"""
Agent package for the Pedantic Agent Orchestration Platform (PAOP).

This package provides the core agent implementation, including configuration
management, task processing, and MCP tool integration.
"""

from .models import (
    AgentRole,
    AgentStatus,
    ToolConfig,
    AgentConfig,
    MCPConfig,
    TaskType,
    TaskStatus,
    TaskDefinition,
    TaskResponse,
)

__all__ = [
    "AgentRole",
    "AgentStatus",
    "ToolConfig",
    "AgentConfig",
    "MCPConfig",
    "TaskType",
    "TaskStatus",
    "TaskDefinition",
    "TaskResponse",
]
