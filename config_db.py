
import sqlite3
import json
import os
from typing import Dict, Any, List

# The database file for storing connection configurations
DB_FILE = os.path.join(os.path.dirname(__file__), "mcp_config.sqlite3")

def init_db():
    """Initializes the database and creates the connections table if it doesn't exist."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS connections (
            alias TEXT PRIMARY KEY,
            db_type TEXT NOT NULL,
            params_json TEXT NOT NULL
        )
        """)
        conn.commit()

def add_connection(alias: str, db_type: str, params: Dict[str, Any]):
    """
    Adds or updates a database connection in the config database.
    The alias is the primary key; if it exists, it will be replaced.
    """
    params_json = json.dumps(params)
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO connections (alias, db_type, params_json)
        VALUES (?, ?, ?)
        """, (alias, db_type, params_json))
        conn.commit()

def remove_connection(alias: str) -> bool:
    """Removes a database connection from the config database."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM connections WHERE alias = ?", (alias,))
        conn.commit()
        return cursor.rowcount > 0

def get_connection(alias: str) -> Dict[str, Any]:
    """Retrieves a single connection's details by its alias."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT db_type, params_json FROM connections WHERE alias = ?", (alias,))
        row = cursor.fetchone()
        if row:
            db_type, params_json = row
            params = json.loads(params_json)
            # This structure is for compatibility with the execute_query function
            if db_type == "mongo":
                 return {"type": db_type, "uri": params.get("uri"), "dbname": params.get("dbname")}
            else:
                 return {"type": db_type, "conn_params": params}
        return None

def get_all_connections() -> Dict[str, Any]:
    """Retrieves all configured connections."""
    configs = {}
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT alias, db_type, params_json FROM connections")
        rows = cursor.fetchall()
        for row in rows:
            alias, db_type, params_json = row
            params = json.loads(params_json)
            # This structure is for compatibility with the execute_query function
            if db_type == "mongo":
                configs[alias] = {"type": db_type, "uri": params.get("uri"), "dbname": params.get("dbname")}
            else:
                configs[alias] = {"type": db_type, "conn_params": params}
    return configs

