#!/bin/bash
# build_all.sh - Build script for the PAOP system

# Exit on error
set -e

# Set colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Set up logging
LOG_FILE="build_log.txt"
echo "=== PAOP System Build Log ($(date)) ===" > $LOG_FILE

# Display header
echo -e "${BOLD}==================================================${NC}"
echo -e "${BOLD}      Pedantic Agent Orchestration Platform       ${NC}"
echo -e "${BOLD}         Building and Setting Up System           ${NC}"
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
    
    # Check Python
    if ! command -v python3 &> /dev/null; then
        log_message "ERROR" "Python 3 is required but not installed"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 --version | cut -d ' ' -f 2)
    log_message "INFO" "Found Python version: $PYTHON_VERSION"
    
    # Check if pip is installed
    if ! command -v pip3 &> /dev/null; then
        log_message "ERROR" "pip3 is required but not installed"
        exit 1
    fi
    
    # Check for Docker (optional)
    if command -v docker &> /dev/null; then
        DOCKER_AVAILABLE=true
        DOCKER_VERSION=$(docker --version | cut -d ' ' -f 3 | tr -d ',')
        log_message "INFO" "Found Docker version: $DOCKER_VERSION"
    else
        DOCKER_AVAILABLE=false
        log_message "WARN" "Docker not found (optional - required for container deployment)"
    fi
    
    log_message "INFO" "Prerequisites check completed"
}

# Function to set up local environment
setup_local_environment() {
    log_message "INFO" "Setting up local environment..."
    
    # Make scripts executable
    log_message "INFO" "Making scripts executable..."
    chmod +x scripts/*.sh
    
    # Create Python virtual environment if it doesn't exist
    if [ ! -d ".venv" ]; then
        log_message "INFO" "Creating Python virtual environment..."
        python3 -m venv .venv
    else
        log_message "INFO" "Python virtual environment already exists"
    fi
    
    # Activate virtual environment
    log_message "INFO" "Activating virtual environment..."
    source .venv/bin/activate
    
    # Install dependencies
    log_message "INFO" "Installing dependencies..."
    pip install -r requirements.txt >> $LOG_FILE 2>&1
    
    # Install the package in development mode
    log_message "INFO" "Installing the package in development mode..."
    pip install -e . >> $LOG_FILE 2>&1
    
    log_message "INFO" "Local environment setup completed"
}

# Function to build Docker image
build_docker_image() {
    # Check if Docker is available
    if [ "$DOCKER_AVAILABLE" != true ]; then
        log_message "WARN" "Docker is not installed, skipping Docker image build"
        return
    fi
    
    log_message "INFO" "Building Docker image..."
    
    # Build Docker image
    docker build -t paop:dev . >> $LOG_FILE 2>&1
    
    log_message "INFO" "Docker image built successfully: paop:dev"
    log_message "INFO" "To run the Docker container, use: docker run -p 8000:8000 paop:dev"
}

# Function to run tests
run_tests() {
    log_message "INFO" "Running tests..."
    
    # Run unit tests if they exist
    if [ -d "tests/unit" ]; then
        log_message "INFO" "Running unit tests..."
        python -m pytest tests/unit -v >> $LOG_FILE 2>&1 || log_message "WARN" "Some unit tests failed (see log for details)"
    else
        log_message "INFO" "No unit tests found, skipping"
    fi
    
    log_message "INFO" "Tests completed"
}

# Main execution flow
main() {
    # Check prerequisites
    check_prerequisites
    
    # Set up local environment
    setup_local_environment
    
    # Build Docker image
    build_docker_image
    
    # Run tests
    run_tests
    
    # Final message
    log_message "INFO" "Build process completed successfully!"
    echo
    echo -e "${BOLD}==================================================${NC}"
    echo -e "${BOLD}                 Build Complete                   ${NC}"
    echo -e "${BOLD}==================================================${NC}"
    echo "To run the application locally:"
    echo "  1. Activate the virtual environment: source .venv/bin/activate"
    echo "  2. Run the API server: ./scripts/run_api.sh"
    echo
    echo "To run in Docker:"
    echo "  docker run -p 8000:8000 paop:dev"
    echo
    echo "The API will be available at: http://localhost:8000"
    echo -e "${BOLD}==================================================${NC}"
}

# Run the main function
main

# Deactivate virtual environment
deactivate 2>/dev/null || true