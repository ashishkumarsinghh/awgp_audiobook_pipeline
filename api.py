import os
import re
import json
from threading import Lock
from fastapi import Request
from src.core.artifacts import atomic_write, write_json, validate_segments
from src.synthesis.runner import load_manifest, is_current
from dotenv import load_dotenv

load_dotenv()

import fitz
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form, Depends, Query, security, Path
from fastapi.middleware.cors import CORSMiddleware
import jwt
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timedelta, timezone

from fastapi.responses import FileResponse
from pydantic import BaseModel
import shutil
import hashlib
import uuid
import unicodedata
import bcrypt
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text

from src.pipeline_v3 import ProjectManager
from src.synthesis.providers import VOICE_CATALOG
from src.db.database import engine, Base, get_db
from src.db.models import User, AuditLog, Project, Artifact, Candidate, ReviewIssue, ReviewDecision

# Init DB
Base.metadata.create_all(bind=engine)
# Keep deployments created before volunteer allocation metadata compatible.
with engine.begin() as _conn:
    _user_columns = {c["name"] for c in inspect(engine).get_columns("users")}
    for _column in ("recording_type", "language"):
        if _column not in _user_columns:
            _conn.execute(text(f"ALTER TABLE users ADD COLUMN {_column} VARCHAR"))
    _project_columns = {c["name"] for c in inspect(engine).get_columns("projects")}
    if "book_identifier" not in _project_columns:
        _conn.execute(text("ALTER TABLE projects ADD COLUMN book_identifier VARCHAR"))
    if "display_name" not in _project_columns:
        _conn.execute(text("ALTER TABLE projects ADD COLUMN display_name VARCHAR"))

app = FastAPI(title="AWGP Audiobook Pipeline API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list({origin.strip() for origin in os.environ.get("FRONTEND_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173").split(",") if origin.strip()}),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECTS_DIR = os.path.abspath(os.environ.get("PROJECTS_DIR", "projects"))
os.makedirs(PROJECTS_DIR, exist_ok=True)

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "awgp-audiobook-api"}

def _book_slug(title: str, db: Session) -> str:
    normalized = unicodedata.normalize("NFKD", (title or "book").strip()).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:48] or "book"
    while True:
        slug = f"{base}-{uuid.uuid4().hex[:8]}"
        if not db.query(Project).filter(Project.name == slug).first() and not os.path.exists(os.path.join(PROJECTS_DIR, slug)):
            return slug

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
security = HTTPBearer(auto_error=False)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    jwt_token = None
    if credentials:
        jwt_token = credentials.credentials
    elif token:
        jwt_token = token

    if not jwt_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(jwt_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid auth credentials")
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Could not validate credentials")


_project_locks = {}
_locks_guard = Lock()


def project_lock(name):
    with _locks_guard:
        return _project_locks.setdefault(name, Lock())


def project_access(request: Request, db: Session = Depends(get_db),
                   credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
                   token: Optional[str] = Query(None)):
    name = request.path_params.get("project_name") or request.path_params.get("name")
    if not name:
        yield
        return
    user = get_current_user(credentials, token, db)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name):
        raise HTTPException(400, detail="Invalid project name")
    project = db.query(Project).filter(Project.name == name).first()
    if not project:
        raise HTTPException(404, detail="Project not found")
    if user.role != "admin" and project.assigned_to != user.id:
        raise HTTPException(403, detail="This project is not assigned to you")
    root = os.path.realpath(PROJECTS_DIR)
    target = os.path.realpath(os.path.join(root, name))
    if os.path.commonpath([root, target]) != root:
        raise HTTPException(403, detail="Invalid project path")
    lock = project_lock(name)
    mutation = request.method in {"POST", "PUT", "DELETE"}
    if mutation and "stage" not in request.path_params:
        if not lock.acquire(blocking=False):
            raise HTTPException(409, detail="A project operation is running. Wait before editing.")
        try:
            yield
        finally:
            lock.release()
    else:
        yield


app.router.dependencies.append(Depends(project_access))


def save_artifact_record(
    db: Session,
    project_name: str,
    stage: str,
    file_type: str,
    source_file: str,
    username: str,
    user_id: Optional[int] = None
) -> Optional[str]:
    """Saves a timestamped, user-tagged version of an artifact to artifacts/ and records in DB."""
    if not os.path.exists(source_file):
        return None
    # Include microsecond segment to ensure uniqueness even in rapid automated tests
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    clean_username = re.sub(r'[^a-zA-Z0-9_]', '', username or "system")
    clean_book = re.sub(r'[^a-zA-Z0-9_]', '', project_name)
    stage_slug = stage.lower().replace(" ", "_")
    artifact_filename = f"{clean_book}_{stage_slug}_{clean_username}_{now_str}.{file_type}"

    artifacts_dir = os.path.join(PROJECTS_DIR, project_name, "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)
    target_path = os.path.join(artifacts_dir, artifact_filename)

    shutil.copyfile(source_file, target_path)
    file_size = os.path.getsize(target_path)

    art = Artifact(
        project_name=project_name,
        stage=stage,
        filename=artifact_filename,
        file_type=file_type,
        file_size=file_size,
        user_id=user_id,
        username=username
    )
    db.add(art)
    db.commit()
    return artifact_filename

def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    recording_type: Optional[str] = None
    language: Optional[str] = None


@app.post("/api/signup")
def signup(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username taken")
    hashed = bcrypt.hashpw(user.password.encode('utf-8'), bcrypt.gensalt())
    role = "admin" if db.query(User).count() == 0 else "editor"
    new_user = User(username=user.username, password_hash=hashed.decode('utf-8'), role=role,
                    full_name=user.full_name, email=user.email, phone=user.phone,
                    recording_type=user.recording_type, language=user.language)
    db.add(new_user)
    db.commit()
    access_token = create_access_token(data={"sub": str(new_user.id)})
    return {"status": "success", "token": access_token, "username": new_user.username, "role": new_user.role,
            "user_id": new_user.id, "allocation_status": new_user.allocation_status}

@app.post("/api/login")
def login(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if not db_user or not bcrypt.checkpw(user.password.encode('utf-8'), db_user.password_hash.encode('utf-8')):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": str(db_user.id)})
    return {"status": "success", "token": access_token, "username": db_user.username, "user_id": db_user.id, "role": db_user.role}


@app.post("/api/projects")
async def create_project(
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    display_name: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Validate project name (alphanumeric, underscore, dash, max 64 chars)
    display_title = (display_name or name).strip()
    if not display_title or len(display_title) > 200:
        raise HTTPException(status_code=400, detail="Book name is required and must be at most 200 characters.")
    if display_name:
        name = _book_slug(display_title, db)
    elif not re.match(r'^[a-zA-Z0-9_-]{1,64}$', name):
        raise HTTPException(status_code=400, detail="Invalid project name. Use alphanumeric, underscore, or dash. Max 64 chars.")
    # Validate file
    if file.content_type not in ["application/pdf", "application/x-pdf"]:
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Check file size (max 50MB)
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    if file_size > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size must be less than 50MB")

    user_id = current_user.id
    project_dir = os.path.join(PROJECTS_DIR, name)
    if os.path.exists(project_dir) or db.query(Project).filter(Project.name == name).first():
        raise HTTPException(status_code=400, detail="Project already exists")
    os.makedirs(project_dir, exist_ok=True)

    # Save PDF
    pdf_path = os.path.join(project_dir, "00_scanned.pdf")
    with open(pdf_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Add to DB
    new_proj = Project(name=name, display_name=display_title, book_identifier=f"AWGP-{uuid.uuid4().hex[:12].upper()}", status="00_Starting")
    db.add(new_proj)
    db.commit()

    # Audit log (Upload)
    log = AuditLog(project_name=name, stage="00_Starting", action="UPLOADED PDF", user_id=user_id)
    db.add(log)
    db.commit()

    # Save artifact record
    save_artifact_record(db, name, "00_pdf_ingested", "pdf", pdf_path, current_user.username, user_id)

    return {"status": "success", "project": name, "book_identifier": new_proj.book_identifier, "stage": "00_Starting"}

@app.delete("/api/projects/{name}")
def delete_project(name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete a project and its production artifacts. Administrators only."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name):
        raise HTTPException(status_code=400, detail="Invalid project name")
    project = db.query(Project).filter(Project.name == name).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    root = os.path.realpath(PROJECTS_DIR)
    target = os.path.realpath(os.path.join(root, name))
    if os.path.commonpath([root, target]) != root:
        raise HTTPException(status_code=403, detail="Invalid project path")
    if os.path.isdir(target):
        shutil.rmtree(target)
    db.query(ReviewIssue).filter(ReviewIssue.project_name == name).delete(synchronize_session=False)
    db.query(ReviewDecision).filter(ReviewDecision.project_name == name).delete(synchronize_session=False)
    db.query(Candidate).filter(Candidate.project_name == name).delete(synchronize_session=False)
    db.query(Artifact).filter(Artifact.project_name == name).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.project_name == name).delete(synchronize_session=False)
    db.delete(project)
    db.commit()
    return {"status": "success", "deleted": name}


class AllocationRequest(BaseModel):
    user_id: Optional[int] = None
    full_name: str
    email: str
    phone: str
    recording_type: Optional[str] = None
    language: Optional[str] = None


class TTSProviderRequest(BaseModel):
    provider: str
    voice: Optional[str] = None

class ReviewIssueRequest(BaseModel):
    body: str
    severity: str = "major"
    stage: Optional[str] = None
    page_number: Optional[int] = None
    start_seconds: Optional[int] = None
    end_seconds: Optional[int] = None
    segment_id: Optional[str] = None

class ReviewDecisionRequest(BaseModel):
    decision: str
    summary: Optional[str] = None

def _validate_tts_selection(provider: str, voice: Optional[str]) -> str:
    provider = "google" if provider == "gemini" else provider
    options = [v["voice"] for v in VOICE_CATALOG if v["provider"] == provider]
    if voice and voice not in options:
        raise HTTPException(422, detail="Voice is not in the curated Hindi/Sanskrit voice catalog")
    return voice or ("hi-IN-Neural2-A" if provider == "google" else "hi-IN-SwaraNeural")

@app.get("/api/settings/tts-provider")
def get_tts_provider(current_user: User = Depends(get_current_user)):
    provider = os.environ.get('TTS_PROVIDER', 'edge')
    voice = os.environ.get('TTS_VOICE', 'hi-IN-SwaraNeural')
    return {"provider": provider, "voice": voice}

@app.get("/api/tts/voices")
def get_tts_voices(current_user: User = Depends(get_current_user)):
    return {"voices": VOICE_CATALOG}


@app.post("/api/settings/tts-provider")
def set_tts_provider(req: TTSProviderRequest, current_user: User = Depends(get_current_user)):
    if req.provider not in ['edge', 'google', 'azure', 'gemini']:
        raise HTTPException(status_code=400, detail="Provider must be 'edge', 'google' or 'azure'")
    req.voice = _validate_tts_selection(req.provider, req.voice)
    os.environ['TTS_PROVIDER'] = "google" if req.provider == "gemini" else req.provider
    if req.voice:
        os.environ['TTS_VOICE'] = req.voice
    return {"status": "success", "provider": os.environ['TTS_PROVIDER'], "voice": os.environ.get('TTS_VOICE')}


@app.post("/api/users/request-allocation")
def request_allocation(req: AllocationRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    u = db.query(User).filter(User.id == current_user.id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.full_name = req.full_name
    u.email = req.email
    u.phone = req.phone
    u.recording_type = req.recording_type
    u.language = req.language
    u.allocation_status = "pending"
    db.commit()
    return {"status": "success"}

@app.get("/api/admin/allocation-requests")
def get_allocation_requests(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(403, detail="Admin only")
    reqs = db.query(User).filter(User.allocation_status == "pending").all()
    unassigned_projects = db.query(Project).filter(Project.assigned_to == None).all()
    return {
        "users": [{"id": u.id, "username": u.username, "full_name": u.full_name, "email": u.email, "phone": u.phone,
                    "recording_type": u.recording_type, "language": u.language} for u in reqs],
        "unassigned_projects": [{"id": p.id, "name": p.name} for p in unassigned_projects]
    }

@app.post("/api/admin/allocate-user")
def allocate_user(
    user_id: int = Form(...),
    project_id: Optional[int] = Form(None),
    project_name: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(403, detail="Admin only")
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, detail="User not found")

    p = None
    if project_id:
        p = db.query(Project).filter(Project.id == project_id).first()
    elif project_name:
        p = db.query(Project).filter(Project.name == project_name).first()

    if not p:
        raise HTTPException(404, detail="Project not found")

    p.assigned_to = u.id
    u.allocation_status = "active"

    log = AuditLog(project_name=p.name, stage=p.status, action=f"ALLOCATED TO {u.username}", user_id=current_user.id)
    db.add(log)
    db.commit()
    return {"status": "success"}


@app.get("/api/users")
def get_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    users = db.query(User).filter(User.role == "editor").all()
    return [{"id": u.id, "username": u.username, "full_name": u.full_name, "allocation_status": u.allocation_status} for u in users]

@app.post("/api/projects/{name}/assign")
def assign_project(
    name: str,
    user_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(403, detail="Admin only")
    proj = db.query(Project).filter(Project.name == name).first()
    if not proj:
        raise HTTPException(404, detail="Project not found")

    if user_id and user_id > 0:
        assigned_user = db.query(User).filter(User.id == user_id).first()
        if not assigned_user:
            raise HTTPException(404, detail="Assigned user not found")
        proj.assigned_to = user_id
        assigned_user.allocation_status = "active"
        log_action = f"ASSIGNED TO {assigned_user.username}"
    else:
        proj.assigned_to = None
        log_action = "UNASSIGNED"

    log = AuditLog(project_name=name, stage=proj.status, action=log_action, user_id=current_user.id)
    db.add(log)
    db.commit()
    return {"status": "success"}

def _get_project_artifacts(project_name: str, tts_provider=None, tts_voice=None) -> dict:
    p_dir = os.path.join(PROJECTS_DIR, project_name)
    has_pdf = os.path.exists(os.path.join(p_dir, "00_scanned.pdf"))

    raw_path = os.path.join(p_dir, "01_ocr_raw.txt")
    has_raw = False
    if os.path.exists(raw_path):
        try:
            with open(raw_path, "r", encoding="utf-8") as f:
                if not f.read(50).startswith("OCR failed:"):
                    has_raw = True
        except Exception:
            pass

    clean_path = os.path.join(p_dir, "02_text_cleaned.txt")
    has_clean = False
    if os.path.exists(clean_path):
        try:
            with open(clean_path, "r", encoding="utf-8") as f:
                if not f.read(50).startswith("OCR failed:"):
                    has_clean = True
        except Exception:
            pass

    has_seg = os.path.exists(os.path.join(p_dir, "03_segments.json"))
    has_phon = os.path.exists(os.path.join(p_dir, "04_phonetics.json"))
    has_audio = os.path.exists(os.path.join(p_dir, "05_audio_chunks")) and len(os.listdir(os.path.join(p_dir, "05_audio_chunks"))) > 0
    has_master = os.path.exists(os.path.join(p_dir, "06_mastered.mp3"))

    total_chunks = 0
    completed_chunks = 0
    failed_chunks = []
    pace_warnings = []
    manifest = load_manifest(audio_dir := os.path.join(p_dir, "05_audio_chunks"))
    try:
        with open(os.path.join(p_dir, "04_phonetics.json"), encoding="utf-8") as stream:
            data = validate_segments(json.load(stream))
        total_chunks = len(data)
        provider = tts_provider or manifest.get("provider", "edge")
        voice = tts_voice or manifest.get("voice", "hi-IN-MadhurNeural")
        records = manifest.get("chunks", {})
        for item in data:
            record = records.get(item["id"], {})
            if is_current(item, record, audio_dir, provider, voice, verify_audio=False):
                completed_chunks += 1
                if record.get("pace_warning"):
                    pace_warnings.append({"id": item["id"], "wpm": record.get("measured_wpm")})
            elif record.get("status") == "failed":
                failed_chunks.append({"id": item["id"], "error": record.get("error", "Synthesis failed")})
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    has_audio = total_chunks > 0 and completed_chunks == total_chunks
    has_master = has_master and has_audio
    audio_progress = {
        "completed": completed_chunks, "total": total_chunks,
        "percent": int(completed_chunks / total_chunks * 100) if total_chunks else 0,
        "failed": failed_chunks,
        "pace_warnings": pace_warnings,
    }

    return {
        "has_pdf": has_pdf,
        "has_raw_text": has_raw,
        "has_clean_text": has_clean,
        "has_segments": has_seg,
        "has_phonetics": has_phon,
        "has_audio": has_audio,
        "has_mastered": has_master,
        "audio_progress": audio_progress
    }

def _effective_stage(status: str, artifacts: dict) -> str:
    """Return the stage represented by the files that actually exist.

    Database status can lag after a worker restart or a manual artifact edit, so
    the dashboard uses the highest complete artifact as its source of truth.
    Final review decisions remain authoritative.
    """
    if status in ("06_Approved", "06_Changes_Requested", "06_Pending_Second_Approval"):
        return status
    if artifacts.get("has_mastered"):
        return "05_Mastered"
    if artifacts.get("has_audio"):
        return "04_Audio_Review"
    if artifacts.get("has_phonetics"):
        return "03_Phonetics"
    if artifacts.get("has_segments"):
        return "02_Segmentation"
    if artifacts.get("has_clean_text") or artifacts.get("has_raw_text"):
        return "01_OCR_Done"
    return "00_Starting"

@app.get("/api/projects")
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    projects_db = db.query(Project).all()
    user = current_user

    # Editors see assigned projects, admins see all
    projects = projects_db if user.role == "admin" else [p for p in projects_db if p.assigned_to == user.id]

    result = []
    stage_counts = {}
    failed_chunks = 0
    pace_warnings = 0
    open_blockers = 0
    open_issues = 0
    for p in projects:
        artifacts = _get_project_artifacts(p.name, p.tts_provider, p.tts_voice)
        stage = _effective_stage(p.status, artifacts)
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        failed_chunks += len(artifacts.get("audio_progress", {}).get("failed", []))
        pace_warnings += len(artifacts.get("audio_progress", {}).get("pace_warnings", []))
        open_query = db.query(ReviewIssue).filter(
            ReviewIssue.project_name == p.name,
            ReviewIssue.status.in_(["open", "reopened"]),
        )
        open_issues += open_query.count()
        open_blockers += open_query.filter(ReviewIssue.severity == "blocker").count()
        assigned_user = db.query(User).filter(User.id == p.assigned_to).first() if p.assigned_to else None
        result.append({
            "id": p.id,
            "name": p.name,
            "display_name": p.display_name or p.name,
            "book_identifier": p.book_identifier,
            "status": p.status,
            "stage": stage,
            "created_at": p.created_at.timestamp() if p.created_at else 0,
            "assigned_to": p.assigned_to,
            "assigned_to_name": assigned_user.username if assigned_user else "Unassigned",
            "assigned_username": assigned_user.username if assigned_user else "Unassigned",
            "is_assigned_to_me": (p.assigned_to == user.id),
            "artifacts": artifacts,
            **artifacts
        })

    metrics = {
        "total": len(projects_db),
        "unassigned": len([p for p in projects_db if p.assigned_to is None]),
        "in_progress": sum(v for k, v in stage_counts.items() if k not in ("00_Starting", "05_Mastered", "06_Approved")),
        "mastered": stage_counts.get("05_Mastered", 0),
        "audio_review": stage_counts.get("04_Audio_Review", 0),
        "approved": stage_counts.get("06_Approved", 0),
        "changes_requested": stage_counts.get("06_Changes_Requested", 0),
        "open_blockers": open_blockers,
        "open_issues": open_issues,
        "failed_chunks": failed_chunks,
        "pace_warnings": pace_warnings,
        "by_stage": stage_counts,
    }

    return {"projects": sorted(result, key=lambda x: x.get("created_at") or 0, reverse=True), "metrics": metrics}

@app.get("/api/projects/{name}")
def get_project_details(name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    p = db.query(Project).filter(Project.name == name).first()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")

    artifacts = _get_project_artifacts(name, p.tts_provider, p.tts_voice)
    stage = _effective_stage(p.status, artifacts)
    assigned_user = db.query(User).filter(User.id == p.assigned_to).first() if p.assigned_to else None

    return {
        "id": p.id,
        "name": p.name,
        "display_name": p.display_name or p.name,
        "book_identifier": p.book_identifier,
        "status": p.status,
        "stage": stage,
        "assigned_to": p.assigned_to,
        "assigned_to_name": assigned_user.username if assigned_user else "Unassigned",
        "assigned_username": assigned_user.username if assigned_user else "Unassigned",
        "is_assigned_to_me": (p.assigned_to == current_user.id),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "artifacts": artifacts,
        **artifacts
    }

@app.get("/api/projects/{project_name}/pdf")
def get_pdf(project_name: str, token: Optional[str] = Query(None), current_user: User = Depends(get_current_user)):
    file_path = os.path.abspath(os.path.join(PROJECTS_DIR, project_name, "00_scanned.pdf"))
    if not file_path.startswith(os.path.abspath(PROJECTS_DIR)):
        raise HTTPException(status_code=403, detail="Invalid file path")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="PDF file not found")
    return FileResponse(file_path, media_type="application/pdf")

@app.get("/api/projects/{project_name}/raw")
def get_raw_text(project_name: str, current_user: User = Depends(get_current_user)):
    clean_path = os.path.join(PROJECTS_DIR, project_name, "02_text_cleaned.txt")
    raw_path = os.path.join(PROJECTS_DIR, project_name, "01_ocr_raw.txt")

    clean_content = ""
    raw_content = ""

    if os.path.exists(clean_path):
        with open(clean_path, "r", encoding="utf-8") as f:
            clean_content = f.read()

    if os.path.exists(raw_path):
        with open(raw_path, "r", encoding="utf-8") as f:
            raw_content = f.read()

    has_clean = bool(clean_content and not clean_content.startswith("OCR failed:"))

    if not clean_content and not raw_content:
        raise HTTPException(status_code=404, detail="No text found. Please run OCR (Stage 0).")

    effective_text = clean_content if has_clean else raw_content

    return {
        "raw_text": raw_content,
        "clean_text": clean_content,
        "text": effective_text,
        "has_clean": has_clean
    }

@app.put("/api/projects/{project_name}/raw")
def save_raw_text(project_name: str, payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    text = payload.get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(422, detail="Narration text cannot be empty.")
    p_dir = os.path.join(PROJECTS_DIR, project_name)
    os.makedirs(p_dir, exist_ok=True)
    file_path = os.path.join(p_dir, "01_ocr_raw.txt")
    previous = None
    if os.path.isfile(file_path):
        with open(file_path, encoding="utf-8") as stream:
            previous = stream.read()
    if previous != text:
        atomic_write(file_path, text)
        ProjectManager(p_dir).invalidate_after("raw" if file_path.endswith("01_ocr_raw.txt") else "clean")
        project = db.query(Project).filter(Project.name == project_name).first()
        project.status = "01_OCR_Done"
    save_artifact_record(db, project_name, "00_ocr_raw", "txt", file_path, current_user.username, current_user.id)
    log = AuditLog(project_name=project_name, stage="01_OCR_Done", action="SAVED RAW TEXT", user_id=current_user.id)
    db.add(log)
    db.commit()
    return {"status": "success"}

@app.put("/api/projects/{project_name}/clean")
def save_clean_text(project_name: str, payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    text = payload.get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(422, detail="Narration text cannot be empty.")
    p_dir = os.path.join(PROJECTS_DIR, project_name)
    os.makedirs(p_dir, exist_ok=True)
    file_path = os.path.join(p_dir, "02_text_cleaned.txt")
    previous = None
    if os.path.isfile(file_path):
        with open(file_path, encoding="utf-8") as stream:
            previous = stream.read()
    if previous != text:
        atomic_write(file_path, text)
        ProjectManager(p_dir).invalidate_after("raw" if file_path.endswith("01_ocr_raw.txt") else "clean")
        project = db.query(Project).filter(Project.name == project_name).first()
        project.status = "01_OCR_Done"
    save_artifact_record(db, project_name, "01_text_cleaned", "txt", file_path, current_user.username, current_user.id)
    log = AuditLog(project_name=project_name, stage="01_OCR_Done", action="SAVED CLEANED TEXT", user_id=current_user.id)
    db.add(log)
    db.commit()
    return {"status": "success"}

@app.get("/api/projects/{project_name}/segments")
def get_segments(project_name: str, current_user: User = Depends(get_current_user)):
    pm = ProjectManager(os.path.join(PROJECTS_DIR, project_name))

    if os.path.exists(pm.segments_file):
        with open(pm.segments_file, "r", encoding="utf-8") as f:
            return json.load(f)
    raise HTTPException(status_code=404, detail="No segments found. Run Segmentation (API stage 2).")


@app.put("/api/projects/{project_name}/segments")
def update_segments(project_name: str, updates: List[Dict[str, Any]], db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    pm = ProjectManager(os.path.join(PROJECTS_DIR, project_name))

    target_file = pm.segments_file
    if not os.path.exists(target_file):
        target_file = pm.segments_file

    try:
        validate_segments(updates)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc))
    previous = None
    if os.path.isfile(target_file):
        with open(target_file, encoding="utf-8") as stream:
            previous = json.load(stream)
    if previous != updates:
        write_json(target_file, updates)
        pm.invalidate_after("segments")
        db.query(Project).filter(Project.name == project_name).first().status = "02_Segmentation"

    save_artifact_record(db, project_name, "02_segments", "json", target_file, current_user.username, current_user.id)
    log = AuditLog(project_name=project_name, stage="02_Segmentation", action="UPDATED SEGMENTS", user_id=current_user.id)
    db.add(log)
    db.commit()
    return {"status": "success"}

@app.get("/api/projects/{project_name}/phonetics")
def get_phonetics(project_name: str, current_user: User = Depends(get_current_user)):
    pm = ProjectManager(os.path.join(PROJECTS_DIR, project_name))
    if not os.path.exists(pm.phonetics_file):
        raise HTTPException(status_code=404, detail="No phonetics found. Run Stage 2.")
    with open(pm.phonetics_file, "r", encoding="utf-8") as f:
        return json.load(f)

@app.put("/api/projects/{project_name}/phonetics")
def update_phonetics(project_name: str, updates: List[Dict[str, Any]], db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    pm = ProjectManager(os.path.join(PROJECTS_DIR, project_name))
    try:
        validate_segments(updates)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc))
    previous = None
    if os.path.isfile(pm.phonetics_file):
        with open(pm.phonetics_file, encoding="utf-8") as stream:
            previous = json.load(stream)
    if previous != updates:
        write_json(pm.phonetics_file, updates)
        pm.invalidate_after("phonetics")
        db.query(Project).filter(Project.name == project_name).first().status = "03_Phonetics"
    save_artifact_record(db, project_name, "03_phonetics", "json", pm.phonetics_file, current_user.username, current_user.id)
    log = AuditLog(project_name=project_name, stage="03_Phonetics", action="UPDATED PHONETICS", user_id=current_user.id)
    db.add(log)
    db.commit()
    return {"status": "success"}

@app.post("/api/projects/{project_name}/stage/{stage}")
def run_stage(project_name: str, stage: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Validate stage (1-5)
    if stage not in [1, 2, 3, 4, 5]:
        raise HTTPException(status_code=400, detail="Invalid stage. Allowed: 1 (OCR), 2 (Segmentation), 3 (Phonetics), 4 (Audio), 5 (Mastering)")

    # Validate project name format
    if not re.match(r'^[a-zA-Z0-9_-]{1,64}$', project_name):
        raise HTTPException(status_code=400, detail="Invalid project name")

    proj = db.query(Project).filter(Project.name == project_name).first()
    tts_provider = proj.tts_provider if proj else None
    tts_voice = proj.tts_voice if proj else None

    pm = ProjectManager(os.path.join(PROJECTS_DIR, project_name), tts_provider, tts_voice)

    actor_id, actor_name = current_user.id, current_user.username
    database_bind = db.get_bind()

    def _execute_stage():
        if stage == 1:
            pm.run_stage_1_ocr()
            save_artifact_record(db, project_name, "00_ocr_raw", "txt", pm.raw_file, current_user.username, current_user.id)
            return "01_OCR_Done"
        elif stage == 2:
            pm.run_stage_1_segmentation()
            save_artifact_record(db, project_name, "02_segments", "json", pm.segments_file, current_user.username, current_user.id)
            return "02_Segmentation"
        elif stage == 3:
            pm.run_stage_2_phonetics()
            save_artifact_record(db, project_name, "03_phonetics", "json", pm.phonetics_file, current_user.username, current_user.id)
            return "03_Phonetics"
        elif stage == 4:
            pm.run_stage_3_audio()
            return "04_Audio_Review"
        elif stage == 5:
            pm.run_stage_4_mastering()
            artifact_name = save_artifact_record(db, project_name, "05_mastered", "mp3", pm.master_file, current_user.username, current_user.id)
            digest = _sha256_file(pm.master_file)
            existing = db.query(Candidate).filter(Candidate.project_name == project_name,
                                                   Candidate.sha256 == digest).first()
            if existing:
                existing.artifact_filename = artifact_name or existing.artifact_filename
            else:
                db.query(Candidate).filter(Candidate.project_name == project_name,
                                           Candidate.status == "pending_review").update({"status": "superseded"})
                db.add(Candidate(project_name=project_name,
                                 artifact_filename=artifact_name or os.path.basename(pm.master_file),
                                 sha256=digest, status="pending_review",
                                 source_status="05_Mastered", created_by=current_user.id))
            return "05_Mastered"

    lock = project_lock(project_name)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, detail="A project operation is already running.")

    # Fast synchronous stages: 1 (OCR), 2 (segmentation), 3 (phonetics), 5 (mastering)
    if stage in [1, 2, 3, 5]:
        try:
            status_val = _execute_stage()
            proj = db.query(Project).filter(Project.name == project_name).first()
            if proj:
                proj.status = status_val
                log = AuditLog(project_name=project_name, stage=status_val, action=f"STAGE {stage} COMPLETED", user_id=current_user.id)
                db.add(log)
                db.commit()
            return {"status": "success", "stage": stage, "new_status": status_val}
        except (ValueError, FileNotFoundError) as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            lock.release()
    else:
        try:
            # Stage 4: Audio synthesis runs asynchronously in background
            proj = db.query(Project).filter(Project.name == project_name).first()
            if proj:
                proj.status = "04_Synthesizing"
                log = AuditLog(project_name=project_name, stage="04_Synthesizing", action="AUDIO SYNTHESIS STARTED", user_id=current_user.id)
                db.add(log)
                db.commit()
        except Exception:
            lock.release()
            raise

        def _bg():
            try:
                pm.run_stage_3_audio()
                status_val = "04_Audio_Review"
                with Session(database_bind) as session:
                    p = session.query(Project).filter(Project.name == project_name).first()
                    if p:
                        p.status = status_val
                        session.add(AuditLog(project_name=project_name, stage=status_val, action="AUDIO GENERATED", user_id=actor_id))
                        save_artifact_record(session, project_name, "04_audio_synthesis", "json", pm.phonetics_file, actor_name, actor_id)
                        session.commit()
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"Background stage 4 error: {e}")
                try:
                    with Session(database_bind) as session:
                        p = session.query(Project).filter(Project.name == project_name).first()
                        if p:
                            p.status = "03_Phonetics"
                            session.add(AuditLog(project_name=project_name, stage="03_Phonetics", action="AUDIO FAILED", details=str(e), user_id=actor_id))
                            session.commit()
                except Exception as db_err:
                    print(f"Failed to update error status in DB: {db_err}")

            finally:
                lock.release()

        background_tasks.add_task(_bg)
        return {"status": "success", "stage": stage, "async": True, "new_status": "04_Synthesizing", "message": "Audio generation started in background"}

@app.get("/api/projects/{project_name}/audio/{chunk_id}")
def get_audio(project_name: str, chunk_id: str, token: Optional[str] = Query(None),
              db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = db.query(Project).filter(Project.name == project_name).first()
    pm = ProjectManager(os.path.join(PROJECTS_DIR, project_name), project.tts_provider, project.tts_voice)
    try:
        from src.core.artifacts import read_segments
        item = next((item for item in read_segments(pm.phonetics_file) if item["id"] == chunk_id), None)
        record = load_manifest(pm.audio_dir).get("chunks", {}).get(chunk_id, {})
        if item is None or not is_current(item, record, pm.audio_dir, pm.tts_provider, pm.tts.voice):
            raise ValueError("missing or outdated audio")
    except (OSError, ValueError, TypeError, AttributeError):
        raise HTTPException(409, detail="This chunk is missing or outdated. Run Audio to regenerate it.")
    return FileResponse(os.path.join(pm.audio_dir, f"{chunk_id}.wav"), media_type="audio/wav")

@app.get("/api/projects/{project_name}/mastered")
def get_mastered_audio(project_name: str, token: Optional[str] = Query(None), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    file_path = os.path.join(PROJECTS_DIR, project_name, "06_mastered.mp3")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Mastered audio not found")
    project = db.query(Project).filter(Project.name == project_name).first()
    if not _get_project_artifacts(project_name, project.tts_provider, project.tts_voice)["has_mastered"]:
        raise HTTPException(409, detail="This master is outdated or unverified. Run Audio and Mastering again.")
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    download_filename = f"{project_name}_mastered_{current_user.username}_{now_str}.mp3"
    return FileResponse(file_path, media_type="audio/mpeg", filename=download_filename)

@app.get("/api/projects/{project_name}/artifacts")
def list_artifacts(project_name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    records = db.query(Artifact).filter(Artifact.project_name == project_name).order_by(Artifact.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "stage": r.stage,
            "filename": r.filename,
            "file_type": r.file_type,
            "file_size": r.file_size,
            "username": r.username,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "download_url": f"/api/projects/{project_name}/artifacts/{r.filename}"
        }
        for r in records
    ]

@app.get("/api/projects/{project_name}/artifacts/{filename}")
def download_artifact(project_name: str, filename: str, token: Optional[str] = Query(None), current_user: User = Depends(get_current_user)):
    safe_name = os.path.basename(filename)
    file_path = os.path.abspath(os.path.join(PROJECTS_DIR, project_name, "artifacts", safe_name))
    if not file_path.startswith(os.path.abspath(PROJECTS_DIR)):
        raise HTTPException(status_code=403, detail="Invalid file path")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Artifact file not found")
    media_type = "application/octet-stream"
    if safe_name.endswith(".txt"): media_type = "text/plain; charset=utf-8"
    elif safe_name.endswith(".json"): media_type = "application/json"
    elif safe_name.endswith(".mp3"): media_type = "audio/mpeg"
    elif safe_name.endswith(".wav"): media_type = "audio/wav"
    elif safe_name.endswith(".pdf"): media_type = "application/pdf"
    return FileResponse(file_path, media_type=media_type, filename=safe_name)

@app.post("/api/projects/{project_name}/artifacts/{filename}/restore")
def restore_artifact(project_name: str, filename: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Restore an immutable historical text/JSON artifact as the active draft."""
    record = db.query(Artifact).filter(Artifact.project_name == project_name, Artifact.filename == os.path.basename(filename)).first()
    if not record or record.file_type not in ("txt", "json"):
        raise HTTPException(404, detail="Only text and JSON artifacts can be restored")
    source = os.path.abspath(os.path.join(PROJECTS_DIR, project_name, "artifacts", record.filename))
    if not os.path.isfile(source):
        raise HTTPException(404, detail="Artifact file not found")
    target_name = {"00_ocr_raw": "01_ocr_raw.txt", "01_text_cleaned": "02_text_cleaned.txt",
                   "02_segments": "03_segments.json", "03_phonetics": "04_phonetics.json"}.get(record.stage)
    if not target_name:
        raise HTTPException(422, detail="This artifact stage cannot be restored")
    target = os.path.join(PROJECTS_DIR, project_name, target_name)
    shutil.copyfile(source, target)
    pm = ProjectManager(os.path.join(PROJECTS_DIR, project_name))
    pm.invalidate_after({"00_ocr_raw": "raw", "01_text_cleaned": "clean", "02_segments": "segments", "03_phonetics": "phonetics"}[record.stage])
    db.add(AuditLog(project_name=project_name, stage=record.stage, action="RESTORED ARTIFACT AS DRAFT",
                    details=record.filename, user_id=current_user.id))
    db.commit()
    return {"status": "success", "restored": target_name, "source_artifact": record.filename}

@app.get("/api/projects/{project_name}/audit")
def get_audit_logs(project_name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    logs = db.query(AuditLog).filter(AuditLog.project_name == project_name).order_by(AuditLog.timestamp.desc()).all()
    return [{"id": l.id, "stage": l.stage, "action": l.action, "timestamp": l.timestamp.isoformat() if l.timestamp else None, "user_id": l.user_id, "details": l.details} for l in logs]

def _candidate_payload(candidate, db):
    issues = db.query(ReviewIssue).filter(ReviewIssue.candidate_id == candidate.id).order_by(ReviewIssue.created_at.asc()).all()
    decisions = db.query(ReviewDecision).filter(ReviewDecision.candidate_id == candidate.id).order_by(ReviewDecision.created_at.desc()).all()
    return {
        "id": candidate.id, "project_name": candidate.project_name,
        "artifact_filename": candidate.artifact_filename, "sha256": candidate.sha256,
        "status": candidate.status, "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
        "audio_url": f"/api/projects/{candidate.project_name}/review/audio",
        "issues": [{"id": i.id, "body": i.body, "severity": i.severity, "status": i.status,
                    "stage": i.stage, "page_number": i.page_number, "start_seconds": i.start_seconds,
                    "end_seconds": i.end_seconds, "segment_id": i.segment_id,
                    "created_at": i.created_at.isoformat() if i.created_at else None} for i in issues],
        "decisions": [{"id": d.id, "decision": d.decision, "summary": d.summary,
                       "user_id": d.user_id, "created_at": d.created_at.isoformat() if d.created_at else None} for d in decisions],
        "approval_count": len({d.user_id for d in decisions if d.decision == "approved"}),
        "required_approvals": 2,
        "open_blockers": sum(1 for i in issues if i.status in ("open", "reopened") and i.severity == "blocker")
    }

@app.get("/api/projects/{project_name}/review")
def get_review(project_name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    candidate = db.query(Candidate).filter(Candidate.project_name == project_name,
                                           Candidate.status != "superseded").order_by(Candidate.created_at.desc()).first()
    if not candidate:
        raise HTTPException(404, detail="No review candidate exists. Run Mastering first.")
    return _candidate_payload(candidate, db)

@app.get("/api/projects/{project_name}/review/audio")
def get_review_audio(project_name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    candidate = db.query(Candidate).filter(Candidate.project_name == project_name,
                                           Candidate.status != "superseded").order_by(Candidate.created_at.desc()).first()
    if not candidate:
        raise HTTPException(404, detail="No review candidate exists")
    file_path = os.path.abspath(os.path.join(PROJECTS_DIR, project_name, "artifacts", candidate.artifact_filename))
    if not os.path.isfile(file_path):
        raise HTTPException(409, detail="Candidate artifact is missing; restore it before reviewing")
    if _sha256_file(file_path) != candidate.sha256:
        raise HTTPException(409, detail="Candidate artifact integrity check failed")
    return FileResponse(file_path, media_type="audio/mpeg")

@app.post("/api/projects/{project_name}/review/issues")
def create_review_issue(project_name: str, payload: ReviewIssueRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if payload.severity not in ("blocker", "major", "minor"):
        raise HTTPException(422, detail="Severity must be blocker, major or minor")
    if not payload.body.strip():
        raise HTTPException(422, detail="Comment cannot be empty")
    candidate = db.query(Candidate).filter(Candidate.project_name == project_name,
                                           Candidate.status == "pending_review").order_by(Candidate.created_at.desc()).first()
    if not candidate:
        raise HTTPException(409, detail="No pending review candidate")
    issue = ReviewIssue(project_name=project_name, candidate_id=candidate.id, user_id=current_user.id,
                        body=payload.body.strip(), severity=payload.severity, stage=payload.stage,
                        page_number=payload.page_number, start_seconds=payload.start_seconds,
                        end_seconds=payload.end_seconds, segment_id=payload.segment_id)
    db.add(issue)
    db.add(AuditLog(project_name=project_name, stage="06_Final_Review", action="REVIEW ISSUE CREATED",
                    details=payload.body.strip(), user_id=current_user.id))
    db.commit()
    return {"status": "success", "issue_id": issue.id}

@app.patch("/api/projects/{project_name}/review/issues/{issue_id}")
def update_review_issue(project_name: str, issue_id: int, status: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if status not in ("open", "resolved", "dismissed", "reopened"):
        raise HTTPException(422, detail="Invalid issue status")
    issue = db.query(ReviewIssue).filter(ReviewIssue.id == issue_id, ReviewIssue.project_name == project_name).first()
    if not issue:
        raise HTTPException(404, detail="Review issue not found")
    issue.status = status
    if status in ("resolved", "dismissed"):
        issue.resolved_by, issue.resolved_at = current_user.id, datetime.now(timezone.utc)
    else:
        issue.resolved_by, issue.resolved_at = None, None
    db.commit()
    return {"status": "success", "issue_status": issue.status}

@app.post("/api/projects/{project_name}/review/decision")
def submit_review_decision(project_name: str, payload: ReviewDecisionRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if payload.decision not in ("approved", "changes_requested", "saved"):
        raise HTTPException(422, detail="Decision must be approved, changes_requested or saved")
    candidate = db.query(Candidate).filter(Candidate.project_name == project_name,
                                           Candidate.status == "pending_review").order_by(Candidate.created_at.desc()).first()
    if not candidate:
        raise HTTPException(409, detail="No pending review candidate")
    blockers = db.query(ReviewIssue).filter(ReviewIssue.candidate_id == candidate.id,
                                            ReviewIssue.severity == "blocker",
                                            ReviewIssue.status.in_(["open", "reopened"])).count()
    if payload.decision == "approved" and blockers:
        raise HTTPException(409, detail=f"Resolve {blockers} blocking review issue(s) before approval")
    if payload.decision == "approved":
        prior_approvals = db.query(ReviewDecision).filter(
            ReviewDecision.candidate_id == candidate.id,
            ReviewDecision.decision == "approved",
        ).all()
        if any(d.user_id == current_user.id for d in prior_approvals):
            raise HTTPException(409, detail="A second approval must come from a different human reviewer")
    db.add(ReviewDecision(project_name=project_name, candidate_id=candidate.id, user_id=current_user.id,
                          decision=payload.decision, summary=payload.summary))
    if payload.decision == "approved":
        approval_count = len({d.user_id for d in prior_approvals}) + 1
        if approval_count >= 2:
            candidate.status = "approved"
            db.query(Project).filter(Project.name == project_name).update({"status": "06_Approved"})
        else:
            db.query(Project).filter(Project.name == project_name).update({"status": "06_Pending_Second_Approval"})
    elif payload.decision == "changes_requested":
        db.query(Project).filter(Project.name == project_name).update({"status": "06_Changes_Requested"})
    db.add(AuditLog(project_name=project_name, stage="06_Final_Review", action=f"REVIEW {payload.decision.upper()}",
                    details=payload.summary, user_id=current_user.id))
    db.commit()
    return {"status": "success", "decision": payload.decision, "candidate_id": candidate.id,
            "approval_count": (approval_count if payload.decision == "approved" else None),
            "required_approvals": 2}


@app.get("/api/projects/{project_name}/settings/tts-provider")
def get_project_tts_provider(project_name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    proj = db.query(Project).filter(Project.name == project_name).first()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"provider": proj.tts_provider or "edge", "voice": proj.tts_voice or "hi-IN-SwaraNeural"}


@app.post("/api/projects/{project_name}/settings/tts-provider")
def set_project_tts_provider(project_name: str, req: TTSProviderRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    proj = db.query(Project).filter(Project.name == project_name).first()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if req.provider not in ['edge', 'google', 'azure', 'gemini']:
        raise HTTPException(status_code=400, detail="Provider must be 'edge', 'google' or 'azure'")
    normalized_provider = "google" if req.provider == "gemini" else req.provider
    proj.tts_provider = normalized_provider
    proj.tts_voice = _validate_tts_selection(normalized_provider, req.voice)
    ProjectManager(os.path.join(PROJECTS_DIR, project_name)).invalidate_after("phonetics")
    db.commit()
    return {"status": "success", "provider": proj.tts_provider, "voice": proj.tts_voice}

@app.get("/api/dictionary")
def get_dictionary():
    dict_path = "configs/pronunciation.json"
    if os.path.exists(dict_path):
        with open(dict_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

@app.get("/api/dictionary/explain")
def explain_pronunciation(text: str = Query(..., min_length=1), context: str = Query("general")):
    """Return the reversible pronunciation transformation used for a preview."""
    from src.normalize.pronunciation import PronunciationDictionary
    return PronunciationDictionary().explain(text, context=context)

@app.get("/api/dictionary/analyze-marks")
def analyze_pronunciation_marks(text: str = Query(..., min_length=1)):
    from src.normalize.pronunciation import PronunciationDictionary
    return PronunciationDictionary.analyze_marks(text)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
