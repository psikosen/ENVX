"""
Core agent implementation for the Pedantic Agent Orchestration Platform (PAOP).

This module provides the base Agent class that handles configuration, task processing,
and interaction with MCP and other tools.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import ValidationError

from .models import (
    AgentRole,
    AgentStatus,
    AgentConfig,
    MCPConfig,
    TaskDefinition,
    TaskResponse,
    TaskStatus,
    TaskType,
)
from .config import ConfigurationError, load_configurations
from .mcp_client import MCPClient, MCPException


logger = logging.getLogger(__name__)


class Agent:
    """
    Base Agent class for the PAOP system.
    
    This class provides the core functionality for all agents, including
    configuration loading, task processing, and tool interaction.
    """
    
    def __init__(
        self,
        agent_config: AgentConfig,
        mcp_config: MCPConfig,
    ):
        """
        Initialize an agent with the provided configurations.
        
        Args:
            agent_config: Configuration for this agent
            mcp_config: Configuration for MCP integration
        """
        self.config = agent_config
        self.mcp_config = mcp_config
        self.status = AgentStatus.INITIALIZING
        self.mcp_client = None
        
        # Initialize MCP client if enabled
        if self.mcp_config.enabled:
            try:
                self.mcp_client = MCPClient(self.mcp_config)
                logger.info(f"Agent {self.config.agent_id}: Initialized MCP client")
            except MCPException as e:
                logger.error(f"Agent {self.config.agent_id}: Failed to initialize MCP client: {e}")
                self.status = AgentStatus.ERROR
                return
        
        # Completed initialization
        self.status = AgentStatus.IDLE
        logger.info(
            f"Agent {self.config.agent_id} initialized "
            f"(role: {self.config.role}, orchestrator: {self.config.is_orchestrator})"
        )
    
    @classmethod
    def from_config_files(
        cls,
        agent_config_path: Optional[str] = None,
        mcp_config_path: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> "Agent":
        """
        Create an Agent instance from configuration files.
        
        Args:
            agent_config_path: Path to agent configuration file
            mcp_config_path: Path to MCP configuration file
            agent_id: Agent ID to use if not in config
            
        Returns:
            Agent instance
            
        Raises:
            ConfigurationError: If configuration loading fails
        """
        try:
            agent_config, mcp_config = load_configurations(
                agent_config_path, mcp_config_path, agent_id
            )
            return cls(agent_config, mcp_config)
        except ConfigurationError as e:
            logger.error(f"Failed to create agent from config files: {e}")
            raise
    
    def process_task(self, task: TaskDefinition) -> TaskResponse:
        """
        Process a task based on its type and payload.
        
        Args:
            task: The task to process
            
        Returns:
            TaskResponse with the result or error
        """
        if self.status in (AgentStatus.ERROR, AgentStatus.PROCESSING_TASK, AgentStatus.MCP_TOOL_BUSY):
            return TaskResponse(
                task_id=task.task_id,
                agent_id=self.config.agent_id,
                status=TaskStatus.FAILED,
                error_message=f"Agent is not available to process tasks (current status: {self.status})"
            )
        
        # Update agent status
        previous_status = self.status
        self.status = AgentStatus.PROCESSING_TASK
        
        # Record start time
        started_at = datetime.utcnow().isoformat()
        
        logger.info(f"Agent {self.config.agent_id}: Processing task {task.task_id} ({task.task_type})")
        
        try:
            # Route task to appropriate handler based on task_type
            if task.task_type == TaskType.MCP_COMMAND:
                response = self._process_mcp_task(task)
            elif task.task_type == TaskType.INTERNAL_PROCESS:
                response = self._process_internal_task(task)
            elif task.task_type == TaskType.STATUS_UPDATE:
                response = self._process_status_update_task(task)
            elif task.task_type == TaskType.CONFIGURATION_UPDATE:
                response = self._process_config_update_task(task)
            else:
                response = TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.FAILED,
                    error_message=f"Unsupported task type: {task.task_type}"
                )
            
            # Ensure agent_id is set correctly
            response.agent_id = self.config.agent_id
            
            # Set timing information if not already set
            if not response.started_at:
                response.started_at = started_at
            if not response.completed_at:
                response.completed_at = datetime.utcnow().isoformat()
            
            return response
            
        except Exception as e:
            logger.exception(f"Agent {self.config.agent_id}: Error processing task {task.task_id}: {e}")
            return TaskResponse(
                task_id=task.task_id,
                agent_id=self.config.agent_id,
                status=TaskStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.utcnow().isoformat(),
                error_message=f"Unhandled error: {str(e)}"
            )
        finally:
            # Restore previous status
            self.status = previous_status
    
    def _process_mcp_task(self, task: TaskDefinition) -> TaskResponse:
        """
        Process an MCP command task.
        
        Args:
            task: The MCP task to process
            
        Returns:
            TaskResponse with the result or error
        """
        if not self.mcp_client:
            return TaskResponse(
                task_id=task.task_id,
                agent_id=self.config.agent_id,
                status=TaskStatus.FAILED,
                error_message="MCP client is not initialized or disabled"
            )
        
        # Update status to indicate MCP tool is in use
        self.status = AgentStatus.MCP_TOOL_BUSY
        
        try:
            return self.mcp_client.process_task(task)
        finally:
            # Reset status when done
            self.status = AgentStatus.IDLE
    
    def _process_internal_task(self, task: TaskDefinition) -> TaskResponse:
        """
        Process an internal task that doesn't require external tools.
        
        Args:
            task: The internal task to process
            
        Returns:
            TaskResponse with the result or error
        """
        logger.info(f"Processing internal task {task.task_id} with payload: {task.payload}")
        
        try:
            # Extract operation type from payload
            operation = task.payload.get("operation")
            if not operation:
                return TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.FAILED,
                    error_message="Missing 'operation' in internal task payload"
                )
            
            # Route to specific internal operation handlers
            if operation == "echo":
                # Simple echo operation for testing
                return TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.COMPLETED,
                    result_payload={"echo": task.payload.get("data")}
                )
            elif operation == "validate_data":
                # Validate data structure
                data = task.payload.get("data")
                if not data:
                    return TaskResponse(
                        task_id=task.task_id,
                        agent_id=self.config.agent_id,
                        status=TaskStatus.FAILED,
                        error_message="Missing 'data' for validation operation"
                    )
                
                # Perform validation (example implementation)
                validation_errors = []
                required_fields = task.payload.get("required_fields", [])
                
                for field in required_fields:
                    if field not in data or data[field] is None:
                        validation_errors.append(f"Missing required field: {field}")
                
                if validation_errors:
                    return TaskResponse(
                        task_id=task.task_id,
                        agent_id=self.config.agent_id,
                        status=TaskStatus.FAILED,
                        error_message="Validation failed",
                        result_payload={"validation_errors": validation_errors}
                    )
                
                return TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.COMPLETED,
                    result_payload={"validation": "success"}
                )
            elif operation == "transform_data":
                # Transform data structure
                data = task.payload.get("data")
                transform_type = task.payload.get("transform_type")
                
                if not data:
                    return TaskResponse(
                        task_id=task.task_id,
                        agent_id=self.config.agent_id,
                        status=TaskStatus.FAILED,
                        error_message="Missing 'data' for transform operation"
                    )
                
                if not transform_type:
                    return TaskResponse(
                        task_id=task.task_id,
                        agent_id=self.config.agent_id,
                        status=TaskStatus.FAILED,
                        error_message="Missing 'transform_type' for transform operation"
                    )
                
                # Perform transformation
                transformed_data = {}
                
                if transform_type == "uppercase_keys":
                    transformed_data = {k.upper(): v for k, v in data.items()}
                elif transform_type == "lowercase_keys":
                    transformed_data = {k.lower(): v for k, v in data.items()}
                elif transform_type == "flatten":
                    # Basic flattening of nested dictionaries
                    def flatten_dict(d, parent_key=""):
                        items = []
                        for k, v in d.items():
                            new_key = f"{parent_key}.{k}" if parent_key else k
                            if isinstance(v, dict):
                                items.extend(flatten_dict(v, new_key).items())
                            else:
                                items.append((new_key, v))
                        return dict(items)
                    
                    transformed_data = flatten_dict(data)
                else:
                    return TaskResponse(
                        task_id=task.task_id,
                        agent_id=self.config.agent_id,
                        status=TaskStatus.FAILED,
                        error_message=f"Unsupported transform type: {transform_type}"
                    )
                
                return TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.COMPLETED,
                    result_payload={"transformed_data": transformed_data}
                )
            else:
                return TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.FAILED,
                    error_message=f"Unsupported internal operation: {operation}"
                )
                
        except Exception as e:
            logger.exception(f"Error processing internal task: {e}")
            return TaskResponse(
                task_id=task.task_id,
                agent_id=self.config.agent_id,
                status=TaskStatus.FAILED,
                error_message=f"Internal processing error: {str(e)}"
            )
    
    def _process_status_update_task(self, task: TaskDefinition) -> TaskResponse:
        """
        Process a status update task.
        
        Args:
            task: The status update task
            
        Returns:
            TaskResponse with the result or error
        """
        try:
            new_status = task.payload.get("status")
            if not new_status:
                return TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.FAILED,
                    error_message="Missing 'status' in payload"
                )
            
            # Validate and update status
            try:
                self.status = AgentStatus(new_status)
            except ValueError:
                return TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.FAILED,
                    error_message=f"Invalid status value: {new_status}"
                )
            
            return TaskResponse(
                task_id=task.task_id,
                agent_id=self.config.agent_id,
                status=TaskStatus.COMPLETED,
                result_payload={"status": self.status.value}
            )
            
        except Exception as e:
            return TaskResponse(
                task_id=task.task_id,
                agent_id=self.config.agent_id,
                status=TaskStatus.FAILED,
                error_message=f"Error updating status: {str(e)}"
            )
    
    def _process_config_update_task(self, task: TaskDefinition) -> TaskResponse:
        """
        Process a configuration update task.
        
        Args:
            task: The configuration update task
            
        Returns:
            TaskResponse with the result or error
        """
        logger.info(f"Processing configuration update task {task.task_id}")
        
        try:
            # Extract config updates from payload
            updates = task.payload.get("updates")
            if not updates or not isinstance(updates, dict):
                return TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.FAILED,
                    error_message="Missing or invalid 'updates' in configuration update payload"
                )
            
            # Track applied and rejected updates
            applied_updates = []
            rejected_updates = []
            
            # Process MCP config updates
            mcp_updates = updates.get("mcp", {})
            for key, value in mcp_updates.items():
                # Check if the field is allowed to be updated at runtime
                if key in ("enabled", "timeout_seconds", "retry_count", "retry_delay_seconds"):
                    try:
                        # Update the config field
                        setattr(self.mcp_config, key, value)
                        applied_updates.append({"target": "mcp", "field": key, "value": value})
                        logger.info(f"Updated MCP config {key} to {value}")
                    except ValidationError as ve:
                        rejected_updates.append({
                            "target": "mcp", 
                            "field": key, 
                            "value": value,
                            "reason": str(ve)
                        })
                else:
                    rejected_updates.append({
                        "target": "mcp", 
                        "field": key, 
                        "value": value,
                        "reason": "Field cannot be updated at runtime"
                    })
            
            # Process agent config updates
            agent_updates = updates.get("agent", {})
            for key, value in agent_updates.items():
                # Check if the field is allowed to be updated at runtime
                if key in ("name", "description"):
                    try:
                        # Update the config field
                        setattr(self.config, key, value)
                        applied_updates.append({"target": "agent", "field": key, "value": value})
                        logger.info(f"Updated agent config {key} to {value}")
                    except ValidationError as ve:
                        rejected_updates.append({
                            "target": "agent", 
                            "field": key, 
                            "value": value,
                            "reason": str(ve)
                        })
                else:
                    rejected_updates.append({
                        "target": "agent", 
                        "field": key, 
                        "value": value,
                        "reason": "Field cannot be updated at runtime"
                    })
            
            # If MCP config changed significantly, reinitialize the client
            if any(update["target"] == "mcp" and update["field"] == "enabled" for update in applied_updates):
                try:
                    if self.mcp_config.enabled:
                        # Re-initialize MCP client
                        self.mcp_client = MCPClient(self.mcp_config)
                        logger.info(f"Reinitialized MCP client after config update")
                    else:
                        # Disable MCP client
                        self.mcp_client = None
                        logger.info(f"Disabled MCP client after config update")
                except MCPException as e:
                    return TaskResponse(
                        task_id=task.task_id,
                        agent_id=self.config.agent_id,
                        status=TaskStatus.FAILED,
                        error_message=f"Failed to reinitialize MCP client: {str(e)}",
                        result_payload={
                            "applied_updates": applied_updates,
                            "rejected_updates": rejected_updates
                        }
                    )
            
            # Construct response based on update results
            if rejected_updates and not applied_updates:
                return TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.FAILED,
                    error_message="All configuration updates were rejected",
                    result_payload={
                        "rejected_updates": rejected_updates
                    }
                )
            elif rejected_updates:
                # Partial success
                return TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.COMPLETED,
                    result_payload={
                        "message": "Some configuration updates were applied, others rejected",
                        "applied_updates": applied_updates,
                        "rejected_updates": rejected_updates
                    }
                )
            else:
                # Complete success
                return TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.COMPLETED,
                    result_payload={
                        "message": "All configuration updates were applied successfully",
                        "applied_updates": applied_updates
                    }
                )
                
        except Exception as e:
            logger.exception(f"Error processing configuration update: {e}")
            return TaskResponse(
                task_id=task.task_id,
                agent_id=self.config.agent_id,
                status=TaskStatus.FAILED,
                error_message=f"Configuration update error: {str(e)}"
            )
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the agent.
        
        Returns:
            Dictionary containing agent status information
        """
        return {
            "agent_id": self.config.agent_id,
            "status": self.status.value,
            "role": self.config.role.value,
            "is_orchestrator": self.config.is_orchestrator,
            "mcp_enabled": self.mcp_config.enabled and self.mcp_client is not None,
        }


class OrchestratorAgent(Agent):
    """
    Orchestrator Agent for the PAOP system.
    
    This agent coordinates the work of other agents, delegating tasks and
    aggregating results.
    """
    
    def __init__(
        self,
        agent_config: AgentConfig,
        mcp_config: MCPConfig,
    ):
        """
        Initialize an orchestrator agent.
        
        Args:
            agent_config: Configuration for this agent
            mcp_config: Configuration for MCP integration
        """
        # Ensure configuration has orchestrator role
        if agent_config.role != AgentRole.ORCHESTRATOR:
            agent_config.role = AgentRole.ORCHESTRATOR
            agent_config.is_orchestrator = True
            logger.warning(f"Agent {agent_config.agent_id}: Forcing role to ORCHESTRATOR")
        
        super().__init__(agent_config, mcp_config)
        
        # Worker agent registry (would be populated from configuration or discovery)
        self.worker_agents: Dict[str, Dict[str, Any]] = {}
        
        logger.info(f"Orchestrator {self.config.agent_id} initialized")
    
    def register_worker(self, worker_id: str, worker_info: Dict[str, Any]) -> None:
        """
        Register a worker agent with this orchestrator.
        
        Args:
            worker_id: ID of the worker agent
            worker_info: Information about the worker agent
        """
        self.worker_agents[worker_id] = worker_info
        logger.info(f"Orchestrator {self.config.agent_id}: Registered worker {worker_id}")
    
    def unregister_worker(self, worker_id: str) -> None:
        """
        Unregister a worker agent from this orchestrator.
        
        Args:
            worker_id: ID of the worker agent to unregister
        """
        if worker_id in self.worker_agents:
            del self.worker_agents[worker_id]
            logger.info(f"Orchestrator {self.config.agent_id}: Unregistered worker {worker_id}")
    
    def get_worker_status(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the status of a registered worker agent.
        
        Args:
            worker_id: ID of the worker agent
            
        Returns:
            Worker status information or None if not registered
        """
        return self.worker_agents.get(worker_id)
    
    def list_workers(self) -> List[Dict[str, Any]]:
        """
        Get a list of all registered worker agents.
        
        Returns:
            List of worker agent information
        """
        return [
            {"worker_id": worker_id, **worker_info}
            for worker_id, worker_info in self.worker_agents.items()
        ]
    
    def delegate_task(self, task: TaskDefinition, worker_id: Optional[str] = None) -> TaskResponse:
        """
        Delegate a task to a worker agent.
        
        Args:
            task: The task to delegate
            worker_id: Specific worker to delegate to, or None to auto-select
            
        Returns:
            TaskResponse from the worker agent or error
        """
        logger.info(f"Delegating task {task.task_id} to worker")
        
        # Auto-select worker if not specified using load-balancing
        if not worker_id:
            if not self.worker_agents:
                return TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.FAILED,
                    error_message="No worker agents registered"
                )
            
            # Select worker based on status (prefer IDLE workers)
            idle_workers = [
                wid for wid, info in self.worker_agents.items() 
                if info.get("status") == AgentStatus.IDLE.value
            ]
            
            if idle_workers:
                # If idle workers are available, choose one randomly for load distribution
                import random
                worker_id = random.choice(idle_workers)
                logger.debug(f"Selected idle worker {worker_id} from {len(idle_workers)} available")
            else:
                # Fall back to any available worker
                worker_id = next(iter(self.worker_agents.keys()))
                logger.debug(f"No idle workers available, selected {worker_id}")
        
        # Check if worker exists
        if worker_id not in self.worker_agents:
            return TaskResponse(
                task_id=task.task_id,
                agent_id=self.config.agent_id,
                status=TaskStatus.FAILED,
                error_message=f"Worker agent not found: {worker_id}"
            )
        
        try:
            # Mark the source of the task
            if not task.source_agent_id:
                task.source_agent_id = self.config.agent_id
            
            # Ensure the task has the target agent set
            task.target_agent_id = worker_id
            
            # In this production implementation, we're using a shared task queue mechanism
            # to communicate between agents running in the same container
            # This implementation uses inter-thread communication via a queue
            from queue import Queue
            
            # Check if the worker has a task queue
            if "task_queue" not in self.worker_agents[worker_id]:
                # This is a serious architectural issue - workers should have been registered with their queues
                return TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.FAILED,
                    error_message=f"Worker {worker_id} has no task queue registered"
                )
            
            # Get worker's task queue and response queue
            task_queue = self.worker_agents[worker_id]["task_queue"]
            response_queue = self.worker_agents[worker_id].get("response_queue")
            
            if not isinstance(task_queue, Queue):
                return TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.FAILED,
                    error_message=f"Worker {worker_id} has invalid task queue"
                )
            
            # Create timeout based on task specification or default
            timeout = task.timeout_seconds if task.timeout_seconds else 60
            
            # Send task to worker's queue
            logger.debug(f"Sending task {task.task_id} to worker {worker_id}")
            task_queue.put(task)
            
            # If worker is configured for asynchronous processing, return immediately
            if not response_queue or self.worker_agents[worker_id].get("async_mode", False):
                return TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.PENDING,
                    started_at=datetime.utcnow().isoformat(),
                    result_payload={
                        "message": f"Task submitted to worker {worker_id} for asynchronous processing",
                        "worker_id": worker_id,
                    }
                )
            
            # For synchronous processing, wait for response from worker
            try:
                logger.debug(f"Waiting for response to task {task.task_id} from worker {worker_id}")
                response = response_queue.get(timeout=timeout)
                logger.debug(f"Received response for task {task.task_id} from worker {worker_id}")
                
                # Ensure the response has the correct orchestrator metadata
                if isinstance(response, TaskResponse):
                    if not response.result_payload:
                        response.result_payload = {}
                    response.result_payload["orchestrator_id"] = self.config.agent_id
                    return response
                else:
                    return TaskResponse(
                        task_id=task.task_id,
                        agent_id=self.config.agent_id,
                        status=TaskStatus.FAILED,
                        error_message=f"Received invalid response type from worker {worker_id}"
                    )
                    
            except Exception as e:
                # Timeout or other error waiting for response
                logger.error(f"Error receiving response from worker {worker_id}: {e}")
                return TaskResponse(
                    task_id=task.task_id,
                    agent_id=self.config.agent_id,
                    status=TaskStatus.FAILED,
                    error_message=f"Failed to get response from worker {worker_id}: {str(e)}"
                )
        
        except Exception as e:
            logger.exception(f"Error delegating task to worker {worker_id}: {e}")
            return TaskResponse(
                task_id=task.task_id,
                agent_id=self.config.agent_id,
                status=TaskStatus.FAILED,
                error_message=f"Error delegating task: {str(e)}"
            )
    
    def process_task(self, task: TaskDefinition) -> TaskResponse:
        """
        Process a task, either directly or by delegating to a worker.
        
        Overrides the base Agent process_task method to add orchestration logic.
        
        Args:
            task: The task to process
            
        Returns:
            TaskResponse with the result or error
        """
        # If the task specifies a target agent other than this orchestrator,
        # delegate it to that agent
        if (
            task.target_agent_id and
            task.target_agent_id != self.config.agent_id and
            task.target_agent_id in self.worker_agents
        ):
            logger.info(
                f"Orchestrator {self.config.agent_id}: "
                f"Delegating task {task.task_id} to worker {task.target_agent_id}"
            )
            return self.delegate_task(task, task.target_agent_id)
        
        # Handle orchestrator-specific task types
        # (placeholder for future implementation)
        
        # Default to base agent behavior for other tasks
        return super().process_task(task)
