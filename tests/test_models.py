"""
Unit tests for the external interface models.
"""
import pytest
from uuid import uuid4
from src.external_interface.models import (
    CommandType,
    CommandStatus,
    ExternalCommandRequest,
    ExternalCommandResponse,
    ExecuteTaskRequest,
    ExecuteTaskResponse,
    CreateAgentRequest,
    CreateAgentResponse,
)


def test_external_command_request():
    """Test creation of an ExternalCommandRequest."""
    command_id = str(uuid4())
    request = ExternalCommandRequest(
        command_id=command_id,
        command_type=CommandType.EXECUTE_TASK,
        target_id="agent-123",
        payload={"task_type": "test_task"},
    )
    
    assert request.command_id == command_id
    assert request.command_type == CommandType.EXECUTE_TASK
    assert request.target_id == "agent-123"
    assert request.payload == {"task_type": "test_task"}


def test_external_command_response():
    """Test creation of an ExternalCommandResponse."""
    command_id = str(uuid4())
    response = ExternalCommandResponse(
        command_id=command_id,
        status=CommandStatus.SUCCESS,
        result={"message": "Task completed"},
    )
    
    assert response.command_id == command_id
    assert response.status == CommandStatus.SUCCESS
    assert response.result == {"message": "Task completed"}
    assert response.error is None


def test_external_command_response_with_error():
    """Test creation of an ExternalCommandResponse with error."""
    command_id = str(uuid4())
    response = ExternalCommandResponse(
        command_id=command_id,
        status=CommandStatus.FAILURE,
        error="Task failed",
    )
    
    assert response.command_id == command_id
    assert response.status == CommandStatus.FAILURE
    assert response.result is None
    assert response.error == "Task failed"


def test_execute_task_request():
    """Test creation of an ExecuteTaskRequest."""
    command_id = str(uuid4())
    request = ExecuteTaskRequest(
        command_id=command_id,
        target_id="agent-123",
        payload={"task_type": "test_task", "params": {"key": "value"}},
    )
    
    assert request.command_id == command_id
    assert request.command_type == CommandType.EXECUTE_TASK
    assert request.target_id == "agent-123"
    assert request.payload == {"task_type": "test_task", "params": {"key": "value"}}


def test_execute_task_response():
    """Test creation of an ExecuteTaskResponse."""
    command_id = str(uuid4())
    task_id = str(uuid4())
    response = ExecuteTaskResponse(
        command_id=command_id,
        status=CommandStatus.SUCCESS,
        result={"output": "Task output"},
        task_id=task_id,
    )
    
    assert response.command_id == command_id
    assert response.status == CommandStatus.SUCCESS
    assert response.result == {"output": "Task output"}
    assert response.task_id == task_id
    assert response.error is None


def test_create_agent_request():
    """Test creation of a CreateAgentRequest."""
    command_id = str(uuid4())
    request = CreateAgentRequest(
        command_id=command_id,
        payload={"agent_type": "test_agent", "name": "Test Agent"},
    )
    
    assert request.command_id == command_id
    assert request.command_type == CommandType.CREATE_AGENT
    assert request.target_id is None
    assert request.payload == {"agent_type": "test_agent", "name": "Test Agent"}


def test_create_agent_response():
    """Test creation of a CreateAgentResponse."""
    command_id = str(uuid4())
    agent_id = str(uuid4())
    response = CreateAgentResponse(
        command_id=command_id,
        status=CommandStatus.SUCCESS,
        result={"name": "Test Agent"},
        agent_id=agent_id,
    )
    
    assert response.command_id == command_id
    assert response.status == CommandStatus.SUCCESS
    assert response.result == {"name": "Test Agent"}
    assert response.agent_id == agent_id
    assert response.error is None
