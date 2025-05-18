#!/bin/bash
# This script fixes the import errors in the Docker container

# Navigate to /app directory
cd /app || exit 1

# Fix the imports in api.py
sed -i 's/from ..agent_framework.orchestrator import OrchestratorClient/from src.agent_framework.orchestrator import OrchestratorClient/' /app/src/external_interface/api.py

# Fix the imports in orchestrator.py
sed -i 's/from ..external_interface.models import/from src.external_interface.models import/' /app/src/agent_framework/orchestrator.py 

# Fix the imports in orchestrator_client.py
sed -i 's/from ..external_interface.models import/from src.external_interface.models import/' /app/src/agent_framework/orchestrator_client.py

# Update the run_api.sh script to use the correct module path
sed -i 's/python -m external_interface.main/python -m src.external_interface.main/' /app/scripts/run_api.sh

# Make sure we're using the right Python path
export PYTHONPATH=/app:$PYTHONPATH

echo "Import fixes applied. Ready to start the application."

# Pass control to the original entrypoint
exec "$@"
