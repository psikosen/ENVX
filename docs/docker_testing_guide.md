# PAOP Docker Environment Testing Guide

This document provides instructions for testing the Docker environment to ensure it's properly configured.

## Prerequisites

Make sure you have Docker installed on your system:

```bash
docker --version
```

Should return something like: `Docker version 24.0.6, build ed223bc`

## Testing Process

### Step 1: Build the Docker Image

```bash
# Navigate to the project root directory
cd /Users/psikosen/Documents/envx

# Make scripts executable
chmod +x scripts/*.sh

# Build the Docker image
./scripts/build.sh
```

This script will:
- Build the Docker image named `paop:dev`
- Display the image details when complete

### Step 2: Run the Environment Verification

```bash
# Run container with verification mode
./scripts/run.sh --verify
```

This will:
- Start the container
- Run the verification script inside the container
- Display detailed information about the environment
- Check Python, Node.js, and MCP configuration

### Step 3: Test MCP Integration

```bash
# Run the container with an interactive shell
docker run --rm -it paop:dev bash

# Inside the container, run:
cd /app/mcp
node -e 'console.log(`Node.js version: ${process.version}`); console.log("MCP directory exists:", require("fs").existsSync("/app/mcp")); console.log("MCP dist exists:", require("fs").existsSync("/app/mcp/dist"))'

# You should see confirmation that MCP is properly installed
# Exit the container
exit
```

### Step 4: Test Python Environment

```bash
# Run the container with Python check
docker run --rm paop:dev python -c "import sys, os; print(f'Python version: {sys.version}'); print(f'Virtual env: {os.environ.get(\"VIRTUAL_ENV\")}'); import pydantic; print(f'Pydantic version: {pydantic.__version__}')"
```

### Step 5: Test Full Container Startup

```bash
# Run the container with the default command
./scripts/run.sh
```

You should see the initialization message confirming that the environment is ready.

## Troubleshooting

If you encounter issues:

1. **Build Errors**: 
   - Check Docker installation
   - Ensure all files are in the correct locations
   - Review Dockerfile for any syntax errors

2. **Runtime Errors**:
   - Check that Python dependencies are correctly specified in requirements files
   - Ensure MCP is properly cloned and built
   - Verify file permissions are correct

3. **MCP Integration Issues**:
   - Verify Node.js is installed correctly
   - Check MCP repository URL is correct
   - Ensure npm build command completes successfully

## Expected Results

A successful test should show:
- Docker image builds without errors
- Container starts successfully
- Python virtual environment is active
- Node.js is available and functional
- MCP is properly installed and configured

If all these checks pass, your Docker environment is correctly set up and ready for development.
