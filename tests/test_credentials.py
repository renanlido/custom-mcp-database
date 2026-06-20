"""Credential-handling tests: secret-by-reference, resolution, admin-tool gating."""

import pytest

from custom_mcp_database import core, security

# --- secret references in build_and_validate_params -------------------------

def test_sql_password_literal():
    p = core.build_and_validate_params(
        "postgres", host="h", port=5432, user="u", password="pw", dbname="db"
    )
    assert p["password"] == "pw"
    assert "password_env" not in p


def test_sql_password_env_reference_not_plaintext():
    p = core.build_and_validate_params(
        "postgres", host="h", port=5432, user="u", dbname="db", password_env="PGPASS"
    )
    assert p["password_env"] == "PGPASS"
    assert "password" not in p  # plaintext never stored


def test_mongo_uri_file_reference():
    p = core.build_and_validate_params("mongo", dbname="db", uri_file="/run/secrets/uri")
    assert p["uri_file"] == "/run/secrets/uri"
    assert "uri" not in p


def test_only_one_secret_source_allowed():
    with pytest.raises(ValueError):
        core.build_and_validate_params(
            "postgres", host="h", port=5432, user="u", dbname="db",
            password="pw", password_env="PGPASS",
        )


def test_sql_requires_a_password_source():
    with pytest.raises(ValueError):
        core.build_and_validate_params("postgres", host="h", port=5432, user="u", dbname="db")


# --- resolution at connection time -----------------------------------------

def test_resolve_password_from_env(monkeypatch):
    monkeypatch.setenv("PGPASS", "s3cret")
    stored = {"type": "postgres", "conn_params": {"host": "h", "user": "u", "password_env": "PGPASS"}}
    resolved = core.resolve_secrets(stored)
    assert resolved["conn_params"]["password"] == "s3cret"
    assert "password_env" not in resolved["conn_params"]
    # original untouched
    assert "password" not in stored["conn_params"]


def test_resolve_password_from_file(tmp_path):
    f = tmp_path / "pw"
    f.write_text("filepass\n")
    stored = {"type": "mysql", "conn_params": {"user": "u", "password_file": str(f)}}
    resolved = core.resolve_secrets(stored)
    assert resolved["conn_params"]["password"] == "filepass"


def test_resolve_missing_env_raises(monkeypatch):
    monkeypatch.delenv("NOPE", raising=False)
    stored = {"type": "postgres", "conn_params": {"user": "u", "password_env": "NOPE"}}
    with pytest.raises(RuntimeError):
        core.resolve_secrets(stored)


def test_resolve_mongo_uri_from_env(monkeypatch):
    monkeypatch.setenv("MURI", "mongodb://u:p@h/db")
    stored = {"type": "mongo", "dbname": "db", "uri_env": "MURI"}
    resolved = core.resolve_secrets(stored)
    assert resolved["uri"] == "mongodb://u:p@h/db"


# --- admin tool gating ------------------------------------------------------

def test_admin_tools_off_by_default(monkeypatch):
    monkeypatch.delenv("MCP_DB_ALLOW_ADMIN_TOOLS", raising=False)
    assert security.admin_tools_enabled() is False


def test_admin_tools_optin(monkeypatch):
    monkeypatch.setenv("MCP_DB_ALLOW_ADMIN_TOOLS", "1")
    assert security.admin_tools_enabled() is True
