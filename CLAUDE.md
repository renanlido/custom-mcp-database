# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An MCP server that acts as a secure middleware so AI agents can run database queries without seeing raw credentials. Supports PostgreSQL, MySQL, MongoDB, and Oracle. Connections are referenced by alias; the alias→credentials mapping lives in a local SQLite file.

The same entry point serves as both the MCP server (stdio) and a connection-management CLI. It is packaged for distribution across every major MCP client.

## Layout

```
src/custom_mcp_database/
  core.py        # pure logic: validation, query execution per driver (no MCP/CLI coupling)
  server.py      # FastMCP("database_mcp") + db_* tool registration -> calls core
  cli.py         # argparse CLI (run/add-db/remove-db/list-aliases/execute-query/list-collections)
  config_db.py   # SQLite alias store; DB path resolved to a user config dir
  __main__.py    # python -m custom_mcp_database
main.py          # back-compat shim (adds src/ to path, calls cli.main) for old client configs
```

Distribution metadata (one file per channel): `pyproject.toml` (PyPI), `server.json` (MCP Registry), `.claude-plugin/plugin.json` + `.mcp.json` (Claude Code plugin), `.claude-plugin/marketplace.json` (marketplace), `manifest.json` (Claude Desktop MCPB). Client config snippets in `examples/mcp-clients/`.

## Commands

```bash
uv sync                 # install deps into .venv  (make install)
make run                # run the server: uv run custom-mcp-database run
make lint               # uvx ruff check .
make build              # uv build -> dist/  (sdist + wheel)
uv run mcp dev src/custom_mcp_database/server.py   # MCP Inspector

# CLI (also: python -m custom_mcp_database, or uvx custom-mcp-database)
uv run custom-mcp-database setup            # interactive guided wizard (cli._run_setup)
uv run custom-mcp-database add-db --alias <name> --type <postgres|mysql|mongo|oracle> [conn flags]
uv run custom-mcp-database execute-query --database_alias <alias> --query <q> [--params <json>] [--collection <c>] [--limit N]
```

Smoke test (no DB needed) — build then import + assert tool set:
```bash
uv build
uv run --no-project --with ./dist/*.whl python -c "from custom_mcp_database import server; print(sorted(t.name for t in server.mcp._tool_manager.list_tools()))"
```
There is no DB-backed test suite (queries need live databases).

## Architecture — non-obvious details

These require reading `core.py` + `config_db.py` together and are the main sources of confusion:

1. **Three-layer split.** `core.py` holds the only query logic; `server.py` and `cli.py` are thin adapters that both call `core`. Add behavior in `core.py`, expose it in both adapters. Do NOT call the `@mcp.tool`-decorated functions from the CLI — they are FunctionTool objects, not plain callables; use the `core.*` functions.

2. **Per-driver param shapes** ([core.py:60-83](src/custom_mcp_database/core.py:60), `build_and_validate_params`). MySQL stores the db name as `database`; postgres/oracle as `dbname`; oracle collapses host/port/dbname into a single `dsn` (`host:port/dbname`); mongo stores `{uri, dbname}` and ignores host/port/user/password.

3. **`get_connection` returns two shapes** ([config_db.py:64](src/custom_mcp_database/config_db.py:64)) that `execute_query` branches on: mongo → `{type, uri, dbname}`; SQL → `{type, conn_params}` spread into `driver.connect(**conn_params)`.

4. **MongoDB specifics** ([core.py `execute_query`](src/custom_mcp_database/core.py)): `collection` required; empty/`{}` filter rejected; results capped at `limit` (default 10); 24-char hex strings auto-coerced to `ObjectId` via `convert_objectid_strings` (a legitimate 24-char string value becomes an ObjectId). SQL is NOT row-limited by this code.

5. **Config DB path** ([config_db.py:8](src/custom_mcp_database/config_db.py:8), `_resolve_db_file`). Resolves to `$MCP_DB_CONFIG`, else `$XDG_CONFIG_HOME/custom-mcp-database/`, else `~/.config/custom-mcp-database/mcp_config.sqlite3`. This is deliberate so `uvx`/ephemeral installs don't lose config into site-packages. Never hard-code the repo dir.

## Storage & Security

- Connection params are stored as **plaintext JSON** in the SQLite config file ([config_db.py `add_connection`](src/custom_mcp_database/config_db.py)), chmod'd `0600`. Gitignored, not encrypted — treat as a secret.
- SQL uses parameterized binds; oracle uses named binds (`:name`), defaults params to `{}`.
- **Security policy engine: [security.py](src/custom_mcp_database/security.py).** Deny-by-default. `execute_query` calls `enforce_sql_policy` / `enforce_mongo_filter` / `validate_identifier` **before opening any connection** (so `SecurityError` surfaces un-wrapped, not as a DB error). Guards: read-only by default, single-statement only (no `;` stacking), writes need `MCP_DB_ALLOW_WRITES`, DDL needs `MCP_DB_ALLOW_DDL` (both gated by `MCP_DB_READONLY=0`), Mongo JS operators blocked, results capped at `MCP_DB_MAX_ROWS` (default 1000) with a `truncated` flag, driver errors passed through `security.redact` against `collect_secrets`. Posture via `db_security_status` tool / `security-status` CLI. Full protocol in [SECURITY.md](SECURITY.md).
- **Credential intake never goes through the agent.** `db_add_database`/`db_remove_database` are NOT registered as MCP tools unless `MCP_DB_ALLOW_ADMIN_TOOLS=1` ([server.py](src/custom_mcp_database/server.py) `security.admin_tools_enabled()`). Provisioning is CLI-only. The MCP tool, even when enabled, accepts secrets only by reference. Reason: tool args enter the LLM context → provider/logs.
- **Secret-by-reference.** Connections may store `password_env`/`password_file`/`uri_env`/`uri_file` instead of a literal; `core.resolve_secrets` resolves them at connect time and never persists the value. `build_and_validate_params` enforces exactly one secret source. CLI `add-db` prompts via `getpass` when none given. Tests: `tests/test_credentials.py`.
- When adding a query path or tool, route it through the `security.*` guards; never interpolate agent input into SQL/identifiers. Security guards are unit-tested in `tests/test_security.py` (pure, no DB) — keep them green.
- Env vars (all read fresh at call time): `MCP_DB_READONLY` (default 1), `MCP_DB_ALLOW_WRITES`, `MCP_DB_ALLOW_DDL`, `MCP_DB_MAX_ROWS` (1000), `MCP_DB_ALLOW_ADMIN_TOOLS` (0), `MCP_DB_CONFIG`.

## Distribution invariants

- Server display name is `database_mcp`; MCP tool names are prefixed `db_*`.
- Registry id is reverse-DNS `io.github.renanlido/custom-mcp-database`.
- **Version has a single source: `pyproject.toml` `[project].version`.** `scripts/sync_version.py` propagates it into `server.json`, `manifest.json`, `.claude-plugin/plugin.json`, `marketplace.json`. Never hand-edit those version fields; run `make version-sync` (or let CI do it). Add new version-bearing files to `JSON_TARGETS` in that script.
- The universal client launch command is `uvx custom-mcp-database run` (stdio).
- `README.md` MUST keep the line `mcp-name: io.github.renanlido/custom-mcp-database`. The MCP Registry validates PyPI package ownership by requiring that marker in the published README; removing it makes `mcp-publisher publish` fail with HTTP 400.

## Release automation

Push to `main` triggers `.github/workflows/release.yml`: `scripts/bump_version.py` picks the next semver from commit subjects since the last `v*` tag (`feat:`→minor, `BREAKING CHANGE`/`type!:`→major, else patch; `[skip release]` opts out), writes it to pyproject, syncs artifacts, generates the changelog (`scripts/gen_changelog.py` → prepends a grouped section to `CHANGELOG.md` and writes `.release_notes.md`), builds, commits `chore(release): vX [skip ci]` (incl. `CHANGELOG.md`), tags, pushes, then publishes PyPI (OIDC) + MCP Registry + `.mcpb` + GitHub Release (body = `.release_notes.md`). The `[skip ci]` on the release commit is the loop guard. `ci.yml` runs only on PRs. Do NOT add a `push: main` trigger that builds/publishes elsewhere — it would double-publish.
