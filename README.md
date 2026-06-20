# Custom MCP Database

An [MCP](https://modelcontextprotocol.io) server that lets AI agents run **alias-based**
queries against **PostgreSQL, MySQL, MongoDB and Oracle** — without ever exposing
credentials to the model. Connections are configured once and stored locally; the
agent only ever references them by alias.

Works with Claude Code, Claude Desktop, Cursor, VS Code, Windsurf, Gemini CLI, and
any other MCP client (all use the same stdio launch command).

---

## Install

The server runs over **stdio**. The universal launch command is `uvx custom-mcp-database run`
(requires [uv](https://docs.astral.sh/uv/); the package is fetched from PyPI on first run).

### Claude Code

```bash
# Direct (published package)
claude mcp add custom-mcp-database -- uvx custom-mcp-database run

# Or install the full plugin from this repo's marketplace
/plugin marketplace add renanlido/custom-mcp-database
/plugin install custom-mcp-database@renanlido-mcp
```

### Claude Desktop

Two options:

1. **One-click bundle** — build the `.mcpb` (`mcpb pack`) and open it in Claude Desktop. See [Distribution](#distribution).
2. **Manual config** — add the snippet from [`examples/mcp-clients/claude-desktop.json`](examples/mcp-clients/claude-desktop.json) to `claude_desktop_config.json`.

### Other clients

Copy the matching snippet — all use the same `command`/`args`, only the file and key differ:

| Client | Config file | Key | Snippet |
| --- | --- | --- | --- |
| Cursor | `~/.cursor/mcp.json` | `mcpServers` | [cursor.json](examples/mcp-clients/cursor.json) |
| VS Code | `.vscode/mcp.json` | `servers` | [vscode.json](examples/mcp-clients/vscode.json) |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | `mcpServers` | [windsurf.json](examples/mcp-clients/windsurf.json) |
| Gemini CLI | `~/.gemini/settings.json` | `mcpServers` | [gemini-cli.json](examples/mcp-clients/gemini-cli.json) |

Full client matrix and a local-checkout variant: [`examples/mcp-clients/README.md`](examples/mcp-clients/README.md).

---

## Configure connections

The server starts empty. Add connections via the CLI (or the `db_add_database` tool).
Credentials are written to local SQLite and never re-sent to the model.

```bash
# PostgreSQL
uvx custom-mcp-database add-db --alias pg --type postgres \
  --host localhost --port 5432 --user me --password secret --dbname app

# MySQL
uvx custom-mcp-database add-db --alias my --type mysql \
  --host localhost --port 3306 --user root --password secret --dbname app

# Oracle
uvx custom-mcp-database add-db --alias ora --type oracle \
  --host db.example.com --port 1521 --user system --password pw --dbname ORCLPDB1

# MongoDB
uvx custom-mcp-database add-db --alias mongo --type mongo \
  --uri "mongodb+srv://user:pw@cluster.mongodb.net/" --dbname app

uvx custom-mcp-database list-aliases
uvx custom-mcp-database remove-db --alias pg
```

Config location (override with `MCP_DB_CONFIG`):
`$XDG_CONFIG_HOME/custom-mcp-database/mcp_config.sqlite3`
(default `~/.config/custom-mcp-database/mcp_config.sqlite3`).

> Credentials are stored as **plaintext JSON** in that SQLite file. Keep it secret;
> it is not committed and not encrypted.

---

## MCP tools

| Tool | Purpose |
| --- | --- |
| `db_list_aliases` | List configured aliases and types |
| `db_add_database` | Add/replace a connection |
| `db_remove_database` | Remove a connection |
| `db_execute_query` | Run SQL or a MongoDB JSON filter |
| `db_list_collections` | List MongoDB collections |

`db_execute_query` notes: SQL runs as given with parameterized binds (add your own
`LIMIT`); MongoDB takes a JSON filter + `collection`, caps results at 10 (`--limit`),
rejects empty filters, and coerces 24-char hex strings to `ObjectId`.

---

## Develop

```bash
uv sync                 # create .venv and install deps
make run                # run the server (stdio)
make lint               # ruff
make build              # sdist + wheel into dist/
```

Inspect tools interactively:

```bash
uv run mcp dev src/custom_mcp_database/server.py
```

---

## Distribution

This repo ships ready-to-publish metadata for every major channel. All of it is
published automatically on push to `main` (see below):

| Channel | File | Published by |
| --- | --- | --- |
| PyPI | `pyproject.toml` | `release.yml` (push to main) |
| MCP Registry | `server.json` | `release.yml` (push to main) |
| Claude Code plugin | `.claude-plugin/plugin.json`, `.mcp.json` | available on GitHub push |
| Claude Code marketplace | `.claude-plugin/marketplace.json` | available on GitHub push |
| Claude Desktop bundle | `manifest.json` | `release.yml` attaches `.mcpb` to the Release |

### Automated release — just push to `main`

Releases are fully automated. On every push to `main`,
[`.github/workflows/release.yml`](.github/workflows/release.yml):

1. Picks the next **semantic version** from your commits since the last tag
   (`feat:` → minor, `BREAKING CHANGE`/`type!:` → major, anything else → patch;
   add `[skip release]` to a commit message to skip).
2. Writes that version into `pyproject.toml` and **syncs it into every artifact**
   (`server.json`, `manifest.json`, plugin + marketplace) via `scripts/sync_version.py` —
   version lives in **one place**, no hand-bumping.
3. Builds, commits `chore(release): vX [skip ci]`, tags `vX`, pushes.
4. Publishes to **PyPI** (Trusted Publishing/OIDC), then the **MCP Registry** (GitHub OIDC).
5. Packs the **`.mcpb`** and cuts a **GitHub Release** with the wheel + bundle attached.

The release commit carries `[skip ci]`, so it does not re-trigger the workflow.

**One-time setup** (can't be automated — needs your accounts):

- Create a [PyPI Trusted Publisher](https://docs.pypi.org/trusted-publishers/) for
  `renanlido/custom-mcp-database`, workflow `release.yml`.
- Allow GitHub Actions to push to `main` (repo → Settings → Actions → *Read and write
  permissions*; if `main` is a protected branch, allow the actions bot to bypass or use a PAT).

The MCP Registry namespace is `io.github.renanlido/custom-mcp-database` (GitHub-validated).

Local manual escape hatch: `make build` (syncs version + builds) then `uv publish`.

---

## License

MIT
