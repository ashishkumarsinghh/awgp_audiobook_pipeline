from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import Base, Job, Project
from src.job_runner import claim_job, finish_job


def test_project_job_lease_serializes_and_reclaims(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'jobs.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        db.add(Project(name="book"))
        db.add(Job(project_name="book", stage="4", status="queued"))
        db.commit()

    first = claim_job(engine)
    assert first is not None
    assert claim_job(engine) is None
    finish_job(engine, first[0], "failed", error="synthetic failure")

    with Session(engine) as db:
        recovered = Job(project_name="book", stage="4", status="running", lease_until=(datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)))
        db.add(recovered)
        db.flush()
        db.query(Project).filter(Project.name == "book").update({"active_job_id": recovered.id})
        db.commit()

    reclaimed = claim_job(engine)
    assert reclaimed is not None
    with Session(engine) as db:
        assert db.query(Job).filter(Job.id == reclaimed[0]).one().attempts == 1
