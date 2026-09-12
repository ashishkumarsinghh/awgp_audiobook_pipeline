"""Add project TTS settings to an existing SQLite database without resetting data."""
import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def migrate(database):
    database = Path(database).resolve()
    if not database.is_file():
        raise FileNotFoundError(f"Database not found: {database}. Start the API once to create a new database.")
    with sqlite3.connect(database) as source:
        columns = {row[1] for row in source.execute("PRAGMA table_info(projects)")}
        if not columns:
            raise ValueError("The database has no projects table.")
        migrations = {
            "tts_provider": "ALTER TABLE projects ADD COLUMN tts_provider VARCHAR DEFAULT 'edge'",
            "tts_voice": "ALTER TABLE projects ADD COLUMN tts_voice VARCHAR DEFAULT 'hi-IN-SwaraNeural'",
        }
        missing = [name for name in migrations if name not in columns]
        if not missing:
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = database.with_name(f"{database.name}.backup-{stamp}")
        with sqlite3.connect(backup) as target:
            source.backup(target)
        source.execute("BEGIN IMMEDIATE")
        try:
            for name in missing:
                source.execute(migrations[name])
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
