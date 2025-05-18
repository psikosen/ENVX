#!/bin/bash
# Run all tests for the PAOP external interface

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Set Python path to include src directory
export PYTHONPATH="$DIR/../src:$PYTHONPATH"

echo "===== Testing PAOP External Interface ====="

echo -e "\n===== Running Model Tests ====="
python $DIR/test_models.py

echo -e "\n===== Running API Tests ====="
python $DIR/test_api.py

echo -e "\n===== Running Client Tests ====="
python $DIR/test_client.py

echo -e "\n===== All Tests Completed! ====="
