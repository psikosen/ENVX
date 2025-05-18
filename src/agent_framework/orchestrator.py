"""
Orchestrator implementation for PAOP.

This module provides the orchestrator that manages agents and processes commands.
"""
import logging
import asyncio
import uuid
from typing import Any, Dict, List, Optional, Union

from src.external_interface.models import (
    CommandType,
    CommandStatus,
    ExternalCommandRequest,
    ExternalCommandResponse,
    ExecuteTaskResponse,
    CreateAgentResponse,
)

logger = logging.getLogger(__name__)


class Orchestrator:
    """Orchestrator for managing agents and processing commands."""
    
    def __init__(self):
        """Initialize the orchestrator."""
        self.agents = {}
        self.tasks = {}
    
    async def process_command(self, command: ExternalCommandRequest) -> ExternalCommandResponse:
        """Process a command.
        
        Args:
            command: The command to process
            
        Returns:
            The response to the command
        """
        logger.info(f"Processing command: {command.command_type} (ID: {command.command_id})")
        
        if command.command_type == CommandType.EXECUTE_TASK:
            return await self._execute_task(command)
        elif command.command_type == CommandType.CANCEL_TASK:
            return await self._cancel_task(command)
        elif command.command_type == CommandType.GET_TASK_STATUS:
            return await self._get_task_status(command)
        elif command.command_type == CommandType.CREATE_AGENT:
            return await self._create_agent(command)
        elif command.command_type == CommandType.DELETE_AGENT:
            return await self._delete_agent(command)
        elif command.command_type == CommandType.LIST_AGENTS:
            return await self._list_agents(command)
        elif command.command_type == CommandType.GET_AGENT_STATUS:
            return await self._get_agent_status(command)
        elif command.command_type == CommandType.GET_SYSTEM_STATUS:
            return await self._get_system_status(command)
        elif command.command_type == CommandType.UPDATE_CONFIGURATION:
            return await self._update_configuration(command)
        else:
            logger.error(f"Unknown command type: {command.command_type}")
            return ExternalCommandResponse(
                command_id=command.command_id,
                status=CommandStatus.FAILURE,
                error=f"Unknown command type: {command.command_type}",
            )
    
    async def _execute_task(self, command: ExternalCommandRequest) -> ExecuteTaskResponse:
        """Execute a task on an agent."""
        agent_id = command.target_id
        if not agent_id or agent_id not in self.agents:
            return ExecuteTaskResponse(
                command_id=command.command_id,
                status=CommandStatus.FAILURE,
                error=f"Agent not found: {agent_id}",
                task_id=None,
            )
        
        # Create a task ID
        task_id = str(uuid.uuid4())
        
        # Add the task to the tasks dictionary
        self.tasks[task_id] = {
            "agent_id": agent_id,
            "status": "pending",
            "command": command,
        }
        
        # Create successful response
        return ExecuteTaskResponse(
            command_id=command.command_id,
            status=CommandStatus.SUCCESS,
            result={"message": f"Task created on agent {agent_id}", "task_id": task_id},
            task_id=task_id,
        )
    
    async def _cancel_task(self, command: ExternalCommandRequest) -> ExternalCommandResponse:
        """Cancel a task."""
        task_id = command.payload.get("task_id")
        if not task_id or task_id not in self.tasks:
            return ExternalCommandResponse(
                command_id=command.command_id,
                status=CommandStatus.FAILURE,
                error=f"Task not found: {task_id}",
            )
        
        # Update task status
        self.tasks[task_id]["status"] = "canceled"
        
        # Create successful response
        return ExternalCommandResponse(
            command_id=command.command_id,
            status=CommandStatus.SUCCESS,
            result={"message": f"Task {task_id} canceled"},
        )
    
    async def _get_task_status(self, command: ExternalCommandRequest) -> ExternalCommandResponse:
        """Get task status."""
        task_id = command.payload.get("task_id")
        if not task_id or task_id not in self.tasks:
            return ExternalCommandResponse(
                command_id=command.command_id,
                status=CommandStatus.FAILURE,
                error=f"Task not found: {task_id}",
            )
        
        # Create successful response
        return ExternalCommandResponse(
            command_id=command.command_id,
            status=CommandStatus.SUCCESS,
            result={"task_id": task_id, "status": self.tasks[task_id]["status"]},
        )
    
    async def _create_agent(self, command: ExternalCommandRequest) -> CreateAgentResponse:
        """Create a new agent."""
        agent_type = command.payload.get("agent_type")
        if not agent_type:
            return CreateAgentResponse(
                command_id=command.command_id,
                status=CommandStatus.FAILURE,
                error=f"Agent type is required",
                agent_id=None,
            )
        
        # Create an agent ID
        agent_id = str(uuid.uuid4())
        
        # Add the agent to the agents dictionary
        self.agents[agent_id] = {
            "type": agent_type,
            "status": "running",
            "config": command.payload,
        }
        
        # Create successful response
        return CreateAgentResponse(
            command_id=command.command_id,
            status=CommandStatus.SUCCESS,
            result={"message": f"Agent created with ID {agent_id}", "agent_id": agent_id},
            agent_id=agent_id,
        )
    
    async def _delete_agent(self, command: ExternalCommandRequest) -> ExternalCommandResponse:
        """Delete an agent."""
        agent_id = command.target_id
        if not agent_id or agent_id not in self.agents:
            return ExternalCommandResponse(
                command_id=command.command_id,
                status=CommandStatus.FAILURE,
                error=f"Agent not found: {agent_id}",
            )
        
        # Remove the agent from the agents dictionary
        del self.agents[agent_id]
        
        # Create successful response
        return ExternalCommandResponse(
            command_id=command.command_id,
            status=CommandStatus.SUCCESS,
            result={"message": f"Agent {agent_id} deleted"},
        )
    
    async def _list_agents(self, command: ExternalCommandRequest) -> ExternalCommandResponse:
        """List all agents."""
        # Create agent list
        agent_list = [
            {"id": agent_id, **agent_info}
            for agent_id, agent_info in self.agents.items()
        ]
        
        # Create successful response
        return ExternalCommandResponse(
            command_id=command.command_id,
            status=CommandStatus.SUCCESS,
            result={"agents": agent_list},
        )
    
    async def _get_agent_status(self, command: ExternalCommandRequest) -> ExternalCommandResponse:
        """Get agent status."""
        agent_id = command.target_id
        if not agent_id or agent_id not in self.agents:
            return ExternalCommandResponse(
                command_id=command.command_id,
                status=CommandStatus.FAILURE,
                error=f"Agent not found: {agent_id}",
            )
        
        # Create successful response
        return ExternalCommandResponse(
            command_id=command.command_id,
            status=CommandStatus.SUCCESS,
            result={"agent_id": agent_id, "status": self.agents[agent_id]},
        )
    
    async def _get_system_status(self, command: ExternalCommandRequest) -> ExternalCommandResponse:
        """Get system status."""
        # Create system status
        system_status = {
            "agents": len(self.agents),
            "tasks": len(self.tasks),
            "status": "running",
        }
        
        # Create successful response
        return ExternalCommandResponse(
            command_id=command.command_id,
            status=CommandStatus.SUCCESS,
            result=system_status,
        )
    
    async def _update_configuration(self, command: ExternalCommandRequest) -> ExternalCommandResponse:
        """Update configuration."""
        # In a real implementation, this would update the configuration
        
        # Create successful response
        return ExternalCommandResponse(
            command_id=command.command_id,
            status=CommandStatus.SUCCESS,
            result={"message": "Configuration updated"},
        )


# Singleton instance
_orchestrator = None


def get_orchestrator() -> Orchestrator:
    """Get the orchestrator singleton instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


async def process_command(command: ExternalCommandRequest) -> ExternalCommandResponse:
    """Process a command using the orchestrator singleton."""
    orchestrator = get_orchestrator()
    return await orchestrator.process_command(command)
