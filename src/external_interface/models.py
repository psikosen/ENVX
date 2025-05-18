"""
External command models for the Pedantic Agent Orchestration Platform (PAOP).

These Pydantic models define the interface for external commands sent to the PAOP
and the responses returned to clients.
"""
from typing import Any, Dict, List, Optional, Union, Literal
from enum import Enum
from pydantic import BaseModel, Field, validator


class CommandType(str, Enum):
    """Types of commands that can be sent to agents or the orchestrator."""
    
    # Agent task commands
    EXECUTE_TASK = "execute_task"
    CANCEL_TASK = "cancel_task"
    GET_TASK_STATUS = "get_task_status"
    
    # Orchestrator commands
    CREATE_AGENT = "create_agent"
    DELETE_AGENT = "delete_agent"
    LIST_AGENTS = "list_agents"
    GET_AGENT_STATUS = "get_agent_status"
    
    # System commands
    GET_SYSTEM_STATUS = "get_system_status"
    UPDATE_CONFIGURATION = "update_configuration"


class CommandStatus(str, Enum):
    """Status of command execution."""
    
    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    CANCELED = "canceled"


class ExternalCommandRequest(BaseModel):
    """Base model for external command requests."""
    
    command_id: str = Field(..., description="Unique identifier for the command")
    command_type: CommandType = Field(..., description="Type of command to execute")
    target_id: Optional[str] = Field(None, description="ID of the target agent or 'orchestrator'")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Command-specific parameters")
    
    @validator('target_id', pre=True)
    def validate_target_id(cls, v, values):
        """Validate that target_id is provided for agent-specific commands."""
        if v is None and values.get('command_type') not in [
            CommandType.GET_SYSTEM_STATUS, 
            CommandType.LIST_AGENTS,
            CommandType.CREATE_AGENT
        ]:
            raise ValueError(f"target_id is required for command type: {values.get('command_type')}")
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "command_id": "cmd-12345",
                "command_type": "get_system_status",
                "target_id": None,
                "payload": {}
            }
        }


class ExternalCommandResponse(BaseModel):
    """Base model for external command responses."""
    
    command_id: str = Field(..., description="ID of the command being responded to")
    status: CommandStatus = Field(..., description="Status of the command execution")
    result: Optional[Dict[str, Any]] = Field(None, description="Command-specific result data")
    error: Optional[str] = Field(None, description="Error message if command failed")
    
    @validator('error')
    def validate_error_with_status(cls, v, values):
        """Validate that error is provided for failed commands and not for successful ones."""
        if values.get('status') == CommandStatus.FAILURE and v is None:
            raise ValueError("Error message is required when status is 'failure'")
        if values.get('status') == CommandStatus.SUCCESS and v is not None:
            raise ValueError("Error message should not be set when status is 'success'")
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "command_id": "cmd-12345",
                "status": "success",
                "result": {"message": "Command executed successfully"},
                "error": None
            }
        }


# More specific command request/response models can be defined here
# These would inherit from the base models above and add command-specific fields

class ExecuteTaskRequest(ExternalCommandRequest):
    """Request to execute a specific task on an agent."""
    
    command_type: Literal[CommandType.EXECUTE_TASK] = Field(CommandType.EXECUTE_TASK)
    payload: Dict[str, Any] = Field(..., description="Task definition and parameters")
    
    @validator('payload')
    def validate_payload(cls, v):
        """Validate that the payload contains the necessary fields for a task."""
        if 'task_type' not in v:
            raise ValueError("payload must contain 'task_type'")
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "command_id": "task-12345",
                "command_type": "execute_task",
                "target_id": "agent-67890",
                "payload": {
                    "task_type": "process_data",
                    "input_data": "sample data",
                    "parameters": {
                        "param1": "value1",
                        "param2": 42
                    }
                }
            }
        }


class ExecuteTaskResponse(ExternalCommandResponse):
    """Response from an agent after attempting to execute a task."""
    
    result: Optional[Dict[str, Any]] = Field(None, description="Task execution results")
    task_id: Optional[str] = Field(None, description="ID of the created task")
    
    class Config:
        schema_extra = {
            "example": {
                "command_id": "task-12345",
                "status": "success",
                "result": {
                    "message": "Task created on agent agent-67890",
                    "task_id": "task-67890"
                },
                "error": None,
                "task_id": "task-67890"
            }
        }


class CreateAgentRequest(ExternalCommandRequest):
    """Request to create a new agent."""
    
    command_type: Literal[CommandType.CREATE_AGENT] = Field(CommandType.CREATE_AGENT)
    payload: Dict[str, Any] = Field(..., description="Agent configuration")
    
    @validator('payload')
    def validate_payload(cls, v):
        """Validate that the payload contains the necessary fields for agent creation."""
        if 'agent_type' not in v:
            raise ValueError("payload must contain 'agent_type'")
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "command_id": "cmd-12345",
                "command_type": "create_agent",
                "target_id": None,
                "payload": {
                    "agent_type": "data_processor",
                    "name": "DataProcessorAgent1",
                    "capabilities": ["process_csv", "transform_json"],
                    "config": {
                        "max_memory": "2GB",
                        "timeout": 300
                    }
                }
            }
        }


class CreateAgentResponse(ExternalCommandResponse):
    """Response after attempting to create a new agent."""
    
    result: Optional[Dict[str, Any]] = Field(None, description="Agent creation results")
    agent_id: Optional[str] = Field(None, description="ID of the created agent")
    
    class Config:
        schema_extra = {
            "example": {
                "command_id": "cmd-12345",
                "status": "success",
                "result": {
                    "message": "Agent created with ID agent-67890",
                    "agent_id": "agent-67890"
                },
                "error": None,
                "agent_id": "agent-67890"
            }
        }
