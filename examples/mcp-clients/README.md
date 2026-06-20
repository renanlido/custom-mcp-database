# Client configuration snippets

Every major MCP client launches a local (stdio) server the same way: a `command`
plus `args`. The snippets here use `uvx custom-mcp-database run`, which works once
the package is published to PyPI and `uv` is installed. No PyPI yet? Swap the
command for a local checkout:

```json
{ "command": "uv", "args": ["run", "--directory", "/abs/path/to/custom-mcp-database", "custom-mcp-database", "run"] }
```

| Client | Config file | Key | Snippet |
| --- | --- | --- | --- |
| Claude Desktop | `claude_desktop_config.json` | `mcpServers` | [claude-desktop.json](claude-desktop.json) |
| Claude Code | project `.mcp.json` (or `claude mcp add`) | `mcpServers` | [claude-desktop.json](claude-desktop.json) |
| Cursor | `~/.cursor/mcp.json` or `.cursor/mcp.json` | `mcpServers` | [cursor.json](cursor.json) |
| VS Code | `.vscode/mcp.json` | `servers` | [vscode.json](vscode.json) |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | `mcpServers` | [windsurf.json](windsurf.json) |
| Gemini CLI | `~/.gemini/settings.json` | `mcpServers` | [gemini-cli.json](gemini-cli.json) |

VS Code uses the key `servers` (not `mcpServers`) and wants `"type": "stdio"`;
everything else uses `mcpServers`.

## Claude Code one-liners

```bash
# Add the published server directly
claude mcp add custom-mcp-database -- uvx custom-mcp-database run

# Or install the full plugin from this repo's marketplace
/plugin marketplace add renanlido/custom-mcp-database
/plugin install custom-mcp-database@renanlido-mcp
```

## Manage connections

The server starts with no connections. Add them once (stored locally, never
re-sent to the model), then reference them by alias:

```bash
uvx custom-mcp-database add-db --alias pg --type postgres \
  --host localhost --port 5432 --user me --password secret --dbname app
```
