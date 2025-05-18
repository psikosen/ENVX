#!/bin/bash
# Run the PAOP external interface API server

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Set default configuration if not provided
API_CONFIG="${1:-$DIR/../config/api_config.json}"

# Set Python path to include the root directory so that 'src' can be imported
export PYTHONPATH="$DIR/..:$PYTHONPATH"

# Start the API server
echo "Starting PAOP API server with config: $API_CONFIG"
# Use a simple Python command that avoids module resolution issues
python /app/src/external_interface/main.py --config "$API_CONFIG"
