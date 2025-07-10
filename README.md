# MCP Database Server

This project provides a Middleware/Control Plane (MCP) server that allows code agents (like Gemini, Claude Desktop, and Claude Code) to securely execute queries against various databases (PostgreSQL, MySQL, MongoDB, Oracle) without directly exposing credentials. Database connection configurations are managed within an SQLite database (`mcp_config.sqlite3`).

## 1. Installation

To set up the project, follow these steps:

1. **Clone the repository** (if you haven't already):

    ```bash
    git clone <repository_url>
    cd custom-mcp-database
    ```

2. **Install dependencies**:
    This project uses a `venv` (virtual environment) to manage dependencies. Run the following command to create the virtual environment and install the required Python packages:

    ```bash
    make install
    ```

    This will create a `venv/` directory and install everything listed in `requirements.txt`.

## 2. Running the MCP Server

To start the MCP server, use the `make run` command:

```bash
make run
```

The server will start and listen for incoming requests from your code agents.

## 3. Database Configuration

Database connections are stored in `mcp_config.sqlite3`. You can manage these connections using the `main.py` script via the command line.

### Adding a Database Connection

Use the `add-db` command. The required parameters vary by database type.

**General Syntax:**

```bash
python main.py add-db --alias <alias> --type <type> [connection_parameters]
```

**Examples:**

* **PostgreSQL**:

    ```bash
    python main.py add-db --alias pg_dev --type postgres --host localhost --port 5432 --user myuser --password mypassword --dbname mydb
    ```

* **MySQL**:

    ```bash
    python main.py add-db --alias mysql_prod --type mysql --host 192.168.1.10 --port 3306 --user root --password secret --dbname production_db
    ```

* **Oracle**:

    ```bash
    python main.py add-db --alias oracle_test --type oracle --host oracle.example.com --port 1521 --user system --password oraclepass --dbname ORCLPDB1
    ```

* **MongoDB**:

    ```bash
    python main.py add-db --alias mongo_cluster --type mongo --uri "mongodb+srv://user:pass@cluster.mongodb.net/" --dbname myapp_db
    ```

### Removing a Database Connection

Use the `remove-db` command with the alias of the connection you want to remove:

```bash
python main.py remove-db --alias <alias>
```

**Example:**

```bash
python main.py remove-db --alias pg_dev
```

## 4. Integration with Code Agents

### Gemini

Once the MCP server is running (`make run`), Gemini will automatically discover and make the following tools available for interacting with your configured databases:

* `list_aliases()`: Lists all configured database aliases.
* `add_database(...)`: Adds a new database connection.
* `remove_database(...)`: Removes a database connection.
* `execute_query(database_alias, query, params, schema)`: Executes a query against a configured database.

**Gemini Usage Examples:**

* **List aliases:**

    ```
    list_aliases()
    ```

* **Execute a SQL query (PostgreSQL/MySQL/Oracle):**

    ```
    execute_query(database_alias="pg_dev", query="SELECT * FROM users WHERE id = %s;", params={"id": 1})
    ```

* **Execute a MongoDB query:**

    ```
    execute_query(database_alias="mongo_cluster", query='''{"name": "John Doe"}''', params={"collection": "users"})
    ```

### Claude Desktop

To integrate with Claude Desktop, you need to configure its `claude_desktop_config.json` file to point to your MCP server. Create or modify this file (usually located in your Claude Desktop configuration directory) with an entry similar to this:

```json
{
  "mcpServers": {
    "Custom DB Server": {
      "command": "/your-path-to/custom-mcp-database/venv/bin/python",
      "args": [
        "/your-path-to/custom-mcp-database/main.py"
      ],
      "workingDirectory": "/your-path-to/custom-mcp-database"
    }
  }
}
```

**Important:** Replace `/your-path-to/custom-mcp-database` with the actual absolute path to your `custom-mcp-database` directory.

After configuring, restart Claude Desktop. The MCP tools will then be available for use within Claude Desktop.

### Tool Configuration for AI Agents

To enable AI agents like Claude Code and Gemini to automatically discover and utilize the MCP server's tools, you need to configure them to launch or connect to the MCP server. This typically involves providing the path to the `main.py` script and specifying the working directory.

Here are examples of how you might configure your AI agent's `mcpServers` section:

#### For Claude Code

```json
{
  "mcpServers": {
    "Custom DB Server": {
      "command": "/your-path-to/custom-mcp-database/venv/bin/python",
      "args": [
        "/your-path-to/custom-mcp-database/main.py"
      ],
      "workingDirectory": "/your-path-to/custom-mcp-database"
    }
  }
}
```

#### For Gemini

```json
{
  "mcpServers": {
    "Custom DB Server": {
      "command": "/your-path-to/custom-mcp-database/venv/bin/python",
      "args": [
        "/your-path-to/custom-mcp-database/main.py"
      ],
      "workingDirectory": "/your-path-to/custom-mcp-database"
    }
  }
}
```

**Important:** Replace `/your-path-to/custom-mcp-database` with the actual absolute path to your `custom-mcp-database` directory.

Refer to your specific AI agent's official documentation for the most accurate and up-to-date instructions on configuring external MCP servers.
