"""Command-line interface for managing connections and running the MCP server."""

import argparse
import getpass
import json

from . import config_db, core

_DEFAULT_PORTS = {"postgres": 5432, "mysql": 3306, "oracle": 1521}


def _ask(label: str, default: str | None = None, required: bool = True) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        val = input(f"{label}{suffix}: ").strip()
        if not val and default is not None:
            return default
        if val or not required:
            return val
        print("  (required)")


def _ask_choice(label: str, choices: list[str]) -> str:
    print(label)
    for i, c in enumerate(choices, 1):
        print(f"  {i}) {c}")
    while True:
        raw = input("> ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1]
        print("  (enter a number)")


def _ask_secret(label: str) -> tuple[str, str]:
    """Return (kind, value): kind in {'now','env','file'}. Secret never echoed."""
    choice = _ask_choice(
        f"How should the {label} be provided?",
        ["Enter it now (hidden input)", "Read from an environment variable", "Read from a file"],
    )
    if choice.startswith("Enter"):
        return "now", getpass.getpass(f"  {label} (hidden): ")
    if "environment" in choice:
        return "env", _ask(f"  Name of the env var holding the {label}")
    return "file", _ask(f"  Path of the file holding the {label}")


def _run_setup() -> None:
    """Interactive, secret-safe wizard to add a connection."""
    print("Add a database connection. Press Ctrl-C to abort.\n")
    try:
        alias = _ask("Alias (a short name you'll reference, e.g. 'prod_ro')")
        db_type = _ask_choice("Database type:", ["postgres", "mysql", "oracle", "mongo"])
        kwargs: dict = {}
        if db_type == "mongo":
            kwargs["dbname"] = _ask("Database name")
            kind, val = _ask_secret("MongoDB connection URI")
            kwargs[{"now": "uri", "env": "uri_env", "file": "uri_file"}[kind]] = val
        else:
            kwargs["host"] = _ask("Host", default="localhost")
            kwargs["port"] = int(_ask("Port", default=str(_DEFAULT_PORTS[db_type])))
            kwargs["user"] = _ask("User")
            kwargs["dbname"] = _ask("Database name")
            kind, val = _ask_secret("password")
            kwargs[{"now": "password", "env": "password_env", "file": "password_file"}[kind]] = val
    except (KeyboardInterrupt, EOFError):
        print("\nAborted. Nothing was saved.")
        return

    shown = {k: v for k, v in kwargs.items() if k not in ("password", "uri")}
    if "password" in kwargs:
        shown["password"] = "<hidden>"
    if "uri" in kwargs:
        shown["uri"] = "<hidden>"
    print(f"\nSummary:\n  alias: {alias}\n  type:  {db_type}")
    for k, v in shown.items():
        print(f"  {k}: {v}")

    if _ask("Save this connection? (y/n)", default="y").lower() not in ("y", "yes"):
        print("Not saved.")
        return
    try:
        print(core.add_database(alias, db_type, **kwargs)["status"])
    except ValueError as e:
        print(f"Error: {e}")
        return

    if _ask("Test the connection now? (y/n)", default="y").lower() in ("y", "yes"):
        try:
            if db_type == "mongo":
                core.list_collections(alias)
            else:
                core.execute_query(alias, "SELECT 1 FROM DUAL" if db_type == "oracle" else "SELECT 1")
            print("Connection OK.")
        except Exception as e:  # noqa: BLE001 - surface any driver/policy error to the user
            print(f"Connection test failed: {e}")
            print("The connection was saved; fix the details with 'add-db' or re-run 'setup'.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="custom-mcp-database",
        description="MCP Database Server & connection-config CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
  # Run the MCP server (stdio) — this is also the default with no command
  %(prog)s run

  # List configured aliases
  %(prog)s list-aliases

  # Add a PostgreSQL database
  %(prog)s add-db --alias mydb --type postgres --host localhost --port 5432 \\
      --user postgres --password secret --dbname myapp

  # Add a MongoDB database
  %(prog)s add-db --alias mymongo --type mongo --uri mongodb://localhost:27017 --dbname myapp

  # Execute a SQL query
  %(prog)s execute-query --database_alias mydb --query "SELECT * FROM users LIMIT 5"

  # Execute a MongoDB query (24-char hex strings become ObjectId)
  %(prog)s execute-query --database_alias mymongo --collection optins \\
      --query '{"campaign": "6850982849bcd9c1f6633874"}'

  # Remove a connection
  %(prog)s remove-db --alias mydb

NOTES:
  - Connection config is stored at $MCP_DB_CONFIG, else
    $XDG_CONFIG_HOME/custom-mcp-database/mcp_config.sqlite3
    (default ~/.config/custom-mcp-database/mcp_config.sqlite3).
  - Credentials are stored as PLAINTEXT JSON in that SQLite file — keep it secret.
  - MongoDB results are capped at 10 documents by default (use --limit to change).
  - Quote JSON arguments in single quotes to avoid shell interpretation.
        """,
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    sub.add_parser("run", help="Run the MCP server (stdio)")
    sub.add_parser("setup", help="Interactive, guided wizard to add a connection (secret-safe)")
    sub.add_parser("list-aliases", help="List all configured database aliases")

    p_add = sub.add_parser("add-db", help="Add a new database connection")
    p_add.add_argument("--alias", required=True, help="Unique alias for the connection")
    p_add.add_argument(
        "--type", required=True, choices=["postgres", "mysql", "oracle", "mongo"], help="Database type"
    )
    p_add.add_argument("--host", help="DB host (not for mongo)")
    p_add.add_argument("--port", type=int, help="DB port (not for mongo)")
    p_add.add_argument("--user", help="DB user (not for mongo)")
    p_add.add_argument(
        "--password",
        help="DB password (SQL). Omit to be prompted securely (recommended). "
        "Prefer --password-env/--password-file to avoid storing plaintext.",
    )
    p_add.add_argument("--password-env", dest="password_env", help="Env var name holding the password")
    p_add.add_argument("--password-file", dest="password_file", help="File path holding the password")
    p_add.add_argument("--dbname", help="DB name (all types)")
    p_add.add_argument("--uri", help="MongoDB connection URI (omit to be prompted securely)")
    p_add.add_argument("--uri-env", dest="uri_env", help="Env var name holding the MongoDB URI")
    p_add.add_argument("--uri-file", dest="uri_file", help="File path holding the MongoDB URI")

    p_rm = sub.add_parser("remove-db", help="Remove a database connection")
    p_rm.add_argument("--alias", required=True, help="Alias of the connection to remove")

    p_exec = sub.add_parser(
        "execute-query",
        help="Execute a query on a configured database",
        description="Execute SQL or MongoDB queries. MongoDB results capped at 10 rows by default.",
    )
    p_exec.add_argument("--database_alias", required=True, help="Alias of the database")
    p_exec.add_argument("--query", required=True, help="SQL string or MongoDB JSON filter")
    p_exec.add_argument("--params", help='JSON string of bind params, e.g. \'{"user_id": 123}\'')
    p_exec.add_argument("--collection", help="Collection name (required for MongoDB)")
    p_exec.add_argument("--oracle_schema", help="Oracle schema to switch to (optional)")
    p_exec.add_argument(
        "--limit", type=int, default=core.DEFAULT_LIMIT, help="Max MongoDB documents (default 10)"
    )

    p_lc = sub.add_parser("list-collections", help="List collections for a MongoDB database")
    p_lc.add_argument("--database_alias", required=True, help="Alias of the MongoDB database")

    sub.add_parser("security-status", help="Show the active security policy")

    return parser


def main() -> None:
    config_db.init_db()
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "setup":
        _run_setup()

    elif args.command == "add-db":
        password = args.password
        uri = args.uri
        # Prompt securely when no secret (literal or reference) was supplied.
        if args.type in ("postgres", "mysql", "oracle"):
            if not (password or args.password_env or args.password_file):
                password = getpass.getpass(f"Password for '{args.alias}': ")
        elif args.type == "mongo":
            if not (uri or args.uri_env or args.uri_file):
                uri = getpass.getpass(f"MongoDB URI for '{args.alias}': ")
        try:
            result = core.add_database(
                args.alias, args.type, args.host, args.port, args.user,
                password=password, dbname=args.dbname, uri=uri,
                password_env=args.password_env, password_file=args.password_file,
                uri_env=args.uri_env, uri_file=args.uri_file,
            )
            print(result["status"])
        except ValueError as e:
            print(f"Error: {e}")

    elif args.command == "remove-db":
        try:
            print(core.remove_database(args.alias)["status"])
        except ValueError as e:
            print(f"Error: {e}")

    elif args.command == "list-aliases":
        aliases = core.list_aliases()["aliases"]
        if aliases:
            print("Configured database aliases:")
            for info in aliases:
                print(f"  - Alias: {info['alias']}, Type: {info['type']}")
        else:
            print("No database aliases configured.")

    elif args.command == "execute-query":
        try:
            params = json.loads(args.params) if args.params else None
            result = core.execute_query(
                args.database_alias, args.query, params,
                args.collection, args.oracle_schema, args.limit,
            )
            print(json.dumps(result, indent=2, default=str))
        except (ValueError, RuntimeError) as e:
            print(f"Error: {e}")

    elif args.command == "list-collections":
        try:
            print(json.dumps(core.list_collections(args.database_alias), indent=2))
        except (ValueError, RuntimeError) as e:
            print(f"Error: {e}")

    elif args.command == "security-status":
        print(json.dumps(core.security_status(), indent=2))

    else:  # "run" or no command
        from .server import run as run_server
        run_server()


if __name__ == "__main__":
    main()
