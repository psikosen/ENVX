#!/usr/bin/env python
"""
Main entry point for the Pedantic Agent Orchestration Platform (PAOP).

This script initializes and runs a PAOP agent based on provided configuration
and command-line arguments.
"""

import argparse
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

from src.agent.models import AgentRole
from src.agent.config import ConfigurationError, load_configurations
from src.agent.agent import Agent, OrchestratorAgent


# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger("paop")


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Run a PAOP agent")
    
    parser.add_argument(
        "--agent-config",
        help="Path to agent configuration file",
        default=os.environ.get("AGENT_CONFIG_PATH"),
    )
    
    parser.add_argument(
        "--mcp-config",
        help="Path to MCP configuration file",
        default=os.environ.get("MCP_CONFIG_PATH", "/app/config/mcp_config.yml"),
    )
    
    parser.add_argument(
        "--agent-id",
        help="Agent ID (overrides configuration)",
        default=os.environ.get("AGENT_ID"),
    )
    
    parser.add_argument(
        "--role",
        help="Agent role (worker or orchestrator)",
        choices=["worker", "orchestrator"],
        default=os.environ.get("AGENT_ROLE"),
    )
    
    parser.add_argument(
        "--log-level",
        help="Logging level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=os.environ.get("LOG_LEVEL", "INFO"),
    )
    
    return parser.parse_args()


def run_agent(args):
    """Initialize and run an agent with the provided configuration."""
    # Set log level
    log_level = getattr(logging, args.log_level)
    logging.getLogger().setLevel(log_level)
    
    logger.info(f"Starting PAOP agent with arguments: {args}")
    
    try:
        # Load configurations
        agent_config, mcp_config = load_configurations(
            args.agent_config, args.mcp_config, args.agent_id
        )
        
        # Override role if specified in command line
        if args.role:
            if args.role == "orchestrator":
                agent_config.role = AgentRole.ORCHESTRATOR
                agent_config.is_orchestrator = True
            elif args.role == "worker":
                agent_config.role = AgentRole.WORKER
                agent_config.is_orchestrator = False
        
        # Create the appropriate agent type
        if agent_config.is_orchestrator:
            agent = OrchestratorAgent(agent_config, mcp_config)
            logger.info(f"Created orchestrator agent: {agent_config.agent_id}")
        else:
            agent = Agent(agent_config, mcp_config)
            logger.info(f"Created worker agent: {agent_config.agent_id}")
        
        # In a real application, we would now start a main loop to:
        # 1. Listen for incoming tasks
        # 2. Process tasks using agent.process_task()
        # 3. Return responses
        #
        # For now, we'll just keep the agent alive and report its status
        
        logger.info(f"Agent {agent_config.agent_id} ready and waiting for tasks")
        logger.info(f"Agent status: {agent.get_status()}")
        
        # Keep agent alive (in a real application, this would be a proper event loop)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info(f"Agent {agent_config.agent_id} shutting down")
        
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Unhandled exception: {e}")
        sys.exit(1)


if __name__ == "__main__":
    args = parse_args()
    run_agent(args)
