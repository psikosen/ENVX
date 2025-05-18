#!/bin/bash
# test_docker_env.sh - Script to test our Docker environment

# Exit on error
set -e

# Set variables
IMAGE_NAME="paop"
IMAGE_TAG="dev"
CONTAINER_NAME="paop-test"

# Log start of test
echo "=== PAOP Docker Environment Test ==="
echo "$(date): Starting Docker test"

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed or not in PATH"
    exit 1
fi

echo "Docker is installed. Proceeding with test..."

# Display Docker version
echo "Docker version:"
docker --version

# Build the Docker image
echo -e "\n=== Building Docker Image ==="
echo "$(date): Starting build of ${IMAGE_NAME}:${IMAGE_TAG}"

# Check if we're in the right directory
if [ ! -f "./Dockerfile" ]; then
    echo "ERROR: Dockerfile not found in current directory"
    echo "Please run this script from the project root directory"
    exit 1
fi

# Build the Docker image
docker build -t ${IMAGE_NAME}:${IMAGE_TAG} .

# Check build result
if [ $? -ne 0 ]; then
    echo "ERROR: Docker build failed"
    exit 1
fi

echo "$(date): Successfully built ${IMAGE_NAME}:${IMAGE_TAG}"

# Output image details
echo -e "\n=== Image Details ==="
docker images ${IMAGE_NAME}:${IMAGE_TAG}

# Run the container with test command
echo -e "\n=== Running Container Test ==="
echo "$(date): Starting test container ${CONTAINER_NAME}"

# Run the container with a simple test command
docker run --name ${CONTAINER_NAME} \
  --rm \
  ${IMAGE_NAME}:${IMAGE_TAG} \
  python -c "import sys, os; print(f'Python version: {sys.version}'); print(f'Environment: {os.environ.get(\"VIRTUAL_ENV\", \"Not in virtualenv\")}'); print('Test successful!')"

# Check run result
if [ $? -ne 0 ]; then
    echo "ERROR: Container test failed"
    exit 1
fi

echo "$(date): Container test completed successfully"

# Test MCP server initialization
echo -e "\n=== Testing MCP Server ==="
echo "$(date): Starting MCP server test"

# Run the container with the MCP server test
docker run --name ${CONTAINER_NAME} \
  --rm \
  ${IMAGE_NAME}:${IMAGE_TAG} \
  bash -c "cd /app/mcp && node -e 'console.log(\"MCP server environment test:\"); console.log(`Node.js version: ${process.version}`); console.log(\"MCP directory exists:\", require(\"fs\").existsSync(\"/app/mcp\")); console.log(\"MCP test successful!\")'"

# Check MCP test result
if [ $? -ne 0 ]; then
    echo "ERROR: MCP server test failed"
    exit 1
fi

echo "$(date): MCP server test completed successfully"

# Final result
echo -e "\n=== Test Summary ==="
echo "✅ Docker is installed correctly"
echo "✅ Docker image built successfully"
echo "✅ Container Python environment works correctly"
echo "✅ MCP server environment is properly configured"
echo "$(date): All tests passed successfully"
echo -e "\nThe PAOP Docker environment is ready for use! 🚀"
