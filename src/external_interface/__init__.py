"""
External interface package for the Pedantic Agent Orchestration Platform (PAOP).

This package provides the external command/control interface for interacting with 
PAOP agents and orchestrator from outside the container.
"""

from .models import (
    CommandType,
    CommandStatus,
    ExternalCommandRequest,
    ExternalCommandResponse,
    ExecuteTaskRequest,
    ExecuteTaskResponse,
    CreateAgentRequest,
    CreateAgentResponse,
)

__all__ = [
    "CommandType",
    "CommandStatus",
    "ExternalCommandRequest",
    "ExternalCommandResponse",
    "ExecuteTaskRequest",
    "ExecuteTaskResponse",
    "CreateAgentRequest",
    "CreateAgentResponse",
]
