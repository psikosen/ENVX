#!/bin/bash
# run.sh - Run script for the PAOP system

# Exit on error
set -e

# Set colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Set up logging
LOG_FILE="run_log.txt"
echo "=== PAOP System Run Log ($(date)) ===" > $LOG_FILE

# Display header
echo -e "${BOLD}==================================================${NC}"
echo -e "${BOLD}      Pedantic Agent Orchestration Platform       ${NC}"
echo -e "${BOLD}               Running System                     ${NC}"
echo -e "${BOLD}==================================================${NC}"
echo

# Function to log messages
log_message() {
    local level=$1
    local message=$2
    local color=$NC
    
    case $level in
        "INFO") color=$GREEN ;;
        "WARN") color=$YELLOW ;;
        "ERROR") color=$RED ;;
    esac
    
    echo -e "${color}[$level] $message${NC}"
    echo "[$level] $message" >> $LOG_FILE
}

# Function to check prerequisites
check_prerequisites() {
    log_message "INFO" "Checking prerequisites..."
    
    # Check if Docker is available
    if command -v docker &> /dev/null; then
        DOCKER_AVAILABLE=true
        DOCKER_VERSION=$(docker --version | cut -d ' ' -f 3 | tr -d ',')
        log_message "INFO" "Found Docker version: $DOCKER_VERSION"
    else
        DOCKER_AVAILABLE=false
        log_message "WARN" "Docker not found (required for container deployment)"
    fi
    
    # Check if the virtual environment exists
    if [ -d ".venv" ]; then
        VENV_AVAILABLE=true
        log_message "INFO" "Found Python virtual environment"
    else
        VENV_AVAILABLE=false
        log_message "WARN" "Python virtual environment not found"
    fi
    
    log_message "INFO" "Prerequisites check completed"
}

# Function to run in Docker mode
run_docker() {
    if [ "$DOCKER_AVAILABLE" != true ]; then
        log_message "ERROR" "Docker is required for container deployment but not installed"
        exit 1
    fi
    
    log_message "INFO" "Running in Docker mode..."
    
    # Check if Docker image exists
    if ! docker images | grep -q "paop"; then
        log_message "WARN" "Docker image not found, building..."
        ./build_all.sh
    fi
    
    # Run Docker container
    log_message "INFO" "Starting Docker container..."
    docker run --rm -p 8000:8000 -e PAOP_API_KEY="${PAOP_API_KEY:-dev-key-DO-NOT-USE-IN-PRODUCTION}" --name paop-container paop:dev >> $LOG_FILE 2>&1 &
    
    # Check if container is running
    sleep 2
    if docker ps | grep -q paop-container; then
        log_message "INFO" "Docker container is running"
        log_message "INFO" "API server accessible at: http://localhost:8000"
    else
        log_message "ERROR" "Failed to start Docker container"
        docker logs paop-container >> $LOG_FILE 2>&1
        exit 1
    fi
    
    log_message "INFO" "Press Ctrl+C to stop the container"
    
    # Set up trap to handle clean shutdown
    trap stop_docker INT
    
    # Wait for user to press Ctrl+C
    tail -f $LOG_FILE || true
}

# Function to stop Docker container
stop_docker() {
    log_message "INFO" "Stopping Docker container..."
    docker stop paop-container >> $LOG_FILE 2>&1
    log_message "INFO" "Docker container stopped"
    exit 0
}

# Function to run in local mode
run_local() {
    if [ "$VENV_AVAILABLE" != true ]; then
        log_message "WARN" "Python virtual environment not found, setting up..."
        ./build_all.sh
    fi
    
    log_message "INFO" "Running in local mode..."
    
    # Activate virtual environment
    log_message "INFO" "Activating virtual environment..."
    source .venv/bin/activate
    
    # Set environment variables
    export PYTHONPATH=$(pwd):$PYTHONPATH
    
    # Run the API server
    log_message "INFO" "Starting API server..."
    ./scripts/run_api.sh >> $LOG_FILE 2>&1 &
    API_PID=$!
    
    # Wait a moment for the API to start
    sleep 2
    
    # Check if the API server is running
    if kill -0 $API_PID 2>/dev/null; then
        log_message "INFO" "API server is running (PID: $API_PID)"
        log_message "INFO" "API server accessible at: http://localhost:8000"
    else
        log_message "ERROR" "Failed to start API server"
        exit 1
    fi
    
    log_message "INFO" "Press Ctrl+C to stop the API server"
    
    # Set up trap to handle clean shutdown
    trap stop_local INT
    
    # Wait for user to press Ctrl+C
    tail -f $LOG_FILE || true
}

# Function to stop local API server
stop_local() {
    log_message "INFO" "Stopping API server..."
    kill $API_PID 2>/dev/null || true
    log_message "INFO" "API server stopped"
    
    # Deactivate virtual environment
    deactivate 2>/dev/null || true
    
    exit 0
}

# Function to present menu and get user choice
show_menu() {
    echo -e "${BOLD}==================================================${NC}"
    echo -e "${BOLD}                    Run Options                    ${NC}"
    echo -e "${BOLD}==================================================${NC}"
    echo "1. Run locally (Python virtual environment)"
    echo "2. Run in Docker container"
    echo "3. Exit"
    echo
    
    read -p "Enter your choice (1-3): " choice
    
    case $choice in
        1)
            RUN_MODE="local"
            ;;
        2)
            RUN_MODE="docker"
            ;;
        3)
            log_message "INFO" "Exiting..."
            exit 0
            ;;
        *)
            log_message "ERROR" "Invalid choice"
            show_menu
            ;;
    esac
}

# Main execution flow
main() {
    # Check prerequisites
    check_prerequisites
    
    # Show menu and get run mode
    show_menu
    
    # Run based on chosen mode
    case $RUN_MODE in
        "local")
            run_local
            ;;
        "docker")
            run_docker
            ;;
    esac
}

# Run the main function
main