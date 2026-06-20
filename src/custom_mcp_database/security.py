"""Security policy engine: query guards, identifier validation, error redaction.

Posture is **deny by default**. Out of the box the server is read-only: only
SELECT-class SQL and read-only MongoDB filters are allowed. Writes and DDL must be
explicitly enabled via environment variables, so a prompt-injected agent cannot
mutate production data without an operator's deliberate opt-in.

Environment variables (read fresh on every call so they can be flipped per process):
    MCP_DB_READONLY     default "1". Set "0" to lift the read-only posture
                        (still subject to the flags below).
    MCP_DB_ALLOW_WRITES default "0". "1" permits INSERT/UPDATE/DELETE/MERGE/UPSERT.
    MCP_DB_ALLOW_DDL    default "0". "1" permits CREATE/DROP/ALTER/TRUNCATE/GRANT/
                        REVOKE and stored-procedure execution.
    MCP_DB_MAX_ROWS     default "1000". Hard cap on rows/documents returned.
"""

from __future__ import annotations

import os
from typing import Any

import sqlparse

DEFAULT_MAX_ROWS = 1000

# SQL statement categories
_READ_TYPES = {"SELECT"}
_READ_LEADING = {"SELECT", "WITH", "EXPLAIN", "SHOW", "DESCRIBE", "DESC", "PRAGMA", "VALUES"}
_WRITE_TYPES = {"INSERT", "UPDATE", "DELETE", "MERGE", "REPLACE", "UPSERT"}
_DDL_TYPES = {"CREATE", "DROP", "ALTER", "TRUNCATE", "GRANT", "REVOKE", "RENAME", "COMMENT"}
_DANGEROUS_LEADING = {"CALL", "EXEC", "EXECUTE", "DO", "COPY", "SET", "LOCK", "USE", "ATTACH", "LOAD"}

# MongoDB operators that run server-side JavaScript or write — never needed for find().
_FORBIDDEN_MONGO_OPS = {
    "$where",
    "$function",
    "$accumulator",
    "$out",
    "$merge",
    "$expr",  # can embed $function; blocked defensively (find() rarely needs it)
    "mapreduce",
    "$eval",
}

_IDENTIFIER_MAX = 128


class SecurityError(Exception):
    """Raised when a query violates the active security policy."""


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def policy() -> dict[str, Any]:
    """Snapshot of the active policy (also exposed as a status tool)."""
    readonly = _flag("MCP_DB_READONLY", "1")
    allow_writes = _flag("MCP_DB_ALLOW_WRITES", "0") and not readonly
    allow_ddl = _flag("MCP_DB_ALLOW_DDL", "0") and not readonly
    try:
        max_rows = int(os.environ.get("MCP_DB_MAX_ROWS", str(DEFAULT_MAX_ROWS)))
    except ValueError:
        max_rows = DEFAULT_MAX_ROWS
    return {
        "readonly": readonly,
        "allow_writes": allow_writes,
        "allow_ddl": allow_ddl,
        "max_rows": max(1, max_rows),
        "mongo_javascript_blocked": True,
    }


def max_rows() -> int:
    return policy()["max_rows"]


def _classify(statement: sqlparse.sql.Statement) -> str:
    """Return one of: read | write | ddl | dangerous."""
    stype = (statement.get_type() or "UNKNOWN").upper()
    if stype in _WRITE_TYPES:
        return "write"
    if stype in _DDL_TYPES:
        return "ddl"
    if stype in _READ_TYPES:
        return "read"

    # get_type() is UNKNOWN for WITH/EXPLAIN/SHOW/CALL/etc — fall back to first keyword.
    leading = None
    for token in statement.flatten():
        if token.is_keyword or token.ttype in (
            sqlparse.tokens.Keyword,
            sqlparse.tokens.Keyword.DML,
            sqlparse.tokens.Keyword.DDL,
        ):
            leading = token.value.upper()
            break
    if leading in _READ_LEADING:
        return "read"
    if leading in _WRITE_TYPES:
        return "write"
    if leading in _DDL_TYPES:
        return "ddl"
    return "dangerous"


def enforce_sql_policy(sql: str) -> None:
    """Validate a SQL string against the active policy. Raises SecurityError if denied.

    Strips comments, forbids multiple statements (stacked-query injection), and
    classifies the single remaining statement, requiring the matching opt-in flag.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise SecurityError("Empty SQL statement.")

    stripped = sqlparse.format(sql, strip_comments=True).strip()
    statements = [s for s in sqlparse.split(stripped) if s.strip()]

    if len(statements) == 0:
        raise SecurityError("No executable SQL after stripping comments.")
    if len(statements) > 1:
        raise SecurityError(
            "Multiple SQL statements are not allowed (stacked-query injection risk). "
            "Send exactly one statement per call."
        )

    parsed = sqlparse.parse(statements[0])[0]
    category = _classify(parsed)
    pol = policy()

    if category == "read":
        return
    if category == "write":
        if pol["allow_writes"]:
            return
        raise SecurityError(
            "Write statements are blocked by the read-only policy. "
            "To allow writes, set MCP_DB_READONLY=0 and MCP_DB_ALLOW_WRITES=1."
        )
    if category == "ddl":
        if pol["allow_ddl"]:
            return
        raise SecurityError(
            "DDL statements (CREATE/DROP/ALTER/TRUNCATE/GRANT/...) are blocked. "
            "To allow them, set MCP_DB_READONLY=0 and MCP_DB_ALLOW_DDL=1."
        )
    # dangerous / unknown
    raise SecurityError(
        "This statement type is blocked by policy (procedure execution / session or "
        "engine-level command). If you trust it, set MCP_DB_READONLY=0 and MCP_DB_ALLOW_DDL=1."
    )


def enforce_mongo_filter(obj: Any, _depth: int = 0) -> None:
    """Recursively reject MongoDB filters that use server-side JS or write stages."""
    if _depth > 50:
        raise SecurityError("MongoDB filter nested too deeply.")
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str) and key.lower() in _FORBIDDEN_MONGO_OPS:
                raise SecurityError(
                    f"MongoDB operator '{key}' is blocked (server-side JavaScript or "
                    "write operation). Rewrite the query without it."
                )
            enforce_mongo_filter(value, _depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            enforce_mongo_filter(item, _depth + 1)


def validate_identifier(name: str, *, field: str = "identifier") -> str:
    """Validate a bare SQL identifier (e.g. Oracle schema). Raises SecurityError if unsafe.

    Allows letters, digits, underscore, ``$`` and ``#`` (valid in Oracle identifiers),
    length 1..128. This prevents injection through values interpolated into statements
    that cannot use bind parameters (identifiers can't be bound).
    """
    if not isinstance(name, str) or not name:
        raise SecurityError(f"Empty {field}.")
    if len(name) > _IDENTIFIER_MAX:
        raise SecurityError(f"{field} too long.")
    for ch in name:
        if not (ch.isalnum() or ch in "_$#"):
            raise SecurityError(
                f"Invalid character in {field}: only letters, digits, '_', '$' and '#' "
                "are allowed."
            )
    return name


def collect_secrets(db_info: dict[str, Any] | None) -> list[str]:
    """Pull secret-bearing strings out of a stored connection for error redaction."""
    if not db_info:
        return []
    secrets: list[str] = []
    uri = db_info.get("uri")
    if isinstance(uri, str) and uri:
        secrets.append(uri)
    conn = db_info.get("conn_params") or {}
    for key in ("password", "dsn"):
        val = conn.get(key)
        if isinstance(val, str) and val:
            secrets.append(val)
    return secrets


def redact(text: str, secrets: list[str]) -> str:
    """Remove known secret substrings from a (error) message before it leaves the server."""
    if not isinstance(text, str):
        text = str(text)
    for secret in secrets:
        if secret and secret in text:
            text = text.replace(secret, "***REDACTED***")
    return text
