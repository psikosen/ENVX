"""
Agent framework for the Pedantic Agent Orchestration Platform (PAOP).

This package provides the core agent framework for PAOP, including the
orchestrator, agents, and task processing.
"""

from .orchestrator import get_orchestrator, process_command
from .orchestrator_client import OrchestratorClient

__all__ = [
    "get_orchestrator",
    "process_command",
    "OrchestratorClient",
]
