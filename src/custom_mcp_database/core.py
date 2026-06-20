"""Database-agnostic logic shared by the MCP server and the CLI.

All functions here are plain callables (no MCP/CLI coupling) so they can be reused
and unit-tested. Query execution behavior matches the original implementation.
"""

import json
import os
from pathlib import Path
from typing import Any

import mysql.connector
import oracledb
import psycopg2
import psycopg2.extras
from bson import ObjectId, json_util
from pymongo import MongoClient

from . import config_db, security
from .security import SecurityError

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


def _secret_ref(
    label: str,
    literal: str | None,
    env: str | None,
    file: str | None,
) -> dict[str, str]:
    """Return a single stored secret reference: literal value, env-var name, or file path.

    Storing a reference (``*_env`` / ``*_file``) means the plaintext secret never lives
    in the config DB — it is resolved at connection time.
    """
    provided = [x for x in (literal, env, file) if x]
    if len(provided) > 1:
        raise ValueError(f"Provide only one of '{label}', '{label}_env', or '{label}_file'.")
    if literal:
        return {label: literal}
    if env:
        return {f"{label}_env": env}
    if file:
        return {f"{label}_file": file}
    return {}


def build_and_validate_params(
    db_type: str,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    dbname: str | None = None,
    uri: str | None = None,
    password_env: str | None = None,
    password_file: str | None = None,
    uri_env: str | None = None,
    uri_file: str | None = None,
) -> dict[str, Any]:
    """Validate inputs and build the driver-specific params dict for storage.

    Secrets may be given literally or by reference (``*_env`` / ``*_file``); references
    are stored instead of the value and resolved at connection time.
    """
    if db_type == "mongo":
        uri_ref = _secret_ref("uri", uri, uri_env, uri_file)
        if not uri_ref or not dbname:
            raise ValueError(
                "For MongoDB, 'dbname' and one of 'uri'/'uri_env'/'uri_file' are required."
            )
        return {"dbname": dbname, **uri_ref}

    if db_type in ("postgres", "mysql", "oracle"):
        pw_ref = _secret_ref("password", password, password_env, password_file)
        if not all([host, port, user, dbname]) or not pw_ref:
            raise ValueError(
                f"For {db_type}, 'host', 'port', 'user', 'dbname', and one of "
                "'password'/'password_env'/'password_file' are required."
            )
        params: dict[str, Any] = {"host": host, "port": port, "user": user, **pw_ref}
        if db_type == "mysql":
            params["database"] = dbname
        else:
            params["dbname"] = dbname
        if db_type == "oracle":
            params["dsn"] = f"{params.pop('host')}:{params.pop('port')}/{params.pop('dbname')}"
        return params

    raise ValueError(f"Unsupported database type: {db_type}")


def _resolve_ref(d: dict[str, Any], label: str) -> None:
    """In-place: turn ``label_env``/``label_file`` in ``d`` into a concrete ``label`` value."""
    if d.get(label):
        return
    env = d.pop(f"{label}_env", None)
    file = d.pop(f"{label}_file", None)
    if env is not None:
        val = os.environ.get(env)
        if val is None or val == "":
            raise RuntimeError(f"Environment variable '{env}' (for {label}) is not set.")
        d[label] = val
    elif file is not None:
        try:
            raw = Path(file).expanduser().read_text(encoding="utf-8")
        except OSError as e:
            raise RuntimeError(f"Could not read {label} file '{file}': {e}") from None
        # Trim only a single trailing newline (from `echo`/editors); preserve every
        # other character, including spaces and shell-special chars inside the secret.
        if raw.endswith("\r\n"):
            raw = raw[:-2]
        elif raw.endswith("\n"):
            raw = raw[:-1]
        d[label] = raw


def resolve_secrets(db_info: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a stored connection with secret references resolved to values.

    Resolution happens here, at connection time, so the plaintext secret is never
    persisted and never returned by any listing/tool.
    """
    resolved = dict(db_info)
    if resolved.get("type") == "mongo":
        _resolve_ref(resolved, "uri")
    else:
        conn = dict(resolved.get("conn_params") or {})
        _resolve_ref(conn, "password")
        resolved["conn_params"] = conn
    return resolved


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
    password_env: str | None = None,
    password_file: str | None = None,
    uri_env: str | None = None,
    uri_file: str | None = None,
) -> dict[str, str]:
    """Persist a new (or replace an existing) database connection."""
    params = build_and_validate_params(
        db_type, host, port, user, password, dbname, uri,
        password_env=password_env, password_file=password_file,
        uri_env=uri_env, uri_file=uri_file,
    )
    config_db.add_connection(alias, db_type, params)
    return {"status": f"Database '{alias}' added successfully."}


def remove_database(alias: str) -> dict[str, str]:
    """Remove a configured connection by alias."""
    if config_db.remove_connection(alias):
        return {"status": f"Database '{alias}' removed successfully."}
    raise ValueError(f"Database alias '{alias}' not found.")


def list_collections(database_alias: str) -> dict[str, Any]:
    """List all collections for a configured MongoDB alias."""
    stored = config_db.get_connection(database_alias)
    if not stored:
        raise ValueError(f"Database alias '{database_alias}' not found in configuration.")
    if stored.get("type") != "mongo":
        raise ValueError(f"Alias '{database_alias}' is not a MongoDB database.")
    db_info = resolve_secrets(stored)
    try:
        client = MongoClient(db_info["uri"])
        db = client[db_info["dbname"]]
        collections = db.list_collection_names()
        client.close()
        return {"collections": collections}
    except Exception as e:
        secrets = security.collect_secrets(db_info)
        raise RuntimeError(
            f"Failed to list collections for '{database_alias}': "
            f"{security.redact(str(e), secrets)}"
        ) from None


def security_status() -> dict[str, Any]:
    """Return the active security policy (read-only/writes/DDL/row cap)."""
    return security.policy()


def execute_query(
    database_alias: str,
    query: str | dict[str, Any],
    params: dict[str, Any] | None = None,
    collection: str | None = None,
    oracle_schema: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Execute a query against a configured database and return rows + row_count.

    Security: enforced BEFORE any connection is opened. SQL is parsed and must be a
    single statement permitted by the active policy (read-only by default; writes/DDL
    require explicit opt-in env vars). ``oracle_schema`` is validated as an identifier.
    MongoDB filters that use server-side JavaScript are rejected. Results are capped at
    ``min(limit, MCP_DB_MAX_ROWS)`` and a ``truncated`` flag is returned.
    """
    stored = config_db.get_connection(database_alias)
    if not stored:
        raise ValueError(f"Database alias '{database_alias}' not found in configuration.")

    db_type = stored.get("type")
    db_info = resolve_secrets(stored)
    cap = min(int(limit), security.max_rows())
    if cap < 1:
        cap = 1
    secrets = security.collect_secrets(db_info)

    # --- Policy enforcement (outside the try: SecurityError must surface verbatim) ---
    if db_type in ("postgres", "mysql", "oracle"):
        if not isinstance(query, str):
            raise SecurityError("SQL query must be a string.")
        security.enforce_sql_policy(query)
        if db_type == "oracle" and oracle_schema:
            security.validate_identifier(oracle_schema, field="oracle_schema")
    elif db_type == "mongo":
        if isinstance(query, str):
            try:
                query_dict = json.loads(query)
            except Exception as e:
                raise ValueError(f"Invalid MongoDB filter JSON: {e}") from e
        else:
            query_dict = query
        if not query_dict or query_dict == {}:
            return {
                "data": [],
                "row_count": 0,
                "error": "Empty queries not allowed to prevent large results",
            }
        security.enforce_mongo_filter(query_dict)

    def _capped_fetch(cursor) -> tuple[list, bool]:
        rows = cursor.fetchmany(cap)
        truncated = cursor.fetchone() is not None
        return rows, truncated

    try:
        if db_type == "postgres":
            with psycopg2.connect(**db_info["conn_params"]) as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute(query, params)
                    if cursor.description:
                        result, truncated = _capped_fetch(cursor)
                        return {"data": result, "row_count": len(result), "truncated": truncated}
                    conn.commit()
                    return {"data": [], "row_count": cursor.rowcount}

        if db_type == "mysql":
            with mysql.connector.connect(**db_info["conn_params"]) as conn:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute(query, params)
                    if cursor.with_rows:
                        result, truncated = _capped_fetch(cursor)
                        return {"data": result, "row_count": len(result), "truncated": truncated}
                    conn.commit()
                    return {"data": [], "row_count": cursor.rowcount}

        if db_type == "mongo":
            client = MongoClient(db_info["uri"])
            db = client[db_info["dbname"]]
            if not collection:
                raise ValueError("MongoDB query requires a 'collection' to be specified.")
            mongo_collection = db[collection]
            filter_query = convert_objectid_strings(
                query_dict.copy() if isinstance(query_dict, dict) else {}
            )
            cursor = mongo_collection.find(filter_query).limit(cap + 1)
            docs = json.loads(json_util.dumps(list(cursor)))
            client.close()
            truncated = len(docs) > cap
            docs = docs[:cap]
            return {"data": docs, "row_count": len(docs), "truncated": truncated}

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
                        result, truncated = _capped_fetch(cursor)
                        return {"data": result, "row_count": len(result), "truncated": truncated}
                    conn.commit()
                    return {"data": [], "row_count": cursor.rowcount}

        raise ValueError(f"Unsupported database type: {db_type}")

    except SecurityError:
        raise
    except Exception as e:
        raise RuntimeError(
            f"Query execution failed: {security.redact(str(e), secrets)}"
        ) from None
