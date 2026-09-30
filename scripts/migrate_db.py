"""Migrate an existing SQLite database without resetting project data."""
import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def migrate(database):
    database = Path(database).resolve()
    if not database.is_file():
        raise FileNotFoundError(f"Database not found: {database}. Start the API once to create a new database.")
    with sqlite3.connect(database) as source:
        project_columns = {row[1] for row in source.execute("PRAGMA table_info(projects)")}
        if not project_columns:
            raise ValueError("The database has no projects table.")
        project_migrations = {
            "tts_provider": "ALTER TABLE projects ADD COLUMN tts_provider VARCHAR DEFAULT 'edge'",
            "tts_voice": "ALTER TABLE projects ADD COLUMN tts_voice VARCHAR DEFAULT 'hi-IN-SwaraNeural'",
            "book_identifier": "ALTER TABLE projects ADD COLUMN book_identifier VARCHAR",
            "display_name": "ALTER TABLE projects ADD COLUMN display_name VARCHAR",
            "active_job_id": "ALTER TABLE projects ADD COLUMN active_job_id INTEGER",
            "version": "ALTER TABLE projects ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
        }
        statements = [project_migrations[name] for name in project_migrations if name not in project_columns]

        jobs_table = source.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
        ).fetchone()
        if not jobs_table:
            statements.append(
                """CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY,
                    project_name VARCHAR NOT NULL,
                    stage VARCHAR NOT NULL,
                    force BOOLEAN NOT NULL DEFAULT 0,
                    status VARCHAR NOT NULL DEFAULT 'queued',
                    requested_by INTEGER,
                    worker_id VARCHAR,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    lease_until DATETIME,
                    error TEXT,
                    result_status VARCHAR,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    started_at DATETIME,
                    finished_at DATETIME,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )"""
            )

        candidate_table = source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='candidates'").fetchone()
        if candidate_table:
            candidate_columns = {row[1] for row in source.execute("PRAGMA table_info(candidates)")}
            if "predecessor_id" not in candidate_columns:
                statements.append("ALTER TABLE candidates ADD COLUMN predecessor_id INTEGER")
        issue_table = source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='review_issues'").fetchone()
        if issue_table:
            issue_columns = {row[1] for row in source.execute("PRAGMA table_info(review_issues)")}
            if "parent_issue_id" not in issue_columns:
                statements.append("ALTER TABLE review_issues ADD COLUMN parent_issue_id INTEGER")

        corrections_table = source.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='corrections'"
        ).fetchone()
        if not corrections_table:
            statements.append(
                """CREATE TABLE corrections (
                    id INTEGER PRIMARY KEY,
                    project_name VARCHAR NOT NULL,
                    base_version INTEGER NOT NULL,
                    candidate_id INTEGER,
                    issue_id INTEGER,
                    kind VARCHAR NOT NULL,
                    segment_id VARCHAR,
                    expected_text TEXT,
                    operation_json TEXT NOT NULL,
                    status VARCHAR NOT NULL DEFAULT 'applied',
                    conflict_detail TEXT,
                    created_by INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )"""
            )

        user_columns = {row[1] for row in source.execute("PRAGMA table_info(users)")}
        if user_columns:
            user_migrations = {
                "recording_type": "ALTER TABLE users ADD COLUMN recording_type VARCHAR",
                "language": "ALTER TABLE users ADD COLUMN language VARCHAR",
            }
            statements.extend(user_migrations[name] for name in user_migrations if name not in user_columns)

        if not statements:
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = database.with_name(f"{database.name}.backup-{stamp}")
        with sqlite3.connect(backup) as target:
            source.backup(target)
        source.execute("BEGIN IMMEDIATE")
        try:
            for statement in statements:
                source.execute(statement)
            source.commit()
        except Exception:
            source.rollback()
            raise
        return backup


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="audiobook_pipeline.db")
    args = parser.parse_args()
    backup = migrate(args.database)
    print(f"Migration complete. Backup: {backup}" if backup else "Database already up to date.")
