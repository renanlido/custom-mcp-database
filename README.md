# Custom MCP Database

<!-- MCP Registry ownership proof — required to publish to registry.modelcontextprotocol.io -->
mcp-name: io.github.renanlido/custom-mcp-database

An [MCP](https://modelcontextprotocol.io) server that lets AI agents run **alias-based**
queries against **PostgreSQL, MySQL, MongoDB and Oracle** — without ever exposing
credentials to the model. Connections are configured once and stored locally; the
agent only ever references them by alias.

Works with Claude Code, Claude Desktop, Cursor, VS Code, Windsurf, Gemini CLI, and
any other MCP client (all use the same stdio launch command).

---

## Quickstart

There are **two roles**, on purpose. Keeping them separate is what stops your DB
password from ever reaching the model.

### You (once, in your terminal) — install the credentials

The **agent never installs credentials.** You do, with the CLI. The secret stays on
your machine and is never sent to the model.

```bash
# 1. add a connection (you'll be prompted for the password — hidden input)
uvx custom-mcp-database add-db --alias prod_ro --type postgres \
  --host db.internal --port 5432 --user reporting --dbname app

# 2. confirm it's there
uvx custom-mcp-database list-aliases
```

### The agent (always) — uses it by alias

Point your MCP client at the server (see [Install](#install)), then just ask:

> "Using **prod_ro**, run `SELECT count(*) FROM orders`."

The agent calls `db_execute_query` with the **alias** `prod_ro` — never a host, user,
or password. It physically cannot see the credentials; they live in your local config,
resolved only inside the server process at query time.

**Why the agent can't add the DB:** an MCP tool's arguments are produced and read by the
LLM. If the agent typed your password into an `add` tool, that password would land in the
model's context, the provider, and the logs. So credential setup is a human/CLI step by
design. (Need an agent to wire connections in an automated pipeline? See
`MCP_DB_ALLOW_ADMIN_TOOLS` in [SECURITY.md](SECURITY.md) — even then it only accepts a
*reference* to a secret, e.g. an env-var name, never the secret itself.)

Writes are **off by default** (read-only). To allow them for a task:
`export MCP_DB_READONLY=0 MCP_DB_ALLOW_WRITES=1`.

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

**Configure connections from your terminal with the CLI — never through the agent.**
A connection's password is a real secret; if it were passed as an MCP tool argument it
would enter the model's context (and the provider, transcripts, and logs). So the
credential-management tools are **off the MCP surface by default**; provisioning is a
human/CLI task. The agent only lists and uses aliases.

Omit `--password`/`--uri` to be prompted securely (hidden input, not stored in shell
history). Even better, keep the secret out of the config file entirely with
`--password-env` / `--password-file` (resolved at connection time):

```bash
# PostgreSQL — prompted for the password (recommended)
uvx custom-mcp-database add-db --alias pg --type postgres \
  --host localhost --port 5432 --user me --dbname app

# MySQL — password taken from an env var at connect time (nothing secret on disk)
MYSQL_PW=... uvx custom-mcp-database add-db --alias my --type mysql \
  --host localhost --port 3306 --user root --dbname app --password-env MYSQL_PW

# Oracle — password read from a file (e.g. a mounted secret)
uvx custom-mcp-database add-db --alias ora --type oracle \
  --host db.example.com --port 1521 --user system --dbname ORCLPDB1 \
  --password-file /run/secrets/ora_pw

# MongoDB — full URI from a file (the URI embeds credentials)
uvx custom-mcp-database add-db --alias mongo --type mongo \
  --dbname app --uri-file /run/secrets/mongo_uri

uvx custom-mcp-database list-aliases
uvx custom-mcp-database remove-db --alias pg
```

Config location (override with `MCP_DB_CONFIG`):
`$XDG_CONFIG_HOME/custom-mcp-database/mcp_config.sqlite3`
(default `~/.config/custom-mcp-database/mcp_config.sqlite3`, `0600`).

> If you pass a literal `--password`/`--uri`, it is stored as **plaintext JSON** in that
> SQLite file. Prefer `--password-env`/`--password-file` (or `--uri-env`/`--uri-file`) so
> only a reference is stored. Either way, keep the file secret (it is `0600`, gitignored,
> not encrypted).

---

## MCP tools

| Tool | Purpose |
| --- | --- |
| `db_list_aliases` | List configured aliases and types |
| `db_execute_query` | Run SQL or a MongoDB JSON filter |
| `db_list_collections` | List MongoDB collections |
| `db_security_status` | Report the active security policy |

`db_add_database` / `db_remove_database` are **not exposed over MCP by default** — manage
connections with the CLI. To opt into exposing them (the add tool only accepts secrets by
reference, never a literal password), set `MCP_DB_ALLOW_ADMIN_TOOLS=1`.

`db_execute_query` notes: SQL runs as given with parameterized binds (add your own
`LIMIT`); MongoDB takes a JSON filter + `collection`, caps results at 10 (`--limit`),
rejects empty filters, and coerces 24-char hex strings to `ObjectId`.

---

## Security

This server handles **real credentials** and **production data**, so it ships
**deny-by-default**:

- **Read-only by default.** Only SELECT-class SQL runs. Writes/DDL require explicit opt-in.
- **No stacked statements** (`;`-injection blocked), **single statement per call**.
- **MongoDB server-side JavaScript blocked** (`$where`, `$function`, `$accumulator`, mapReduce, …).
- **Identifiers validated** (`oracle_schema` can't be used for injection).
- **Results capped** at `MCP_DB_MAX_ROWS` (default 1000); **secrets redacted** from errors.
- **Credential store** is `0600` plaintext SQLite — keep the host disk encrypted.

Check the live posture: `custom-mcp-database security-status` (or the `db_security_status` tool).

Enable writes for a specific task (then turn it back off):

```bash
export MCP_DB_READONLY=0
export MCP_DB_ALLOW_WRITES=1     # INSERT/UPDATE/DELETE
# export MCP_DB_ALLOW_DDL=1      # only if you really need CREATE/DROP/ALTER/...
```

**Read the full protocol — least-privilege DB roles, TLS, prompt-injection handling,
vulnerability reporting — in [SECURITY.md](SECURITY.md).** The app-layer guards are
defense-in-depth; the authoritative control is a least-privilege database account.

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
