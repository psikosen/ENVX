"""
Core Pydantic models for the Pedantic Agent Orchestration Platform (PAOP).

These models define the data structures used by agents for configuration, 
task processing, and MCP tool interaction.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, validator


class AgentRole(str, Enum):
    """Defined roles for agents in the PAOP system."""
    
    ORCHESTRATOR = "orchestrator"
    WORKER = "worker"


class AgentStatus(str, Enum):
    """Possible status values for an agent."""
    
    INITIALIZING = "initializing"
    IDLE = "idle"
    PROCESSING_TASK = "processing_task"
    ERROR = "error"
    MCP_TOOL_BUSY = "mcp_tool_busy"


class ToolConfig(BaseModel):
    """Configuration for a specific tool that an agent can use."""
    
    tool_id: str = Field(..., description="Unique identifier for the tool")
    tool_type: str = Field(..., description="Type of tool (e.g., 'mcp', 'api')")
    enabled: bool = Field(True, description="Whether this tool is enabled for the agent")
    config: Dict[str, Any] = Field(default_factory=dict, description="Tool-specific configuration")


class AgentConfig(BaseModel):
    """Configuration for an individual agent."""
    
    agent_id: str = Field(..., description="Unique identifier for the agent")
    role: AgentRole = Field(AgentRole.WORKER, description="Role of this agent in the system")
    is_orchestrator: bool = Field(False, description="Whether this agent acts as an orchestrator")
    name: Optional[str] = Field(None, description="Human-readable name for the agent")
    description: Optional[str] = Field(None, description="Description of the agent's purpose")
    tools: List[ToolConfig] = Field(default_factory=list, description="Tools this agent can access")
    
    @validator('is_orchestrator', always=True)
    def validate_orchestrator_role(cls, v, values):
        """Ensure is_orchestrator and role are consistent."""
        if v and values.get('role') != AgentRole.ORCHESTRATOR:
            raise ValueError("If is_orchestrator is True, role must be ORCHESTRATOR")
        if values.get('role') == AgentRole.ORCHESTRATOR and not v:
            return True  # Auto-correct is_orchestrator to match role
        return v


class MCPConfig(BaseModel):
    """Configuration for MCP (DesktopCommanderMCP) integration."""
    
    enabled: bool = Field(True, description="Whether MCP integration is enabled")
    executable_path: Optional[str] = Field(None, description="Path to MCP executable")
    config_path: Optional[str] = Field(None, description="Path to MCP configuration directory")
    timeout_seconds: int = Field(30, description="Timeout for MCP operations in seconds")
    retry_count: int = Field(3, description="Number of retries for failed MCP operations")
    retry_delay_seconds: int = Field(2, description="Delay between retries in seconds")
    environment_variables: Dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables to set when calling MCP"
    )
    api_key: Optional[str] = Field(None, description="API key for MCP (if required)")
    
    @validator('timeout_seconds')
    def validate_timeout(cls, v):
        """Validate timeout is within reasonable bounds."""
        if v < 1:
            raise ValueError("timeout_seconds must be at least 1")
        if v > 300:
            raise ValueError("timeout_seconds should not exceed 300 (5 minutes)")
        return v


class TaskType(str, Enum):
    """Types of tasks that agents can process."""
    
    MCP_COMMAND = "mcp_command"  # Execute a command via MCP
    INTERNAL_PROCESS = "internal_process"  # Process data internally
    STATUS_UPDATE = "status_update"  # Update agent status
    CONFIGURATION_UPDATE = "configuration_update"  # Update agent configuration
    LLM_REQUEST = "llm_request"  # Request to an LLM provider


class TaskStatus(str, Enum):
    """Status of task execution."""
    
    PENDING = "pending"  # Task has been received but not yet started
    IN_PROGRESS = "in_progress"  # Task is currently being processed
    COMPLETED = "completed"  # Task has completed successfully
    FAILED = "failed"  # Task has failed
    CANCELED = "canceled"  # Task was canceled before completion


class TaskDefinition(BaseModel):
    """Definition of a task to be processed by an agent."""
    
    task_id: str = Field(..., description="Unique identifier for the task")
    task_type: TaskType = Field(..., description="Type of task to execute")
    created_at: Optional[str] = Field(None, description="ISO timestamp when task was created")
    source_agent_id: Optional[str] = Field(None, description="ID of agent that created the task")
    target_agent_id: Optional[str] = Field(None, description="ID of agent that should process the task")
    priority: int = Field(0, description="Priority level (higher means more important)")
    payload: Dict[str, Any] = Field(..., description="Task-specific parameters and data")
    timeout_seconds: Optional[int] = Field(None, description="Task timeout in seconds (if applicable)")


class TaskResponse(BaseModel):
    """Response from an agent after processing a task."""
    
    task_id: str = Field(..., description="ID of the task being responded to")
    agent_id: str = Field(..., description="ID of the agent that processed the task")
    status: TaskStatus = Field(..., description="Final status of the task")
    started_at: Optional[str] = Field(None, description="ISO timestamp when processing started")
    completed_at: Optional[str] = Field(None, description="ISO timestamp when processing completed")
    result_payload: Optional[Dict[str, Any]] = Field(None, description="Task-specific result data")
    error_message: Optional[str] = Field(None, description="Error message if task failed")
    
    @validator('error_message')
    def validate_error_with_status(cls, v, values):
        """Validate that error_message is provided for failed tasks and not for successful ones."""
        if values.get('status') == TaskStatus.FAILED and v is None:
            raise ValueError("error_message is required when status is 'failed'")
        if values.get('status') == TaskStatus.COMPLETED and v is not None:
            raise ValueError("error_message should not be set when status is 'completed'")
        return v
