import sqlite3
from scripts.migrate_db import migrate


def test_tts_migration_preserves_projects_and_is_idempotent(tmp_path):
    database = tmp_path / "old.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, name VARCHAR)")
        conn.execute("INSERT INTO projects (name) VALUES ('existing')")
    backup = migrate(database)
    assert backup.is_file()
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT name, tts_provider, tts_voice FROM projects").fetchone() == (
            "existing", "edge", "hi-IN-SwaraNeural")
    with sqlite3.connect(backup) as conn:
        assert len(list(conn.execute("PRAGMA table_info(projects)"))) == 2
        assert conn.execute("SELECT name FROM projects").fetchone()[0] == "existing"
    assert migrate(database) is None
