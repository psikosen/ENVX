#!/bin/bash
# Docker entrypoint script
set -e

# Print current directory and Python version
echo "Current directory: $(pwd)"
echo "Python version: $(python --version)"

# Set up Python path properly
export PYTHONPATH="/app:${PYTHONPATH}"

# Set a default API key for development if not provided
if [ -z "${PAOP_API_KEY}" ]; then
    echo "Setting default development API key. DO NOT USE IN PRODUCTION."
    export PAOP_API_KEY="dev-key-DO-NOT-USE-IN-PRODUCTION"
fi

# Print Python path for debugging
echo "PYTHONPATH: ${PYTHONPATH}"

# Print out the import paths Python is using
python -c "import sys; print('Python sys.path:'); [print(f'  - {p}') for p in sys.path]"

# Execute the command
exec "$@"
