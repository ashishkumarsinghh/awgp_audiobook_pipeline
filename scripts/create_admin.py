import sys
import os
import bcrypt

# Add root directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.database import engine
from src.db.models import User
from sqlalchemy.orm import Session

def create_or_update_admin(
    username="admin",
    password="adminpassword123",
    full_name="System Administrator",
    email="admin@awgp.org",
    phone="+91 9999999999"
):
    with Session(engine) as session:
        user = session.query(User).filter(User.username == username).first()
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        if user:
            user.password_hash = hashed
            user.role = "admin"
            user.full_name = full_name
            user.email = email
            user.phone = phone
            user.allocation_status = "active"
            print(f"Existing user '{username}' updated to ADMIN with new password.")
        else:
            user = User(
                username=username,
                password_hash=hashed,
                role="admin",
                full_name=full_name,
                email=email,
                phone=phone,
                allocation_status="active"
            )
            session.add(user)
            print(f"New user '{username}' created as ADMIN.")

        session.commit()
        print("Admin Account Details:")
        print(f"  Username: {username}")
        print("  Role:     admin")

if __name__ == "__main__":
    u = sys.argv[1] if len(sys.argv) > 1 else "admin"
    p = sys.argv[2] if len(sys.argv) > 2 else "adminpassword123"
    create_or_update_admin(username=u, password=p)
