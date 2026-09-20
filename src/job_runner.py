"""Small database-backed job queue used by every API worker.

Jobs are claimed with a short lease and a project-level database lease. Any
worker can recover a job left running by a crashed worker after its lease
expires; process-local locks are only an optimization, never the source of
truth.
"""
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from typing import Callable, Optional
import uuid

from sqlalchemy import or_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.db.models import Job, Project

LEASE_SECONDS = 300
POLL_SECONDS = 1.0


def _now():
    # SQLite stores DateTime values without timezone information in this
    # project, so use UTC-naive values consistently for lease comparisons.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def claim_job(bind, preferred_id: Optional[int] = None):
    """Atomically claim one queued or expired job and return its identity."""
    worker_id = uuid.uuid4().hex
    now = _now()
    with Session(bind) as db:
        query = db.query(Job).filter(
            or_(
                Job.status == "queued",
                (Job.status == "running") & (Job.lease_until < now),
            )
        )
        if preferred_id is not None:
            query = query.filter(Job.id == preferred_id)
        job = query.order_by(Job.created_at.asc(), Job.id.asc()).first()
        if not job:
            return None

        project = db.query(Project).filter(Project.name == job.project_name).first()
        if not project:
            job.status = "failed"
            job.error = "Project no longer exists"
            job.finished_at = now
            db.commit()
            return None

        if project.active_job_id and project.active_job_id != job.id:
            active = db.query(Job).filter(Job.id == project.active_job_id).first()
            if active and active.status == "running" and active.lease_until and active.lease_until >= now:
                return None
            project.active_job_id = None

        project.active_job_id = job.id
        job.status = "running"
        job.worker_id = worker_id
        job.attempts = (job.attempts or 0) + 1
        job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
        job.started_at = job.started_at or now
        db.commit()
        return job.id, worker_id


def renew_lease(bind, job_id: int, worker_id: str) -> None:
    with Session(bind) as db:
        job = db.query(Job).filter(Job.id == job_id, Job.worker_id == worker_id, Job.status == "running").first()
        if job:
            job.lease_until = _now() + timedelta(seconds=LEASE_SECONDS)
            db.commit()


def finish_job(bind, job_id: int, status: str, *, result_status: Optional[str] = None, error: Optional[str] = None) -> None:
    now = _now()
    with Session(bind) as db:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return
        job.status = status
        job.result_status = result_status
        job.error = error
        job.finished_at = now
        job.lease_until = None
        project = db.query(Project).filter(Project.name == job.project_name, Project.active_job_id == job.id).first()
        if project:
            project.active_job_id = None
        db.commit()


def process_job(bind, executor: Callable[[int, object], Optional[str]], preferred_id: Optional[int] = None) -> bool:
    try:
        claimed = claim_job(bind, preferred_id)
    except OperationalError:
        # A transient SQLite/PostgreSQL lock or outage must not kill the
        # polling thread; the next poll can retry the claim.
        return False
    if not claimed:
        return False
    job_id, worker_id = claimed
    stop = Event()

    def heartbeat():
        while not stop.wait(30):
            try:
                renew_lease(bind, job_id, worker_id)
            except OperationalError:
                continue

    heartbeat_thread = Thread(target=heartbeat, name=f"job-heartbeat-{job_id}", daemon=True)
    heartbeat_thread.start()
    try:
        result_status = executor(job_id, bind)
        try:
            finish_job(bind, job_id, "succeeded", result_status=result_status)
        except OperationalError:
            pass
    except Exception as exc:
        try:
            finish_job(bind, job_id, "failed", error=f"{type(exc).__name__}: {exc}")
        except OperationalError:
            pass
    finally:
        stop.set()
    return True


def start_worker(bind, executor: Callable[[int, object], Optional[str]], *, enabled: bool = True):
    """Start one polling worker for an API process; safe to call per worker."""
    if not enabled:
        return None, None
    stop = Event()

    def loop():
        while not stop.is_set():
            if not process_job(bind, executor):
                stop.wait(POLL_SECONDS)

    thread = Thread(target=loop, name="durable-job-worker", daemon=True)
    thread.start()
    return thread, stop
