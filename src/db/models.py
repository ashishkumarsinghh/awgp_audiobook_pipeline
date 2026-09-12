from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
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
    allocation_status = Column(String, default="unregistered") # unregistered, pending, active

class Project(Base):
    __tablename__ = 'projects'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    status = Column(String, default='01_Raw_Text')
    assigned_to = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    project_name = Column(String, index=True)
    stage = Column(String)
    action = Column(String) # e.g., "APPROVED", "EDITED"
    user_id = Column(Integer, ForeignKey("users.id"))
    timestamp = Column(DateTime, server_default=func.now())
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
