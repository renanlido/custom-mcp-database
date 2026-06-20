.PHONY: install run lint build clean version-sync version-check publish-test

# Sync deps into a uv-managed virtualenv (.venv)
install:
	@uv sync

# Run the MCP server (stdio)
run:
	@uv run custom-mcp-database run

# Lint
lint:
	@uvx ruff check .

# Propagate pyproject version into all distribution artifacts
version-sync:
	@uv run --no-project python scripts/sync_version.py

# Fail if any artifact version drifts from pyproject (CI guard)
version-check:
	@uv run --no-project python scripts/sync_version.py --check

# Build sdist + wheel into dist/
build: version-sync
	@uv build

# Remove build artifacts
clean:
	@rm -rf dist build *.egg-info src/*.egg-info

# Build + upload to TestPyPI (needs UV_PUBLISH_TOKEN or TestPyPI creds)
publish-test: build
	@uv publish --publish-url https://test.pypi.org/legacy/
