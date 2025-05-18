#!/bin/bash
# entrypoint.sh - Main entrypoint for the PAOP container
# This script activates the Python virtual environment and executes the given command

# Source the virtual environment
source /app/.venv/bin/activate

# Start the MCP server in the background
cd /app/mcp
node /app/mcp/dist/index.js &
MCP_PID=$!

# Wait for the MCP server to initialize
echo "Starting MCP server (PID: $MCP_PID)..."
sleep 2

# Function to clean up processes when container is stopped
cleanup() {
    echo "Stopping MCP server (PID: $MCP_PID)..."
    kill $MCP_PID
    wait $MCP_PID
    echo "MCP server stopped."
    exit 0
}

# Set trap for SIGTERM and SIGINT
trap cleanup SIGTERM SIGINT

# Execute the command passed to the script
echo "Executing: $@"
exec "$@"
