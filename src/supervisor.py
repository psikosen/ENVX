#!/usr/bin/env python
"""
Supervisor script for the Pedantic Agent Orchestration Platform (PAOP).

This script initializes and runs multiple PAOP agents in a single process
using threading or multiprocessing, based on a supervisor configuration file.
"""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import queue
import time
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any

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
logger = logging.getLogger("paop_supervisor")


class AgentSupervisor:
    """
    Supervisor for managing multiple agents in a single process.
    
    This class handles the initialization, monitoring, and lifecycle
    of multiple agents running in separate threads.
    """
    
    def __init__(self, config_path: str):
        """
        Initialize the supervisor with a configuration file.
        
        Args:
            config_path: Path to supervisor configuration file
        """
        self.config_path = config_path
        self.agents = {}  # agent_id -> (agent, thread)
        self.running = False
        self.load_config()
    
    def load_config(self):
        """Load supervisor configuration from file."""
        try:
            path = Path(self.config_path)
            if not path.exists():
                raise ConfigurationError(f"Supervisor config file not found: {path}")
            
            # Parse based on file extension
            content = path.read_text()
            if path.suffix.lower() in ('.yaml', '.yml'):
                try:
                    import yaml
                    self.config = yaml.safe_load(content)
                except ImportError:
                    logger.warning("PyYAML not installed. Falling back to JSON parsing.")
                    self.config = json.loads(content)
            elif path.suffix.lower() == '.json':
                self.config = json.loads(content)
            else:
                raise ConfigurationError(f"Unsupported config file format: {path.suffix}")
            
            # Basic validation
            if not isinstance(self.config, dict):
                raise ConfigurationError("Supervisor config must be a dictionary")
            
            if "agents" not in self.config or not isinstance(self.config["agents"], list):
                raise ConfigurationError("Supervisor config must contain an 'agents' list")
            
            # Extract global MCP config if present
            self.mcp_config_path = self.config.get("mcp_config_path", "/app/config/mcp_config.yml")
            
            logger.info(f"Loaded supervisor config with {len(self.config['agents'])} agents")
            
        except Exception as e:
            logger.error(f"Error loading supervisor config: {e}")
            raise
    
    def start_agent_thread(self, agent_config: Dict[str, Any]) -> threading.Thread:
        """
        Start an agent in a separate thread.
        
        Args:
            agent_config: Configuration for the agent
            
        Returns:
            Thread running the agent
        """
        agent_id = agent_config.get("agent_id")
        if not agent_id:
            raise ValueError("Agent config missing 'agent_id'")
        
        # Extract agent-specific settings
        role = agent_config.get("role", "worker")
        is_orchestrator = role == "orchestrator" or agent_config.get("is_orchestrator", False)
        agent_config_path = agent_config.get("config_path")
        
        # Load configurations
        try:
            agent_model_config, mcp_model_config = load_configurations(
                agent_config_path, self.mcp_config_path, agent_id
            )
            
            # Override with values from supervisor config
            agent_model_config.agent_id = agent_id
            agent_model_config.role = AgentRole.ORCHESTRATOR if is_orchestrator else AgentRole.WORKER
            agent_model_config.is_orchestrator = is_orchestrator
            if "name" in agent_config:
                agent_model_config.name = agent_config["name"]
            if "description" in agent_config:
                agent_model_config.description = agent_config["description"]
            
            # Create the agent
            if is_orchestrator:
                agent = OrchestratorAgent(agent_model_config, mcp_model_config)
                logger.info(f"Created orchestrator agent: {agent_id}")
            else:
                agent = Agent(agent_model_config, mcp_model_config)
                logger.info(f"Created worker agent: {agent_id}")
            
            # Store the agent
            self.agents[agent_id] = {
                "agent": agent,
                "config": agent_config,
                "thread": None,
            }
            
            # Set up task and response queues for agent communication
            from queue import Queue
            task_queue = Queue()
            response_queue = Queue()
            
            # Store queues with agent info for inter-agent communication
            self.agents[agent_id]["task_queue"] = task_queue
            self.agents[agent_id]["response_queue"] = response_queue
            
            # Create and start the agent thread
            def agent_thread_func():
                logger.info(f"Agent thread starting for {agent_id}")
                try:
                    # Set up agent specific logging
                    thread_logger = logging.getLogger(f"agent.{agent_id}")
                    
                    while self.running:
                        try:
                            # Check for incoming tasks (non-blocking)
                            try:
                                task = task_queue.get(block=True, timeout=0.5)
                                thread_logger.info(f"Received task {task.task_id}")
                                
                                # Process the task
                                response = agent.process_task(task)
                                thread_logger.info(f"Processed task {task.task_id} with status {response.status}")
                                
                                # Put response in response queue if task has a source agent
                                if task.source_agent_id and task.source_agent_id != agent_id:
                                    source_agent_info = self.agents.get(task.source_agent_id)
                                    if source_agent_info and "response_queue" in source_agent_info:
                                        source_agent_info["response_queue"].put(response)
                                        thread_logger.debug(
                                            f"Sent response for task {task.task_id} to source agent {task.source_agent_id}"
                                        )
                                
                                # Always mark task as complete in our own task queue
                                task_queue.task_done()
                                
                            except queue.Empty:
                                # No tasks available, just continue
                                pass
                            
                            # Update agent status in worker registry for orchestrators
                            if not agent.config.is_orchestrator:
                                for orchestrator_id in self.orchestrators:
                                    orchestrator = self.agents[orchestrator_id]["agent"]
                                    if agent_id in orchestrator.worker_agents:
                                        orchestrator.worker_agents[agent_id]["status"] = agent.status.value
                        
                        except Exception as task_error:
                            thread_logger.exception(f"Error processing task: {task_error}")
                            # Continue running despite errors in individual tasks
                    
                except Exception as e:
                    logger.exception(f"Fatal agent thread error for {agent_id}: {e}")
                
                logger.info(f"Agent thread stopping for {agent_id}")
            
            thread = threading.Thread(
                target=agent_thread_func,
                name=f"agent-{agent_id}",
                daemon=True,
            )
            self.agents[agent_id]["thread"] = thread
            
            return thread
            
        except Exception as e:
            logger.error(f"Error starting agent {agent_id}: {e}")
            raise
    
    def start(self):
        """Start all configured agents."""
        logger.info("Starting agent supervisor")
        self.running = True
        
        # Start all agents
        for agent_config in self.config["agents"]:
            try:
                thread = self.start_agent_thread(agent_config)
                thread.start()
            except Exception as e:
                logger.error(f"Failed to start agent: {e}")
        
        # Track orchestrators and workers for easy access
        self.orchestrators = [
            agent_id for agent_id, info in self.agents.items()
            if info["agent"].config.is_orchestrator
        ]
        
        self.workers = [
            agent_id for agent_id, info in self.agents.items()
            if not info["agent"].config.is_orchestrator
        ]
        
        # Register worker agents with orchestrator, including communication queues
        for orchestrator_id in self.orchestrators:
            orchestrator = self.agents[orchestrator_id]["agent"]
            for worker_id in self.workers:
                worker = self.agents[worker_id]["agent"]
                worker_info = {
                    "status": worker.status.value,
                    "role": worker.config.role.value,
                    "task_queue": self.agents[worker_id]["task_queue"],
                    "response_queue": self.agents[worker_id]["response_queue"],
                }
                orchestrator.register_worker(worker_id, worker_info)
                logger.info(f"Registered worker {worker_id} with orchestrator {orchestrator_id}")
        
        logger.info(f"Started {len(self.agents)} agents ({len(self.orchestrators)} orchestrators, {len(self.workers)} workers)")
    
    def stop(self):
        """Stop all running agents."""
        logger.info("Stopping agent supervisor")
        self.running = False
        
        # Wait for all threads to complete
        for agent_id, info in self.agents.items():
            thread = info["thread"]
            if thread and thread.is_alive():
                logger.info(f"Waiting for agent {agent_id} to stop")
                thread.join(timeout=5)
        
        logger.info("All agents stopped")
    
    def run(self):
        """Run the supervisor until interrupted."""
        try:
            self.start()
            
            # Keep supervisor alive until interrupted
            while self.running:
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Supervisor interrupted")
        finally:
            self.stop()


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Run a PAOP agent supervisor")
    
    parser.add_argument(
        "--config",
        help="Path to supervisor configuration file",
        default=os.environ.get("SUPERVISOR_CONFIG_PATH", "/app/config/supervisor.yml"),
    )
    
    parser.add_argument(
        "--log-level",
        help="Logging level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=os.environ.get("LOG_LEVEL", "INFO"),
    )
    
    return parser.parse_args()


def main():
    """Main entry point for the supervisor script."""
    args = parse_args()
    
    # Set log level
    log_level = getattr(logging, args.log_level)
    logging.getLogger().setLevel(log_level)
    
    try:
        supervisor = AgentSupervisor(args.config)
        supervisor.run()
    except Exception as e:
        logger.exception(f"Supervisor error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
