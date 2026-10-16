import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./audiobook_pipeline.db")
if DATABASE_URL.startswith("sqlite:///"):
    db_file = DATABASE_URL[len("sqlite:///"):]
    parent_dir = os.path.dirname(os.path.abspath(db_file) if not db_file.startswith("/") else db_file)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite:") else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
