#!/bin/bash
# run_agent.sh - Script to start a PAOP agent within the container

# Exit on error
set -e

# Source the virtual environment if not already sourced
if [[ -z "$VIRTUAL_ENV" ]]; then
    echo "Activating Python virtual environment..."
    source /app/.venv/bin/activate
fi

# Set default variables
AGENT_ID="${AGENT_ID:-default_agent}"
CONFIG_FILE="${CONFIG_FILE:-/app/config/agent_config.yml}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

echo "Starting PAOP Agent: $AGENT_ID"
echo "Configuration: $CONFIG_FILE"
echo "Log level: $LOG_LEVEL"

# TODO: Replace this with actual agent startup code
# For now, this is just a placeholder
python -c "
import sys
import time
import logging

# Configure logging
logging.basicConfig(
    level=\"$LOG_LEVEL\",
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger('PAOP-Agent')

# Log startup information
logger.info(f'Starting agent: $AGENT_ID')
logger.info(f'Python version: {sys.version}')
logger.info(f'Using configuration: $CONFIG_FILE')

# Simulate agent running
logger.info('Agent initialized and running...')

try:
    # Keep running until interrupted
    while True:
        logger.debug('Agent heartbeat...')
        time.sleep(10)
except KeyboardInterrupt:
    logger.info('Agent shutdown requested')
finally:
    logger.info('Agent shutting down')
"
