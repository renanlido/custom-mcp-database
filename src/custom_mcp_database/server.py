"""FastMCP server exposing the database tools to MCP clients (stdio by default)."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import config_db, core, security

mcp = FastMCP("database_mcp")
config_db.init_db()


@mcp.tool(
    name="db_list_aliases",
    annotations={
        "title": "List database aliases",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def db_list_aliases() -> dict[str, Any]:
    """List every configured database alias and its type.

    Returns:
        {"aliases": [{"alias": str, "type": "postgres|mysql|mongo|oracle"}, ...]}
    """
    return core.list_aliases()


# Credential-management tools are NOT exposed over MCP by default. A tool's arguments
# are produced and read by the LLM, so accepting a password through a tool would leak it
# into the model context (and the provider/transcripts/logs). Provision connections
# out-of-band with the `custom-mcp-database` CLI instead. Set MCP_DB_ALLOW_ADMIN_TOOLS=1
# to re-expose these over MCP (accepting that leak).
def _db_add_database(
    alias: str,
    db_type: str,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    dbname: str | None = None,
    password_env: str | None = None,
    password_file: str | None = None,
    uri_env: str | None = None,
    uri_file: str | None = None,
) -> dict[str, str]:
    """Add (or replace) a database connection by *reference* (no plaintext secrets).

    Pass secrets by reference only: ``password_env``/``password_file`` for SQL,
    ``uri_env``/``uri_file`` for MongoDB. The actual secret is resolved from the named
    environment variable or file at connection time and is never sent through the agent.
    """
    return core.add_database(
        alias, db_type, host, port, user, dbname=dbname,
        password_env=password_env, password_file=password_file,
        uri_env=uri_env, uri_file=uri_file,
    )


def _db_remove_database(alias: str) -> dict[str, str]:
    """Remove a configured database connection by alias."""
    return core.remove_database(alias)


if security.admin_tools_enabled():
    mcp.tool(
        name="db_add_database",
        annotations={
            "title": "Add database connection (by reference)",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )(_db_add_database)
    mcp.tool(
        name="db_remove_database",
        annotations={
            "title": "Remove database connection",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )(_db_remove_database)


@mcp.tool(
    name="db_list_collections",
    annotations={
        "title": "List MongoDB collections",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def db_list_collections(database_alias: str) -> dict[str, Any]:
    """List all collections for a configured MongoDB alias.

    Returns:
        {"collections": [str, ...]}
    """
    return core.list_collections(database_alias)


@mcp.tool(
    name="db_execute_query",
    annotations={
        "title": "Execute database query",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
def db_execute_query(
    database_alias: str,
    query: str | dict[str, Any],
    params: dict[str, Any] | None = None,
    collection: str | None = None,
    oracle_schema: str | None = None,
    limit: int = core.DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Run a query against a configured database.

    SQL (postgres/mysql/oracle): pass the SQL string in ``query`` and optional bind
    values in ``params`` (use the driver's placeholder style; Oracle uses ``:name``).
    Add your own LIMIT/WHERE to keep results small.

    MongoDB: pass a JSON filter object in ``query`` and the ``collection`` name.
    24-char hex strings are coerced to ObjectId; empty filters are rejected; results
    are capped at ``limit`` documents (default 10).

    Returns:
        {"data": [...], "row_count": int}  (plus "error" on a rejected empty Mongo filter)
    """
    return core.execute_query(database_alias, query, params, collection, oracle_schema, limit)


@mcp.tool(
    name="db_security_status",
    annotations={
        "title": "Show security policy",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def db_security_status() -> dict[str, Any]:
    """Report the active security policy.

    Returns:
        {"readonly": bool, "allow_writes": bool, "allow_ddl": bool,
         "max_rows": int, "mongo_javascript_blocked": bool}
    """
    return core.security_status()


def run() -> None:
    """Start the MCP server over stdio."""
    mcp.run()
