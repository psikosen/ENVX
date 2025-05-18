#!/bin/bash
# verify_env.sh - Verify the container environment
# This script is designed to run inside the Docker container to verify the environment

# Exit on error
set -e

echo "=== PAOP Container Environment Verification ==="
echo "$(date): Starting verification"

# Check Python environment
echo -e "\n=== Python Environment ==="
echo "Python version: $(python --version)"
echo "Using virtualenv: $VIRTUAL_ENV"
echo "Python path: $PYTHONPATH"

# Check Python dependencies
echo -e "\n=== Python Dependencies ==="
pip list | grep -E 'pydantic|requests'

# Check Node.js environment
echo -e "\n=== Node.js Environment ==="
echo "Node.js version: $(node --version)"
echo "NPM version: $(npm --version)"

# Check MCP installation
echo -e "\n=== MCP Installation ==="
if [ -d "/app/mcp" ]; then
    echo "MCP directory exists: ✅"
    echo "MCP files:"
    ls -la /app/mcp | head -n 10
else
    echo "MCP directory does not exist: ❌"
fi

# Check MCP configuration
echo -e "\n=== MCP Configuration ==="
if [ -f "/app/.config/mcp/config.json" ]; then
    echo "MCP configuration exists: ✅"
    echo "Configuration content:"
    cat /app/.config/mcp/config.json
else
    echo "MCP configuration does not exist: ❌"
fi

# Check file permissions
echo -e "\n=== File Permissions ==="
echo "Current user: $(whoami)"
echo "Permissions for /app directory:"
ls -la /app | head -n 10

# Check network access
echo -e "\n=== Network Access ==="
echo "Hostname: $(hostname)"
echo "IP address: $(hostname -i || echo 'Not available')"

echo -e "\n=== Verification Complete ==="
echo "$(date): Verification completed"
