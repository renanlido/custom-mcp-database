import json
import psycopg2
import psycopg2.extras
import mysql.connector
import oracledb
import argparse
from pymongo import MongoClient
from typing import Dict, Any, Optional, Union
from mcp.server.fastmcp import FastMCP
import config_db
from bson import json_util, ObjectId

# Initialize the MCP server and the configuration database
mcp = FastMCP()
config_db.init_db()

# --- Helper Functions ---

def _convert_objectid_strings(obj):
    """Convert ObjectId strings to ObjectId objects recursively"""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, dict) and "$oid" in value:
                try:
                    obj[key] = ObjectId(value["$oid"])
                except:
                    pass
            elif isinstance(value, str) and len(value) == 24:
                try:
                    obj[key] = ObjectId(value)
                except:
                    pass
            elif isinstance(value, dict):
                obj[key] = _convert_objectid_strings(value)
            elif isinstance(value, list):
                obj[key] = [_convert_objectid_strings(item) if isinstance(item, dict) else item for item in value]
    return obj

def _build_and_validate_params(
    db_type: str,
    host: Optional[str] = None,
    port: Optional[int] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    dbname: Optional[str] = None,
    uri: Optional[str] = None
) -> Dict[str, Any]:
    """Validates parameters and builds the params dictionary for storage."""
    params = {}
    if db_type == "mongo":
        if not uri or not dbname:
            raise ValueError("For MongoDB, 'uri' and 'dbname' are required.")
        params = {"uri": uri, "dbname": dbname}
    elif db_type in ["postgres", "mysql", "oracle"]:
        if not all([host, port, user, password, dbname]):
            raise ValueError(f"For {db_type}, 'host', 'port', 'user', 'password', and 'dbname' are required.")
        
        params = {"host": host, "port": port, "user": user, "password": password}
        if db_type == "mysql":
            params["database"] = dbname
        else:
            params["dbname"] = dbname
        
        if db_type == "oracle":
            # Pop the standard host/port/dbname as they are now in the DSN
            params["dsn"] = f"{params.pop('host')}:{params.pop('port')}/{params.pop('dbname')}"
    else:
        raise ValueError(f"Unsupported database type: {db_type}")

    return params

# --- MCP Tool Definitions ---

@mcp.tool()
def list_aliases() -> Dict[str, Any]:
    """
    Lists all configured database aliases and their types.
    :return: A dictionary containing a list of database aliases and their types.
    """
    db_configs = config_db.get_all_connections()
    aliases_list = []
    for alias, config in db_configs.items():
        aliases_list.append({"alias": alias, "type": config.get("type")})
    return {"aliases": aliases_list}

@mcp.tool()
def add_database(
    alias: str,
    db_type: str,
    host: Optional[str] = None,
    port: Optional[int] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    dbname: Optional[str] = None,
    uri: Optional[str] = None
) -> Dict[str, str]:
    """
    Adds a new database connection to the configuration.
    For SQL types, requires: host, port, user, password, dbname.
    For MongoDB, requires: uri, dbname.
    """
    params = _build_and_validate_params(db_type, host, port, user, password, dbname, uri)
    config_db.add_connection(alias, db_type, params)
    return {"status": f"Database '{alias}' added successfully."}

@mcp.tool()
def remove_database(alias: str) -> Dict[str, str]:
    """
    Removes a database connection from the configuration.
    """
    if config_db.remove_connection(alias):
        return {"status": f"Database '{alias}' removed successfully."}
    else:
        raise ValueError(f"Database alias '{alias}' not found.")

@mcp.tool()
def list_collections(
    database_alias: str
) -> Dict[str, Any]:
    """
    Lists all collections for a given MongoDB database alias.
    """
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
        raise RuntimeError(f"Failed to list collections for '{database_alias}': {str(e)}") from e

@mcp.tool()
def execute_query(
    database_alias: str,
    query: Union[str, Dict[str, Any]],
    params: Optional[Dict[str, Any]] = None,
    collection: Optional[str] = None,
    oracle_schema: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes a query on a configured database and returns the result.
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
                    else:
                        conn.commit()
                        return {"data": [], "row_count": cursor.rowcount}

        elif db_type == "mysql":
            with mysql.connector.connect(**db_info["conn_params"]) as conn:
                with conn.cursor(dictionary=True) as cursor:
                    cursor.execute(query, params)
                    if cursor.with_rows:
                        result = cursor.fetchall()
                        return {"data": result, "row_count": len(result)}
                    else:
                        conn.commit()
                        return {"data": [], "row_count": cursor.rowcount}

        elif db_type == "mongo":
            client = MongoClient(db_info["uri"])
            db = client[db_info["dbname"]]
            if not collection:
                raise ValueError("MongoDB query requires a 'collection' to be specified.")
            
            mongo_collection = db[collection]
            
            # Ensure we have a dict for the query
            if isinstance(query, str):
                try:
                    query_dict = json.loads(query)
                except:
                    query_dict = query
            else:
                query_dict = query
            
            # Prevent empty queries to avoid large results
            if not query_dict or query_dict == {}:
                return {"data": [], "row_count": 0, "error": "Empty queries not allowed to prevent large results"}
            
            filter_query = _convert_objectid_strings(query_dict.copy() if isinstance(query_dict, dict) else {})
            documents = json.loads(json_util.dumps(list(mongo_collection.find(filter_query).limit(10))))
            client.close()
            return {"data": documents, "row_count": len(documents)}

        elif db_type == "oracle":
            with oracledb.connect(**db_info["conn_params"]) as conn:
                with conn.cursor() as cursor:
                    if oracle_schema:
                        cursor.execute(f"ALTER SESSION SET CURRENT_SCHEMA = {oracle_schema}")
                    cursor.execute(query, params or {})
                    if cursor.description:
                        cursor.rowfactory = lambda *args: dict(zip([d[0].lower() for d in cursor.description], args))
                        result = cursor.fetchall()
                        return {"data": result, "row_count": len(result)}
                    else:
                        conn.commit()
                        return {"data": [], "row_count": cursor.rowcount}

        else:
            raise ValueError(f"Unsupported database type: {db_type}")

    except Exception as e:
        raise RuntimeError(f"Query execution failed: {str(e)}") from e

# --- Command-Line Interface (CLI) for Config Management ---

def main_cli():
    parser = argparse.ArgumentParser(
        description="MCP Database Server & Config CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
  # List all configured database aliases
  %(prog)s list-aliases
  
  # Add a PostgreSQL database
  %(prog)s add-db --alias mydb --type postgres --host localhost --port 5432 --user postgres --password secret --dbname myapp
  
  # Add a MongoDB database
  %(prog)s add-db --alias mymongo --type mongo --uri mongodb://localhost:27017 --dbname myapp
  
  # Execute a SQL query
  %(prog)s execute-query --database_alias mydb --query "SELECT * FROM users LIMIT 5"
  
  # Execute a MongoDB query (automatically converts ObjectId strings)
  %(prog)s execute-query --database_alias mymongo --query '{"campaign": "6850982849bcd9c1f6633874"}' --collection optins
  
  # Execute a parameterized query
  %(prog)s execute-query --database_alias mydb --query "SELECT * FROM users WHERE id = :user_id" --params '{"user_id": 123}'
  
  # List MongoDB collections
  %(prog)s list-collections --database_alias mymongo
  
  # Remove a database connection
  %(prog)s remove-db --alias mydb

NOTES:
  - MongoDB queries automatically convert 24-character strings to ObjectId objects
  - All queries are limited to 10 results by default to prevent large outputs
  - Database credentials are stored encrypted in mcp_config.sqlite3
  - Use single quotes around JSON parameters to avoid shell interpretation
        """
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # 'run' command
    subparsers.add_parser("run", help="Run the MCP server")

    # 'list-aliases' command
    subparsers.add_parser("list-aliases", help="List all configured database aliases")

    # 'add-db' command
    parser_add = subparsers.add_parser("add-db", help="Add a new database connection")
    parser_add.add_argument("--alias", required=True, help="Unique alias for the connection")
    parser_add.add_argument("--type", required=True, choices=["postgres", "mysql", "oracle", "mongo"], help="Database type")
    parser_add.add_argument("--host", help="DB host (not for mongo)")
    parser_add.add_argument("--port", type=int, help="DB port (not for mongo)")
    parser_add.add_argument("--user", help="DB user (not for mongo)")
    parser_add.add_argument("--password", help="DB password (not for mongo)")
    parser_add.add_argument("--dbname", help="DB name (for all types)")
    parser_add.add_argument("--uri", help="MongoDB connection URI")

    # 'remove-db' command
    parser_remove = subparsers.add_parser("remove-db", help="Remove a database connection")
    parser_remove.add_argument("--alias", required=True, help="Alias of the connection to remove")

    # 'execute-query' command
    parser_execute = subparsers.add_parser("execute-query", help="Execute a query on a configured database", 
                                          description="Execute SQL or MongoDB queries. Results are limited to 10 rows by default.")
    parser_execute.add_argument("--database_alias", required=True, help="Alias of the database to connect to")
    parser_execute.add_argument("--query", required=True, help="SQL query or MongoDB query (JSON format)")
    parser_execute.add_argument("--params", help="JSON string of parameters for SQL queries (e.g., '{\"user_id\": 123}')")
    parser_execute.add_argument("--collection", help="Collection name for MongoDB queries (required for MongoDB)")
    parser_execute.add_argument("--oracle_schema", help="Oracle schema to use (optional)")

    # 'list-collections' command
    parser_list_collections = subparsers.add_parser("list-collections", help="List collections for a MongoDB database")
    parser_list_collections.add_argument("--database_alias", required=True, help="Alias of the MongoDB database")

    args = parser.parse_args()

    if args.command == "add-db":
        try:
            params = _build_and_validate_params(
                db_type=args.type, host=args.host, port=args.port, user=args.user, 
                password=args.password, dbname=args.dbname, uri=args.uri
            )
            config_db.add_connection(args.alias, args.type, params)
            print(f"Database connection '{args.alias}' added successfully.")
        except ValueError as e:
            print(f"Error: {e}")
    
    elif args.command == "remove-db":
        if config_db.remove_connection(args.alias):
            print(f"Database connection '{args.alias}' removed successfully.")
        else:
            print(f"Error: Database alias '{args.alias}' not found.")

    elif args.command == "list-aliases":
        aliases = list_aliases()
        if aliases and aliases["aliases"]:
            print("Configured database aliases:")
            for alias_info in aliases["aliases"]:
                print(f"  - Alias: {alias_info['alias']}, Type: {alias_info['type']}")
        else:
            print("No database aliases configured.")

    elif args.command == "execute-query":
        try:
            params = json.loads(args.params) if args.params else None
            result = execute_query(args.database_alias, args.query, params, args.collection, args.oracle_schema)
            print(json.dumps(result, indent=2))
        except (ValueError, RuntimeError) as e:
            print(f"Error: {e}")
    
    elif args.command == "list-collections":
        try:
            collections = list_collections(args.database_alias)
            print(json.dumps(collections, indent=2))
        except (ValueError, RuntimeError) as e:
            print(f"Error: {e}")

    elif args.command == "run" or args.command is None:
        mcp.run()

if __name__ == "__main__":
    main_cli()