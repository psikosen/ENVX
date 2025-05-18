#!/bin/bash
# setup_mcp.sh - Script to set up DesktopCommanderMCP in the container

# Exit on error
set -e

# Log start
echo "Setting up DesktopCommanderMCP..."

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "Error: Node.js is not installed. Please install Node.js v18.18.0 or later."
    exit 1
fi

# Check Node.js version
NODE_VERSION=$(node -v | cut -d 'v' -f 2)
NODE_MAJOR_VERSION=$(echo $NODE_VERSION | cut -d '.' -f 1)

if [ "$NODE_MAJOR_VERSION" -lt 18 ]; then
    echo "Error: Node.js v18.18.0 or later is required. Current version: $NODE_VERSION"
    exit 1
fi

echo "Node.js version $NODE_VERSION detected. Proceeding with installation..."

# Set up MCP directory
MCP_DIR="/app/mcp"
mkdir -p "$MCP_DIR"

# Clone DesktopCommanderMCP if not already present
if [ ! -d "$MCP_DIR/node_modules" ]; then
    echo "Installing DesktopCommanderMCP dependencies..."
    cd "$MCP_DIR"
    npm install
fi

# Build MCP if not already built
if [ ! -d "$MCP_DIR/dist" ]; then
    echo "Building DesktopCommanderMCP..."
    cd "$MCP_DIR"
    npm run build
fi

# Set up MCP configuration
CONFIG_DIR="/app/.config/mcp"
mkdir -p "$CONFIG_DIR"

# Create MCP config if it doesn't exist
if [ ! -f "$CONFIG_DIR/config.json" ]; then
    echo "Creating MCP configuration..."
    echo '{
        "mcpServers": {
            "desktop-commander": {
                "command": "node",
                "args": ["/app/mcp/dist/index.js"]
            }
        }
    }' > "$CONFIG_DIR/config.json"
fi

# Set proper permissions
chown -R $(whoami) "$MCP_DIR" "$CONFIG_DIR"

echo "DesktopCommanderMCP setup complete!"
