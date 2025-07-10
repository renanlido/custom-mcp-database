.PHONY: run install

# Target to install dependencies from requirements.txt into the venv
install:
	@echo "Installing dependencies..."
	@./venv/bin/pip install -r requirements.txt

# Target to run the MCP server
run:
	@echo "Starting MCP server..."
	@./venv/bin/python main.py
