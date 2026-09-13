from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.sql import func
from src.db.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String, default="editor") # admin, editor
    
    # Allocation Details
    full_name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    recording_type = Column(String, nullable=True)  # e.g. AI audiobook narration
    language = Column(String, nullable=True)  # Hindi, Sanskrit, or bilingual
    allocation_status = Column(String, default="unregistered") # unregistered, pending, active

class Project(Base):
    __tablename__ = 'projects'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    display_name = Column(String, nullable=True)
    book_identifier = Column(String, unique=True, index=True, nullable=True)
    status = Column(String, default='00_Starting', index=True)
    assigned_to = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    tts_provider = Column(String, default='edge')
    tts_voice = Column(String, default='hi-IN-SwaraNeural')
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    project_name = Column(String, index=True)
    stage = Column(String, index=True)
    action = Column(String)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    timestamp = Column(DateTime, server_default=func.now(), index=True)
    details = Column(Text, nullable=True)

class Artifact(Base):
    __tablename__ = "artifacts"
    id = Column(Integer, primary_key=True, index=True)
    project_name = Column(String, index=True)
    stage = Column(String, index=True) # e.g., "00_OCR", "01_Text_Refinement", "02_Segmentation", "03_Phonetics", "04_Audio", "05_Mastered"
    filename = Column(String, index=True) # e.g. "asd_ocr_raw_admin_20260912_143000.txt"
    file_type = Column(String) # "txt", "json", "wav", "mp3"
    file_size = Column(Integer, default=0)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

class Candidate(Base):
    """An immutable mastered output awaiting an editorial decision."""
    __tablename__ = "candidates"
    id = Column(Integer, primary_key=True, index=True)
    project_name = Column(String, ForeignKey("projects.name"), index=True, nullable=False)
    artifact_filename = Column(String, nullable=False)
    sha256 = Column(String, nullable=False, index=True)
    status = Column(String, default="pending_review", index=True)  # pending_review, approved, superseded
    source_status = Column(String, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)

class ReviewIssue(Base):
    __tablename__ = "review_issues"
    id = Column(Integer, primary_key=True, index=True)
    project_name = Column(String, ForeignKey("projects.name"), index=True, nullable=False)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    body = Column(Text, nullable=False)
    severity = Column(String, default="major")  # blocker, major, minor
    status = Column(String, default="open", index=True)  # open, resolved, dismissed, reopened
    stage = Column(String, nullable=True)
    page_number = Column(Integer, nullable=True)
    start_seconds = Column(Integer, nullable=True)
    end_seconds = Column(Integer, nullable=True)
    segment_id = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)

class ReviewDecision(Base):
    __tablename__ = "review_decisions"
    id = Column(Integer, primary_key=True, index=True)
    project_name = Column(String, ForeignKey("projects.name"), index=True, nullable=False)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    decision = Column(String, nullable=False)  # approved, changes_requested, saved
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
