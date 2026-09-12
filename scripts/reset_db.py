import os
import sys
import shutil
import bcrypt

# Add root directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.database import engine, Base
from src.db.models import User, Project, AuditLog
from sqlalchemy.orm import Session

def reset():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("Database tables dropped and recreated cleanly.")

    projects_dir = os.path.abspath("projects")
    if os.path.exists(projects_dir):
        for item in os.listdir(projects_dir):
            if item == ".gitkeep":
                continue
            item_path = os.path.join(projects_dir, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
                print(f"Removed project directory: {item}")
            elif os.path.isfile(item_path):
                os.remove(item_path)
    print("Projects directory cleared.")

    # Seed default admin
    with Session(engine) as session:
        admin_pw = bcrypt.hashpw("adminpassword123".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        admin_user = User(
            username="admin",
            password_hash=admin_pw,
            role="admin",
            full_name="AWGP Administrator",
            email="admin@awgp.org",
            phone="+91 0000000000",
            allocation_status="active"
        )
        session.add(admin_user)
        session.commit()
        print("Default admin created: username='admin', password='adminpassword123'")

if __name__ == "__main__":
    reset()
