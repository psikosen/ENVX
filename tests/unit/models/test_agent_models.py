"""
Tests for agent model Pydantic classes.

These tests verify that the agent models correctly validate data and enforce constraints.
"""

import unittest
from pydantic import ValidationError

from src.agent.models import (
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


class TestAgentModels(unittest.TestCase):
    """Test cases for agent model Pydantic classes."""
    
    def test_agent_config_validation(self):
        """Test that AgentConfig properly validates input data."""
        # Valid agent config
        config = AgentConfig(
            agent_id="test-agent",
            role=AgentRole.WORKER,
        )
        self.assertEqual(config.agent_id, "test-agent")
        self.assertEqual(config.role, AgentRole.WORKER)
        self.assertFalse(config.is_orchestrator)
        
        # Valid orchestrator config
        config = AgentConfig(
            agent_id="orchestrator",
            role=AgentRole.ORCHESTRATOR,
        )
        self.assertEqual(config.agent_id, "orchestrator")
        self.assertEqual(config.role, AgentRole.ORCHESTRATOR)
        self.assertTrue(config.is_orchestrator)  # Auto-set based on role
        
        # Inconsistent orchestrator settings should be auto-corrected
        config = AgentConfig(
            agent_id="orchestrator",
            role=AgentRole.ORCHESTRATOR,
            is_orchestrator=False,  # This is inconsistent with role
        )
        self.assertTrue(config.is_orchestrator)  # Auto-corrected
        
        # Missing required fields
        with self.assertRaises(ValidationError):
            AgentConfig()  # Missing agent_id
    
    def test_mcp_config_validation(self):
        """Test that MCPConfig properly validates input data."""
        # Valid MCP config
        config = MCPConfig(
            enabled=True,
            executable_path="/usr/local/bin/mcp",
            config_path="/etc/mcp",
            timeout_seconds=30,
        )
        self.assertEqual(config.executable_path, "/usr/local/bin/mcp")
        self.assertEqual(config.timeout_seconds, 30)
        
        # Default values
        config = MCPConfig(
            enabled=True,
            executable_path="/usr/local/bin/mcp",
        )
        self.assertEqual(config.timeout_seconds, 30)  # Default
        self.assertEqual(config.retry_count, 3)  # Default
        
        # Invalid timeout (too small)
        with self.assertRaises(ValidationError):
            MCPConfig(
                enabled=True,
                executable_path="/usr/local/bin/mcp",
                timeout_seconds=0,  # Invalid
            )
        
        # Invalid timeout (too large)
        with self.assertRaises(ValidationError):
            MCPConfig(
                enabled=True,
                executable_path="/usr/local/bin/mcp",
                timeout_seconds=301,  # Invalid
            )
    
    def test_task_definition_validation(self):
        """Test that TaskDefinition properly validates input data."""
        # Valid task definition
        task = TaskDefinition(
            task_id="task-1",
            task_type=TaskType.MCP_COMMAND,
            payload={"command": "test", "args": []},
        )
        self.assertEqual(task.task_id, "task-1")
        self.assertEqual(task.task_type, TaskType.MCP_COMMAND)
        self.assertEqual(task.payload["command"], "test")
        
        # Missing required fields
        with self.assertRaises(ValidationError):
            TaskDefinition(
                task_id="task-1",
                task_type=TaskType.MCP_COMMAND,
                # Missing payload
            )
    
    def test_task_response_validation(self):
        """Test that TaskResponse properly validates input data."""
        # Valid successful response
        response = TaskResponse(
            task_id="task-1",
            agent_id="agent-1",
            status=TaskStatus.COMPLETED,
            result_payload={"result": "success"},
        )
        self.assertEqual(response.task_id, "task-1")
        self.assertEqual(response.status, TaskStatus.COMPLETED)
        self.assertIsNone(response.error_message)
        
        # Valid error response
        response = TaskResponse(
            task_id="task-1",
            agent_id="agent-1",
            status=TaskStatus.FAILED,
            error_message="Something went wrong",
        )
        self.assertEqual(response.status, TaskStatus.FAILED)
        self.assertEqual(response.error_message, "Something went wrong")
        
        # Inconsistent error state (failed but no error message)
        with self.assertRaises(ValidationError):
            TaskResponse(
                task_id="task-1",
                agent_id="agent-1",
                status=TaskStatus.FAILED,
                # Missing error_message
            )
        
        # Inconsistent success state (completed but with error message)
        with self.assertRaises(ValidationError):
            TaskResponse(
                task_id="task-1",
                agent_id="agent-1",
                status=TaskStatus.COMPLETED,
                error_message="This shouldn't be here",
            )


if __name__ == "__main__":
    unittest.main()
