#!/bin/bash
# Make this script executable with: chmod +x scripts/run.sh
set -e

# Run script for Pedantic Agent Orchestration Platform (PAOP)

# Set up logging
LOG_FILE="run_log.txt"
echo "Starting agent at $(date)" | tee $LOG_FILE

# Activate virtual environment
echo "Activating virtual environment..." | tee -a $LOG_FILE
source .venv/bin/activate

# Check for agent configuration file
if [ ! -f "config/supervisor.yml" ]; then
    echo "Warning: Supervisor configuration not found at config/supervisor.yml" | tee -a $LOG_FILE
    echo "Will attempt to run default orchestrator agent" | tee -a $LOG_FILE
    
    # Run a single orchestrator agent
    echo "Running orchestrator agent..." | tee -a $LOG_FILE
    python src/main.py --role orchestrator --agent-id default-orchestrator | tee -a $LOG_FILE
else
    # Run multiple agents via supervisor
    echo "Running agent supervisor..." | tee -a $LOG_FILE
    python src/supervisor.py --config config/supervisor.yml | tee -a $LOG_FILE
fi

# Cleanup
echo "Agent process completed at $(date)" | tee -a $LOG_FILE
deactivate

echo "Agent run completed"