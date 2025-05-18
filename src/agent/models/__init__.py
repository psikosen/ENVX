"""
Agent models package for the Pedantic Agent Orchestration Platform (PAOP).

This package provides the core Pydantic data models used for agent configuration,
task processing, and MCP integration.
"""

from .base import (
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

from .desktop_commander import (
    BrowserAction,
    BrowserCommandParams,
    ClipboardAction,
    ClipboardCommandParams,
    SystemAction,
    SystemCommandParams,
    FileAction,
    FileCommandParams,
    DesktopCommanderCommand,
    MCPDesktopCommanderTask,
)

from .llm import (
    LLMProvider,
    LLMModelConfig,
    LLMPromptTemplate,
    LLMRequestPayload,
    LLMResponsePayload,
    LLMTaskDefinition,
    OllamaModelInfo,
    OllamaModelPullRequest,
)

__all__ = [
    # Base models
    "AgentRole",
    "AgentStatus",
    "ToolConfig",
    "AgentConfig",
    "MCPConfig",
    "TaskType",
    "TaskStatus",
    "TaskDefinition",
    "TaskResponse",
    
    # Desktop Commander models
    "BrowserAction",
    "BrowserCommandParams",
    "ClipboardAction",
    "ClipboardCommandParams",
    "SystemAction",
    "SystemCommandParams",
    "FileAction",
    "FileCommandParams",
    "DesktopCommanderCommand",
    "MCPDesktopCommanderTask",
    
    # LLM models
    "LLMProvider",
    "LLMModelConfig",
    "LLMPromptTemplate",
    "LLMRequestPayload",
    "LLMResponsePayload",
    "LLMTaskDefinition",
    "OllamaModelInfo",
    "OllamaModelPullRequest",
]
