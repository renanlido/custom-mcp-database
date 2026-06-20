import json
import os
import sqlite3
from pathlib import Path
from typing import Any


def _resolve_db_file() -> str:
    override = os.environ.get("MCP_DB_CONFIG")
    if override:
        path = Path(override).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    directory = Path(base) / "custom-mcp-database"
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory / "mcp_config.sqlite3")


DB_FILE = _resolve_db_file()


def init_db() -> None:
    """Create the connections table if it doesn't exist."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS connections (
                alias TEXT PRIMARY KEY,
                db_type TEXT NOT NULL,
                params_json TEXT NOT NULL
            )
            """
        )
        conn.commit()


def add_connection(alias: str, db_type: str, params: dict[str, Any]) -> None:
    """Add or replace a database connection (alias is the primary key)."""
    params_json = json.dumps(params)
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO connections (alias, db_type, params_json)
            VALUES (?, ?, ?)
            """,
            (alias, db_type, params_json),
        )
        conn.commit()


def remove_connection(alias: str) -> bool:
    """Delete a connection by alias. Returns True if a row was removed."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM connections WHERE alias = ?", (alias,))
        conn.commit()
        return cursor.rowcount > 0


def get_connection(alias: str) -> dict[str, Any] | None:
    """Return a single connection in the shape execute_query expects, or None."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT db_type, params_json FROM connections WHERE alias = ?", (alias,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        db_type, params_json = row
        params = json.loads(params_json)
        if db_type == "mongo":
            return {"type": db_type, "uri": params.get("uri"), "dbname": params.get("dbname")}
        return {"type": db_type, "conn_params": params}


def get_all_connections() -> dict[str, Any]:
    """Return every configured connection keyed by alias."""
    configs: dict[str, Any] = {}
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT alias, db_type, params_json FROM connections")
        for alias, db_type, params_json in cursor.fetchall():
            params = json.loads(params_json)
            if db_type == "mongo":
                configs[alias] = {
                    "type": db_type,
                    "uri": params.get("uri"),
                    "dbname": params.get("dbname"),
                }
            else:
                configs[alias] = {"type": db_type, "conn_params": params}
    return configs
