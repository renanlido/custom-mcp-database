# Security Policy & Protocol

This MCP server brokers **real database credentials** and can touch **production,
potentially sensitive data**. It is built **deny-by-default**: out of the box it is
read-only, blocks server-side JavaScript in MongoDB, validates identifiers, caps
result size, and redacts secrets from errors. This document is the protocol to follow
when deploying and operating it.

## Threat model

| Actor | Capability | Primary risk |
| --- | --- | --- |
| The driving LLM/agent | Chooses tool args (SQL string, Mongo filter, alias) | Destructive or exfiltrating queries — especially under **prompt injection** from data it read elsewhere |
| Local processes on the host | Can read files the user can read | Reading the credential store |
| The data itself | Query results flow back into the model | **Indirect prompt injection**: rows containing text that manipulates the agent |

The server trusts: environment variables and CLI flags (operator-controlled), and the
operator who configures connections. It does **not** trust the query content the agent
produces, nor the data returned by the databases.

## Built-in guards

| Guard | What it does | Where |
| --- | --- | --- |
| Read-only by default | Only SELECT-class SQL runs unless explicitly opted in | `security.enforce_sql_policy` |
| Single-statement only | Rejects `;`-stacked statements (after stripping comments) | `security.enforce_sql_policy` |
| Write/DDL opt-in | INSERT/UPDATE/DELETE need `MCP_DB_ALLOW_WRITES`; DDL needs `MCP_DB_ALLOW_DDL` | `security.enforce_sql_policy` |
| Identifier validation | `oracle_schema` (interpolated, cannot be bound) is charset/length checked | `security.validate_identifier` |
| Mongo JS block | Rejects `$where`, `$function`, `$accumulator`, `$expr`, `$out`, `$merge`, mapReduce | `security.enforce_mongo_filter` |
| Result cap | Every result limited to `MCP_DB_MAX_ROWS` (default 1000); `truncated` flag returned | `core.execute_query` |
| Error redaction | Known secrets (password, DSN, URI) stripped from error messages | `security.redact` |
| Credential file perms | Config SQLite chmod'd to `0600` | `config_db._harden_permissions` |
| No credential intake via agent | Add/remove tools are off the MCP surface by default; provisioning is CLI/human-only | `security.admin_tools_enabled` |
| Secret-by-reference | Passwords/URIs can be stored as an env-var name or file path, resolved at connect time — plaintext never persisted | `core.resolve_secrets` |
| Secure CLI prompt | `add-db` prompts with hidden input when no secret/reference is given | `cli` (getpass) |
| Parameterized binds | Values passed via driver placeholders, never string-formatted | `core.execute_query` |

Check the live posture any time: `custom-mcp-database security-status` or the
`db_security_status` MCP tool.

## Configuration (environment variables)

| Variable | Default | Effect |
| --- | --- | --- |
| `MCP_DB_READONLY` | `1` | Master switch. While `1`, all writes/DDL are blocked regardless of the flags below. |
| `MCP_DB_ALLOW_WRITES` | `0` | With `MCP_DB_READONLY=0`, permits INSERT/UPDATE/DELETE/MERGE. |
| `MCP_DB_ALLOW_DDL` | `0` | With `MCP_DB_READONLY=0`, permits CREATE/DROP/ALTER/TRUNCATE/GRANT and procedure execution. |
| `MCP_DB_MAX_ROWS` | `1000` | Hard cap on rows/documents returned per call. |
| `MCP_DB_ALLOW_ADMIN_TOOLS` | `0` | `1` re-exposes `db_add_database`/`db_remove_database` over MCP. Leave `0`. |
| `MCP_DB_CONFIG` | — | Path to the credential SQLite file (else `~/.config/custom-mcp-database/`). |

## Credential intake — never through the agent

An MCP tool's arguments are produced and read by the LLM. A password passed as a tool
argument therefore lands in the model's context, the model provider, and any transcript
or log — "se vaza pro agente, vaza geral". To prevent this:

- The credential-management tools (`db_add_database`/`db_remove_database`) are **not
  exposed over MCP by default**. Connections are provisioned out-of-band with the
  `custom-mcp-database` CLI, run by a human in their terminal.
- Provide secrets **by reference**: `--password-env NAME` / `--password-file PATH`
  (and `--uri-env` / `--uri-file` for MongoDB). Only the reference is stored; the value
  is resolved from the environment or file at connection time.
- Omit `--password`/`--uri` to be **prompted with hidden input** (kept out of shell
  history and the process list).
- If you set `MCP_DB_ALLOW_ADMIN_TOOLS=1`, the exposed add tool still accepts secrets
  **only by reference** — never a literal password — but you reintroduce the agent into
  the provisioning path. Prefer leaving it off.

Writes against production require a **deliberate** `MCP_DB_READONLY=0` +
`MCP_DB_ALLOW_WRITES=1`. Keep DDL off unless you truly need it.

## Operating protocol (required)

1. **Least-privilege database accounts.** The credentials you store define the real
   ceiling — the app-layer guards are defense-in-depth, not a substitute. For
   read-only use, create a DB role with `SELECT`-only grants. Never store a superuser/DBA
   account. Per-environment, prefer a dedicated reporting replica over the primary.
2. **Separate aliases per privilege.** e.g. `prod_ro` (read replica, SELECT-only role)
   vs `prod_rw` (only added when a write task is scheduled, then removed).
3. **Keep read-only on** unless a specific task needs writes; flip the env for that
   session only, then flip it back.
4. **TLS to the database.** Use TLS-enabled connections (e.g. Postgres `sslmode=require`
   via the host/params, MongoDB `mongodb+srv://` / `tls=true` in the URI). Do not send
   credentials or data over plaintext links.
5. **Protect the credential store.** It is `0600` plaintext SQLite. Rely on full-disk
   encryption; restrict the host account. Rotate credentials if the host is shared or
   compromised.
6. **Treat query results as untrusted.** Returned rows may contain text crafted to
   steer the agent (indirect prompt injection). Do not let the agent act on instructions
   found in data; keep human approval for any side-effectful follow-up.
7. **stdio transport only** for local use — it limits the server to the parent MCP
   client. Do not expose this server over an unauthenticated network port.
8. **Review before enabling writes** in any shared/automated context.

## What the guards do NOT do

- They do not make a DBA-privileged DB account safe. Scope the account.
- They do not encrypt credentials at rest (the file is `0600` plaintext). Use disk encryption.
- They do not parse every SQL dialect perfectly. The DB-level read-only role is the
  authoritative backstop.

## Automated scanning

CI runs continuous security checks so regressions surface early:

- **CodeQL** (`security-extended`) — static analysis on push/PR and weekly.
- **Dependabot** — weekly CVE alerts + update PRs for Python deps and GitHub Actions.
- **pip-audit** — fails CI if a dependency has a known vulnerability.
- **gitleaks** — fails CI if a secret is committed.

These complement, but do not replace, the runtime guards and the least-privilege
database account.

## Reporting a vulnerability

Do not open a public issue for security reports. Use **GitHub → Security → Report a
vulnerability** (private advisory) on `renanlido/custom-mcp-database`, or contact the
maintainer directly. Include affected version, reproduction, and impact. Please allow a
reasonable window for a fix before public disclosure.
