"""Security guard tests — pure functions, no live database required."""

import pytest

from custom_mcp_database import security
from custom_mcp_database.security import SecurityError


@pytest.fixture(autouse=True)
def _reset_policy_env(monkeypatch):
    # Default strict posture for every test unless a test overrides it.
    monkeypatch.setenv("MCP_DB_READONLY", "1")
    monkeypatch.setenv("MCP_DB_ALLOW_WRITES", "0")
    monkeypatch.setenv("MCP_DB_ALLOW_DDL", "0")
    monkeypatch.delenv("MCP_DB_MAX_ROWS", raising=False)


# --- default policy ---------------------------------------------------------

def test_default_policy_is_readonly():
    pol = security.policy()
    assert pol["readonly"] is True
    assert pol["allow_writes"] is False
    assert pol["allow_ddl"] is False
    assert pol["max_rows"] == security.DEFAULT_MAX_ROWS
    assert pol["mongo_javascript_blocked"] is True


# --- SQL read-only enforcement ---------------------------------------------

@pytest.mark.parametrize("sql", [
    "SELECT * FROM users WHERE id = 1",
    "  select 1",
    "WITH x AS (SELECT 1) SELECT * FROM x",
    "EXPLAIN SELECT * FROM users",
])
def test_read_statements_allowed(sql):
    security.enforce_sql_policy(sql)  # no raise


@pytest.mark.parametrize("sql", [
    "DELETE FROM users",
    "UPDATE users SET name = 'x'",
    "INSERT INTO users (a) VALUES (1)",
])
def test_writes_blocked_by_default(sql):
    with pytest.raises(SecurityError):
        security.enforce_sql_policy(sql)


@pytest.mark.parametrize("sql", [
    "DROP TABLE users",
    "TRUNCATE TABLE users",
    "ALTER TABLE users ADD COLUMN x INT",
    "GRANT ALL ON users TO bob",
])
def test_ddl_blocked_by_default(sql):
    with pytest.raises(SecurityError):
        security.enforce_sql_policy(sql)


def test_stacked_statements_blocked():
    with pytest.raises(SecurityError):
        security.enforce_sql_policy("SELECT 1; DROP TABLE users")


def test_comment_hidden_stacked_statement_blocked():
    with pytest.raises(SecurityError):
        security.enforce_sql_policy("SELECT 1; /* sneaky */ DROP TABLE users")


def test_dangerous_statement_blocked():
    with pytest.raises(SecurityError):
        security.enforce_sql_policy("CALL do_something()")


def test_writes_allowed_with_optin(monkeypatch):
    monkeypatch.setenv("MCP_DB_READONLY", "0")
    monkeypatch.setenv("MCP_DB_ALLOW_WRITES", "1")
    security.enforce_sql_policy("UPDATE users SET a = 1")  # no raise
    # DDL still blocked without its own flag
    with pytest.raises(SecurityError):
        security.enforce_sql_policy("DROP TABLE users")


def test_ddl_allowed_with_optin(monkeypatch):
    monkeypatch.setenv("MCP_DB_READONLY", "0")
    monkeypatch.setenv("MCP_DB_ALLOW_DDL", "1")
    security.enforce_sql_policy("DROP TABLE users")  # no raise


def test_optin_ignored_while_readonly(monkeypatch):
    # readonly wins even if writes flag is set
    monkeypatch.setenv("MCP_DB_READONLY", "1")
    monkeypatch.setenv("MCP_DB_ALLOW_WRITES", "1")
    with pytest.raises(SecurityError):
        security.enforce_sql_policy("DELETE FROM users")


# --- MongoDB filter enforcement --------------------------------------------

@pytest.mark.parametrize("flt", [
    {"$where": "this.a == 1"},
    {"a": {"b": [{"$function": {"body": "x", "args": [], "lang": "js"}}]}},
    {"$expr": {"$gt": ["$a", 1]}},
    {"$accumulator": {}},
    {"$out": "evil"},
])
def test_mongo_js_operators_blocked(flt):
    with pytest.raises(SecurityError):
        security.enforce_mongo_filter(flt)


def test_mongo_plain_filter_allowed():
    security.enforce_mongo_filter({"name": "john", "age": {"$gte": 18}})  # no raise


# --- identifier validation --------------------------------------------------

@pytest.mark.parametrize("bad", [
    "x; DROP TABLE y",
    "a b",
    "schema'--",
    "",
    "x" * 200,
])
def test_invalid_identifier_rejected(bad):
    with pytest.raises(SecurityError):
        security.validate_identifier(bad, field="oracle_schema")


def test_valid_identifier_accepted():
    assert security.validate_identifier("HR_SCHEMA") == "HR_SCHEMA"
    assert security.validate_identifier("C##ADMIN") == "C##ADMIN"


# --- error redaction --------------------------------------------------------

def test_redact_removes_secrets():
    msg = "could not connect: password=Sup3rSecret host=db"
    out = security.redact(msg, ["Sup3rSecret"])
    assert "Sup3rSecret" not in out
    assert "***REDACTED***" in out


def test_collect_secrets_shapes():
    mongo = {"type": "mongo", "uri": "mongodb://u:p@h/db", "dbname": "db"}
    sql = {"type": "postgres", "conn_params": {"password": "pw", "host": "h"}}
    assert "mongodb://u:p@h/db" in security.collect_secrets(mongo)
    assert "pw" in security.collect_secrets(sql)
    assert security.collect_secrets(None) == []
