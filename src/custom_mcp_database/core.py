"""Database-agnostic logic shared by the MCP server and the CLI.

All functions here are plain callables (no MCP/CLI coupling) so they can be reused
and unit-tested. Query execution behavior matches the original implementation.
"""

import json
from typing import Any

import mysql.connector
import oracledb
import psycopg2
import psycopg2.extras
from bson import ObjectId, json_util
from pymongo import MongoClient

from . import config_db

DEFAULT_LIMIT = 10


def convert_objectid_strings(obj: Any) -> Any:
    """Recursively convert ObjectId-shaped values to ObjectId in a Mongo filter.

    Handles ``{"$oid": "..."}`` and bare 24-char hex strings. Kept for backward
    compatibility with existing usage.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, dict) and "$oid" in value:
                try:
                    obj[key] = ObjectId(value["$oid"])
                except Exception:
                    pass
            elif isinstance(value, str) and len(value) == 24:
                try:
                    obj[key] = ObjectId(value)
                except Exception:
                    pass
            elif isinstance(value, dict):
                obj[key] = convert_objectid_strings(value)
            elif isinstance(value, list):
                obj[key] = [
                    convert_objectid_strings(item) if isinstance(item, dict) else item
                    for item in value
                ]
    return obj


def build_and_validate_params(
    db_type: str,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    dbname: str | None = None,
    uri: str | None = None,
) -> dict[str, Any]:
    """Validate inputs and build the driver-specific params dict for storage."""
    if db_type == "mongo":
        if not uri or not dbname:
            raise ValueError("For MongoDB, 'uri' and 'dbname' are required.")
        return {"uri": uri, "dbname": dbname}

    if db_type in ("postgres", "mysql", "oracle"):
        if not all([host, port, user, password, dbname]):
            raise ValueError(
                f"For {db_type}, 'host', 'port', 'user', 'password', and 'dbname' are required."
            )
        params: dict[str, Any] = {"host": host, "port": port, "user": user, "password": password}
        if db_type == "mysql":
            params["database"] = dbname
        else:
            params["dbname"] = dbname
        if db_type == "oracle":
            params["dsn"] = f"{params.pop('host')}:{params.pop('port')}/{params.pop('dbname')}"
        return params

    raise ValueError(f"Unsupported database type: {db_type}")


def list_aliases() -> dict[str, Any]:
    """Return all configured aliases and their database types."""
    db_configs = config_db.get_all_connections()
    aliases = [{"alias": alias, "type": cfg.get("type")} for alias, cfg in db_configs.items()]
    return {"aliases": aliases}


def add_database(
    alias: str,
    db_type: str,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    dbname: str | None = None,
    uri: str | None = None,
) -> dict[str, str]:
    """Persist a new (or replace an existing) database connection."""
    params = build_and_validate_params(db_type, host, port, user, password, dbname, uri)
    config_db.add_connection(alias, db_type, params)
    return {"status": f"Database '{alias}' added successfully."}


def remove_database(alias: str) -> dict[str, str]:
    """Remove a configured connection by alias."""
    if config_db.remove_connection(alias):
        return {"status": f"Database '{alias}' removed successfully."}
    raise ValueError(f"Database alias '{alias}' not found.")


def list_collections(database_alias: str) -> dict[str, Any]:
    """List all collections for a configured MongoDB alias."""
    db_info = config_db.get_connection(database_alias)
    if not db_info:
        raise ValueError(f"Database alias '{database_alias}' not found in configuration.")
    if db_info.get("type") != "mongo":
        raise ValueError(f"Alias '{database_alias}' is not a MongoDB database.")
    try:
        client = MongoClient(db_info["uri"])
        db = client[db_info["dbname"]]
        collections = db.list_collection_names()
        client.close()
        return {"collections": collections}
    except Exception as e:
        raise RuntimeError(f"Failed to list collections for '{database_alias}': {e}") from e


def execute_query(
    database_alias: str,
    query: str | dict[str, Any],
    params: dict[str, Any] | None = None,
    collection: str | None = None,
    oracle_schema: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Execute a query against a configured database and return rows + row_count.

    SQL drivers (postgres/mysql/oracle) run the query as given with parameterized
    binds. MongoDB takes a JSON filter, requires ``collection``, and is capped at
    ``limit`` documents (default 10) with empty filters rejected.
    """
    db_info = config_db.get_connection(database_alias)
    if not db_info:
        raise ValueError(f"Database alias '{database_alias}' not found in configuration.")

    db_type = db_info.get("type")

    try:
        if db_type == "postgres":
            with psycopg2.connect(**db_info["conn_params"]) as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute(query, params)
                    if cursor.description:
                        result = cursor.fetchall()
                        return {"data": result, "row_count": len(result)}
                    conn.commit()
                    return {"data": [], "row_count": cursor.rowcount}

        if db_type == "mysql":
            with mysql.connector.connect(**db_info["conn_params"]) as conn:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute(query, params)
                    if cursor.with_rows:
                        result = cursor.fetchall()
                        return {"data": result, "row_count": len(result)}
                    conn.commit()
                    return {"data": [], "row_count": cursor.rowcount}

        if db_type == "mongo":
            client = MongoClient(db_info["uri"])
            db = client[db_info["dbname"]]
            if not collection:
                raise ValueError("MongoDB query requires a 'collection' to be specified.")
            mongo_collection = db[collection]

            if isinstance(query, str):
                try:
                    query_dict = json.loads(query)
                except Exception:
                    query_dict = query
            else:
                query_dict = query

            if not query_dict or query_dict == {}:
                return {
                    "data": [],
                    "row_count": 0,
                    "error": "Empty queries not allowed to prevent large results",
                }

            filter_query = convert_objectid_strings(
                query_dict.copy() if isinstance(query_dict, dict) else {}
            )
            documents = json.loads(
                json_util.dumps(list(mongo_collection.find(filter_query).limit(limit)))
            )
            client.close()
            return {"data": documents, "row_count": len(documents)}

        if db_type == "oracle":
            with oracledb.connect(**db_info["conn_params"]) as conn:
                with conn.cursor() as cursor:
                    if oracle_schema:
                        cursor.execute(f"ALTER SESSION SET CURRENT_SCHEMA = {oracle_schema}")
                    cursor.execute(query, params or {})
                    if cursor.description:
                        cursor.rowfactory = lambda *args: dict(
                            zip([d[0].lower() for d in cursor.description], args, strict=False)
                        )
                        result = cursor.fetchall()
                        return {"data": result, "row_count": len(result)}
                    conn.commit()
                    return {"data": [], "row_count": cursor.rowcount}

        raise ValueError(f"Unsupported database type: {db_type}")

    except Exception as e:
        raise RuntimeError(f"Query execution failed: {e}") from e
