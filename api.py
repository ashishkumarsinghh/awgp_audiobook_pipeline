import os
import re
import json
from dotenv import load_dotenv

load_dotenv()

import fitz
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
import jwt
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timedelta, timezone

from fastapi.responses import FileResponse
from pydantic import BaseModel
import shutil
import bcrypt
from sqlalchemy.orm import Session

from src.pipeline_v3 import ProjectManager
from src.db.database import engine, Base, get_db
from src.db.models import User, AuditLog, Project, Artifact

# Init DB
Base.metadata.create_all(bind=engine)

app = FastAPI(title="AWGP Audiobook Pipeline API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECTS_DIR = os.path.abspath("projects")

SECRET_KEY = "awgp_super_secret_key_32_bytes_long_for_security_compliance"
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
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")


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
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
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


class UserCreate(BaseModel):
    username: str
    password: str


@app.post("/api/signup")
def signup(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username taken")
    hashed = bcrypt.hashpw(user.password.encode('utf-8'), bcrypt.gensalt())
    role = "admin" if db.query(User).count() == 0 or user.username.lower() == "admin" else "editor"
    new_user = User(username=user.username, password_hash=hashed.decode('utf-8'), role=role)
    db.add(new_user)
    db.commit()
    access_token = create_access_token(data={"sub": str(new_user.id)})
    return {"status": "success", "token": access_token, "username": new_user.username, "role": new_user.role, "user_id": new_user.id}

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
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
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
    new_proj = Project(name=name, status="00_Ingested")
    db.add(new_proj)
    db.commit()
        
    # Audit log (Upload)
    log = AuditLog(project_name=name, stage="00_Ingested", action="UPLOADED PDF", user_id=user_id)
    db.add(log)
    db.commit()

    # Save artifact record
    save_artifact_record(db, name, "00_pdf_ingested", "pdf", pdf_path, current_user.username, user_id)
        
    return {"status": "success", "project": name, "stage": "00_Ingested"}


class AllocationRequest(BaseModel):
    user_id: Optional[int] = None
    full_name: str
    email: str
    phone: str

@app.post("/api/users/request-allocation")
def request_allocation(req: AllocationRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    u = db.query(User).filter(User.id == current_user.id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.full_name = req.full_name
    u.email = req.email
    u.phone = req.phone
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
        "users": [{"id": u.id, "username": u.username, "full_name": u.full_name, "email": u.email, "phone": u.phone} for u in reqs],
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

def _get_project_artifacts(project_name: str) -> dict:
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

    # Audio synthesis progress tracking
    phon_path = os.path.join(p_dir, "04_phonetics.json")
    audio_dir = os.path.join(p_dir, "05_audio_chunks")
    total_chunks = 0
    completed_chunks = 0
    if os.path.exists(phon_path):
        try:
            with open(phon_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                total_chunks = len(data)
        except Exception:
            pass
    if os.path.exists(audio_dir):
        try:
            completed_chunks = len([f for f in os.listdir(audio_dir) if f.endswith(".wav") and os.path.getsize(os.path.join(audio_dir, f)) > 100])
        except Exception:
            pass
            
    audio_progress = {
        "completed": completed_chunks,
        "total": total_chunks,
        "percent": int(completed_chunks / total_chunks * 100) if total_chunks > 0 else 0
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

@app.get("/api/projects")
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    projects_db = db.query(Project).all()
    user = current_user
    
    # Editors see assigned projects, admins see all
    projects = projects_db if user.role == "admin" else [p for p in projects_db if p.assigned_to == user.id]
    
    result = []
    for p in projects:
        artifacts = _get_project_artifacts(p.name)
        assigned_user = db.query(User).filter(User.id == p.assigned_to).first() if p.assigned_to else None
        result.append({
            "id": p.id,
            "name": p.name,
            "status": p.status,
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
        "in_progress": len([p for p in projects_db if p.status not in ["00_Ingested", "05_Mastered"]]),
        "mastered": len([p for p in projects_db if p.status == "05_Mastered"]),
        "audio_review": len([p for p in projects_db if p.status == "04_Audio_Review"])
    }
    
    return {"projects": sorted(result, key=lambda x: x.get("created_at") or 0, reverse=True), "metrics": metrics}

@app.get("/api/projects/{name}")
def get_project_details(name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    p = db.query(Project).filter(Project.name == name).first()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
        
    artifacts = _get_project_artifacts(name)
    assigned_user = db.query(User).filter(User.id == p.assigned_to).first() if p.assigned_to else None
    
    return {
        "id": p.id,
        "name": p.name,
        "status": p.status,
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
    file_path = os.path.join(PROJECTS_DIR, project_name, "00_scanned.pdf")
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
    p_dir = os.path.join(PROJECTS_DIR, project_name)
    os.makedirs(p_dir, exist_ok=True)
    file_path = os.path.join(p_dir, "01_ocr_raw.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)
    save_artifact_record(db, project_name, "00_ocr_raw", "txt", file_path, current_user.username, current_user.id)
    log = AuditLog(project_name=project_name, stage="01_OCR_Done", action="SAVED RAW TEXT", user_id=current_user.id)
    db.add(log)
    db.commit()
    return {"status": "success"}

@app.put("/api/projects/{project_name}/clean")
def save_clean_text(project_name: str, payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    text = payload.get("text", "")
    p_dir = os.path.join(PROJECTS_DIR, project_name)
    os.makedirs(p_dir, exist_ok=True)
    file_path = os.path.join(p_dir, "02_text_cleaned.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)
    save_artifact_record(db, project_name, "01_text_cleaned", "txt", file_path, current_user.username, current_user.id)
    log = AuditLog(project_name=project_name, stage="01_OCR_Done", action="SAVED CLEANED TEXT", user_id=current_user.id)
    db.add(log)
    db.commit()
    return {"status": "success"}

@app.get("/api/projects/{project_name}/segments")
def get_segments(project_name: str, current_user: User = Depends(get_current_user)):
    pm = ProjectManager(os.path.join(PROJECTS_DIR, project_name))
    
    if os.path.exists(pm.phonetics_file):
        with open(pm.phonetics_file, "r", encoding="utf-8") as f:
            return json.load(f)
    elif os.path.exists(pm.segments_file):
        with open(pm.segments_file, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        raise HTTPException(status_code=404, detail="No segments found. Run Stage 1.")

@app.put("/api/projects/{project_name}/segments")
def update_segments(project_name: str, updates: List[Dict[str, Any]], db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    pm = ProjectManager(os.path.join(PROJECTS_DIR, project_name))
    
    target_file = pm.phonetics_file if os.path.exists(pm.phonetics_file) else pm.segments_file
    if not os.path.exists(target_file):
        target_file = pm.segments_file
        
    with open(target_file, "w", encoding="utf-8") as f:
        json.dump(updates, f, ensure_ascii=False, indent=4)
        
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
    with open(pm.phonetics_file, "w", encoding="utf-8") as f:
        json.dump(updates, f, ensure_ascii=False, indent=4)
    save_artifact_record(db, project_name, "03_phonetics", "json", pm.phonetics_file, current_user.username, current_user.id)
    log = AuditLog(project_name=project_name, stage="03_Phonetics", action="UPDATED PHONETICS", user_id=current_user.id)
    db.add(log)
    db.commit()
    return {"status": "success"}

@app.post("/api/projects/{project_name}/stage/{stage}")
def run_stage(project_name: str, stage: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if stage not in [0, 1, 2, 3, 4]:
        raise HTTPException(status_code=400, detail="Invalid stage. Allowed: 0 (OCR), 1 (Segmentation), 2 (Phonetics), 3 (Audio), 4 (Mastering)")
    pm = ProjectManager(os.path.join(PROJECTS_DIR, project_name))
    
    def _execute_stage():
        if stage == 0:
            pm.run_stage_1_ocr()
            save_artifact_record(db, project_name, "00_ocr_raw", "txt", pm.raw_file, current_user.username, current_user.id)
            return "01_OCR_Done"
        elif stage == 1: 
            pm.run_stage_1_segmentation()
            save_artifact_record(db, project_name, "02_segments", "json", pm.segments_file, current_user.username, current_user.id)
            return "02_Segmentation"
        elif stage == 2: 
            pm.run_stage_2_phonetics()
            save_artifact_record(db, project_name, "03_phonetics", "json", pm.phonetics_file, current_user.username, current_user.id)
            return "03_Phonetics"
        elif stage == 3: 
            pm.run_stage_3_audio()
            return "04_Audio_Review"
        elif stage == 4: 
            pm.run_stage_4_mastering()
            save_artifact_record(db, project_name, "05_mastered", "mp3", pm.master_file, current_user.username, current_user.id)
            return "05_Mastered"

    # Fast synchronous stages: 0 (OCR), 1 (segmentation), 2 (phonetics), 4 (mastering)
    if stage in [1, 2, 4]:
        try:
            status_val = _execute_stage()
            proj = db.query(Project).filter(Project.name == project_name).first()
            if proj:
                proj.status = status_val
                log = AuditLog(project_name=project_name, stage=status_val, action=f"STAGE {stage} COMPLETED", user_id=current_user.id)
                db.add(log)
                db.commit()
            return {"status": "success", "stage": stage, "new_status": status_val}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    elif stage == 0:
        try:
            status_val = _execute_stage()
            proj = db.query(Project).filter(Project.name == project_name).first()
            if proj:
                proj.status = status_val
                log = AuditLog(project_name=project_name, stage=status_val, action="OCR COMPLETED", user_id=current_user.id)
                db.add(log)
                db.commit()
            return {"status": "success", "stage": stage, "new_status": status_val}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        # Stage 3: Audio synthesis runs asynchronously in background
        proj = db.query(Project).filter(Project.name == project_name).first()
        if proj:
            proj.status = "03_Synthesizing"
            log = AuditLog(project_name=project_name, stage="03_Synthesizing", action="AUDIO SYNTHESIS STARTED", user_id=current_user.id)
            db.add(log)
            db.commit()

        def _bg():
            try:
                status_val = _execute_stage()
                with Session(engine) as session:
                    p = session.query(Project).filter(Project.name == project_name).first()
                    if p:
                        p.status = status_val
                        session.add(AuditLog(project_name=project_name, stage=status_val, action="AUDIO GENERATED", user_id=current_user.id))
                        save_artifact_record(session, project_name, "04_audio_synthesis", "json", pm.phonetics_file, current_user.username, current_user.id)
                        session.commit()
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"Background stage 3 error: {e}")
                with Session(engine) as session:
                    p = session.query(Project).filter(Project.name == project_name).first()
                    if p:
                        p.status = "03_Phonetics"
                        session.add(AuditLog(project_name=project_name, stage="03_Phonetics", action=f"AUDIO FAILED: {str(e)[:40]}", user_id=current_user.id))
                        session.commit()
                
        background_tasks.add_task(_bg)
        return {"status": "success", "stage": stage, "async": True, "new_status": "03_Synthesizing", "message": "Audio generation started in background"}

@app.get("/api/projects/{project_name}/audio/{chunk_id}")
def get_audio(project_name: str, chunk_id: str, token: Optional[str] = Query(None)):
    file_path = os.path.join(PROJECTS_DIR, project_name, "05_audio_chunks", f"{chunk_id}.wav")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Audio chunk not found")
    return FileResponse(file_path, media_type="audio/wav")

@app.get("/api/projects/{project_name}/mastered")
def get_mastered_audio(project_name: str, token: Optional[str] = Query(None), current_user: User = Depends(get_current_user)):
    file_path = os.path.join(PROJECTS_DIR, project_name, "06_mastered.mp3")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Mastered audio not found")
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
    file_path = os.path.join(PROJECTS_DIR, project_name, "artifacts", safe_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Artifact file not found")
    media_type = "application/octet-stream"
    if safe_name.endswith(".txt"): media_type = "text/plain; charset=utf-8"
    elif safe_name.endswith(".json"): media_type = "application/json"
    elif safe_name.endswith(".mp3"): media_type = "audio/mpeg"
    elif safe_name.endswith(".wav"): media_type = "audio/wav"
    elif safe_name.endswith(".pdf"): media_type = "application/pdf"
    return FileResponse(file_path, media_type=media_type, filename=safe_name)

@app.get("/api/projects/{project_name}/audit")
def get_audit_logs(project_name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    logs = db.query(AuditLog).filter(AuditLog.project_name == project_name).order_by(AuditLog.timestamp.desc()).all()
    return [{"id": l.id, "stage": l.stage, "action": l.action, "timestamp": l.timestamp.isoformat() if l.timestamp else None, "user_id": l.user_id} for l in logs]

@app.get("/api/dictionary")
def get_dictionary():
    dict_path = "configs/pronunciation.json"
    if os.path.exists(dict_path):
        with open(dict_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
        
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
