"""Command-line interface for managing connections and running the MCP server."""

import argparse
import json

from . import config_db, core


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
    sub.add_parser("list-aliases", help="List all configured database aliases")

    p_add = sub.add_parser("add-db", help="Add a new database connection")
    p_add.add_argument("--alias", required=True, help="Unique alias for the connection")
    p_add.add_argument(
        "--type", required=True, choices=["postgres", "mysql", "oracle", "mongo"], help="Database type"
    )
    p_add.add_argument("--host", help="DB host (not for mongo)")
    p_add.add_argument("--port", type=int, help="DB port (not for mongo)")
    p_add.add_argument("--user", help="DB user (not for mongo)")
    p_add.add_argument("--password", help="DB password (not for mongo)")
    p_add.add_argument("--dbname", help="DB name (all types)")
    p_add.add_argument("--uri", help="MongoDB connection URI")

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

    if args.command == "add-db":
        try:
            result = core.add_database(
                args.alias, args.type, args.host, args.port, args.user,
                args.password, args.dbname, args.uri,
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
