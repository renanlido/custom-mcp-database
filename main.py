import os
import json
import psycopg2
import psycopg2.extras
import mysql.connector
import oracledb
from pymongo import MongoClient
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load environment variables from .env file
load_dotenv()

# Initialize the MCP server
mcp = FastMCP()

# --- Database Connection Logic (Helper Functions) ---

def get_db_configs():
    configs = {}
    # PostgreSQL
    i = 1
    while True:
        alias = os.getenv(f"DB_POSTGRES_ALIAS_{i}")
        if not alias: break
        configs[alias] = {
            "type": "postgres",
            "conn_params": {
                "host": os.getenv(f"DB_POSTGRES_HOST_{i}"),
                "port": os.getenv(f"DB_POSTGRES_PORT_{i}", 5432),
                "user": os.getenv(f"DB_POSTGRES_USER_{i}"),
                "password": os.getenv(f"DB_POSTGRES_PASSWORD_{i}"),
                "dbname": os.getenv(f"DB_POSTGRES_DBNAME_{i}"),
            }
        }
        i += 1

    # MySQL
    i = 1
    while True:
        alias = os.getenv(f"DB_MYSQL_ALIAS_{i}")
        if not alias: break
        configs[alias] = {
            "type": "mysql",
            "conn_params": {
                "host": os.getenv(f"DB_MYSQL_HOST_{i}"),
                "port": os.getenv(f"DB_MYSQL_PORT_{i}", 3306),
                "user": os.getenv(f"DB_MYSQL_USER_{i}"),
                "password": os.getenv(f"DB_MYSQL_PASSWORD_{i}"),
                "database": os.getenv(f"DB_MYSQL_DBNAME_{i}"),
            }
        }
        i += 1
    
    # MongoDB
    i = 1
    while True:
        alias = os.getenv(f"DB_MONGO_ALIAS_{i}")
        if not alias: break
        configs[alias] = {
            "type": "mongo",
            "uri": os.getenv(f"DB_MONGO_URI_{i}"),
            "dbname": os.getenv(f"DB_MONGO_DBNAME_{i}"),
        }
        i += 1

    # Oracle
    i = 1
    while True:
        alias = os.getenv(f"DB_ORACLE_ALIAS_{i}")
        if not alias: break
        host = os.getenv(f"DB_ORACLE_HOST_{i}")
        port = os.getenv(f"DB_ORACLE_PORT_{i}", 1521)
        dbname = os.getenv(f"DB_ORACLE_DBNAME_{i}")
        dsn = f"{host}:{port}/{dbname}"
        
        configs[alias] = {
            "type": "oracle",
            "conn_params": {
                "user": os.getenv(f"DB_ORACLE_USER_{i}"),
                "password": os.getenv(f"DB_ORACLE_PASSWORD_{i}"),
                "dsn": dsn,
            }
        }
        i += 1
    return configs

# --- MCP Tool Definition ---

@mcp.tool()
def list_aliases() -> Dict[str, Any]:
    """
    Lists all configured database aliases.
    :return: A dictionary containing a list of database aliases.
    """
    db_configs = get_db_configs()
    return {"aliases": list(db_configs.keys())}

@mcp.tool()
def execute_query(
    database_alias: str,
    query: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Executes a query on a configured database and returns the result.

    :param database_alias: The alias of the database to connect to (e.g., 'pg_local').
    :param query: The SQL query or MongoDB find filter (as a JSON string) to execute.
    :param params: For SQL, a dict of parameters to prevent injection. For MongoDB, a dict specifying the collection, e.g., {"collection": "my_collection"}.
    :return: A dictionary containing the query result and row count.
    """
    db_configs = get_db_configs()
    db_info = db_configs.get(database_alias)

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
            if not params or "collection" not in params:
                raise ValueError("MongoDB query requires 'collection' in params.")
            
            collection = db[params["collection"]]
            filter_query = json.loads(query)
            documents = list(collection.find(filter_query))
            for doc in documents:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
            client.close()
            return {"data": documents, "row_count": len(documents)}

        elif db_type == "oracle":
            with oracledb.connect(**db_info["conn_params"]) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params or {})
                    if cursor.description:
                        # Make rows accessible by column name
                        cursor.rowfactory = lambda *args: dict(zip([d[0].lower() for d in cursor.description], args))
                        result = cursor.fetchall()
                        return {"data": result, "row_count": len(result)}
                    else:
                        conn.commit()
                        return {"data": [], "row_count": cursor.rowcount}

        else:
            raise ValueError(f"Unsupported database type: {db_type}")

    except Exception as e:
        # Re-raise as a generic exception for the MCP client to handle
        raise RuntimeError(f"Query execution failed: {str(e)}") from e

if __name__ == "__main__":
    mcp.run()