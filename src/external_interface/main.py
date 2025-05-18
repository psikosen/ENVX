"""
Entry point for the PAOP external interface API.

This module provides a main function to run the FastAPI server with proper
configuration and logging.
"""
import os
import sys
import logging
import argparse
import json
import signal
import socket
import uuid
import time
from typing import Optional, Dict, Any

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from src.external_interface.config import load_api_config
from src.external_interface.api import app


# Configure structlog
def configure_structured_logging(log_level: str):
    """Configure structured logging with structlog.
    
    Args:
        log_level: Logging level (DEBUG, INFO, etc.)
    """
    # Set up structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Set up stdlib logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level),
    )
    
    # Set specific logger levels
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    
    # Create a structured logger
    logger = structlog.get_logger(__name__)
    logger.info("Logging configured", level=log_level)


def configure_app(app: FastAPI, config: Dict[str, Any]):
    """Configure the FastAPI application with middleware.
    
    Args:
        app: FastAPI application
        config: API configuration
    """
    # Configure CORS
    if config.get("cors_origins"):
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config["cors_origins"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    
    # Configure trusted hosts if specified
    if config.get("trusted_hosts"):
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=config["trusted_hosts"],
        )
    
    # Add GZip compression
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    
    # Add request ID middleware
    @app.middleware("http")
    async def add_request_id(request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def get_host_info():
    """Get information about the host."""
    hostname = socket.gethostname()
    try:
        ip_address = socket.gethostbyname(hostname)
    except socket.gaierror:
        ip_address = "unknown"
    
    return {
        "hostname": hostname,
        "ip_address": ip_address,
        "pid": os.getpid(),
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def handle_signals():
    """Set up signal handlers."""
    logger = structlog.get_logger(__name__)
    
    def handle_term(signum, frame):
        logger.info("Received termination signal", signal=signum)
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, handle_term)
    signal.signal(signal.SIGINT, handle_term)


def main():
    """Run the FastAPI server."""
    parser = argparse.ArgumentParser(description="PAOP External Interface API")
    parser.add_argument("--config", help="Path to configuration file")
    parser.add_argument("--log-level", help="Logging level (DEBUG, INFO, etc.)")
    parser.add_argument("--host", help="Host to bind to")
    parser.add_argument("--port", type=int, help="Port to bind to")
    args = parser.parse_args()
    
    try:
        # Load configuration
        config = load_api_config(args.config)
        
        # Override configuration with command line arguments
        if args.log_level:
            config.log_level = args.log_level
        if args.host:
            config.host = args.host
        if args.port:
            config.port = args.port
        
        # Configure logging
        configure_structured_logging(config.log_level)
        logger = structlog.get_logger(__name__)
        
        # Set up signal handlers
        handle_signals()
        
        # Log host information
        host_info = get_host_info()
        logger.info("Starting PAOP API server", **host_info)
        
        # Log configuration (excluding sensitive data)
        log_config = config.dict()
        log_config["api_key"] = "REDACTED"
        logger.info("Configuration loaded", **log_config)
        
        # Configure app middleware
        configure_app(app, log_config)
        
        # Run the server
        logger.info(f"Starting server on {config.host}:{config.port}")
        uvicorn.run(
            "src.external_interface.api:app",
            host=config.host,
            port=config.port,
            reload=os.environ.get("PAOP_RELOAD", "false").lower() == "true",
            log_level=config.log_level.lower(),
            log_config=None,  # Disable uvicorn's own logging configuration
            limit_concurrency=config.max_connections if hasattr(config, "max_connections") else None,
            timeout_keep_alive=30,
        )
    
    except Exception as e:
        logging.error(f"Error starting API server: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
