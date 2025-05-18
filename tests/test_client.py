"""
Simple test for the PAOP client.
"""
import sys
import os
import json
import asyncio
from uuid import uuid4
import pytest
from unittest.mock import AsyncMock, patch

# Add the src directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from external_interface.client import PAOPClient
from external_interface.models import CommandType, CommandStatus, ExternalCommandResponse


async def test_health_check():
    """Test the health check method."""
    mock_response = AsyncMock()
    mock_response.json.return_value = {"status": "ok"}
    mock_response.raise_for_status = AsyncMock()
    
    with patch("httpx.AsyncClient.get", return_value=mock_response):
        client = PAOPClient("http://localhost:8000", "test-api-key")
        result = await client.health_check()
        
        assert result == {"status": "ok"}


async def test_send_command():
    """Test the send_command method."""
    command_id = str(uuid4())
    mock_response = AsyncMock()
    mock_response.json.return_value = {
        "command_id": command_id,
        "status": CommandStatus.SUCCESS,
        "result": {"message": "Command processed"},
    }
    mock_response.raise_for_status = AsyncMock()
    
    with patch("httpx.AsyncClient.post", return_value=mock_response):
        client = PAOPClient("http://localhost:8000", "test-api-key")
        command = {
            "command_id": command_id,
            "command_type": CommandType.LIST_AGENTS,
            "payload": {},
        }
        result = await client.send_command(command)
        
        assert result.command_id == command_id
        assert result.status == CommandStatus.SUCCESS
        assert result.result == {"message": "Command processed"}


async def test_execute_task():
    """Test the execute_task method."""
    command_id = str(uuid4())
    task_id = str(uuid4())
    mock_response = AsyncMock()
    mock_response.json.return_value = {
        "command_id": command_id,
        "status": CommandStatus.SUCCESS,
        "result": {"output": "Task output"},
        "task_id": task_id,
    }
    mock_response.raise_for_status = AsyncMock()
    
    with patch("httpx.AsyncClient.post", return_value=mock_response):
        client = PAOPClient("http://localhost:8000", "test-api-key")
        task_data = {
            "task_type": "test_task",
            "parameters": {"key": "value"},
        }
        result = await client.execute_task("test-agent", task_data)
        
        assert result.command_id == command_id
        assert result.status == CommandStatus.SUCCESS
        assert result.result == {"output": "Task output"}
        assert result.task_id == task_id


async def test_create_agent():
    """Test the create_agent method."""
    command_id = str(uuid4())
    agent_id = str(uuid4())
    mock_response = AsyncMock()
    mock_response.json.return_value = {
        "command_id": command_id,
        "status": CommandStatus.SUCCESS,
        "result": {"name": "Test Agent"},
        "agent_id": agent_id,
    }
    mock_response.raise_for_status = AsyncMock()
    
    with patch("httpx.AsyncClient.post", return_value=mock_response):
        client = PAOPClient("http://localhost:8000", "test-api-key")
        agent_config = {
            "type": "test_agent",
            "name": "Test Agent",
        }
        result = await client.create_agent(agent_config)
        
        assert result.command_id == command_id
        assert result.status == CommandStatus.SUCCESS
        assert result.result == {"name": "Test Agent"}
        assert result.agent_id == agent_id


async def test_list_agents():
    """Test the list_agents method."""
    mock_response = AsyncMock()
    mock_response.json.return_value = {
        "agents": [
            {"id": str(uuid4()), "name": "Agent 1"},
            {"id": str(uuid4()), "name": "Agent 2"},
        ]
    }
    mock_response.raise_for_status = AsyncMock()
    
    with patch("httpx.AsyncClient.get", return_value=mock_response):
        client = PAOPClient("http://localhost:8000", "test-api-key")
        result = await client.list_agents()
        
        assert "agents" in result
        assert len(result["agents"]) == 2


async def test_get_agent_status():
    """Test the get_agent_status method."""
    agent_id = str(uuid4())
    mock_response = AsyncMock()
    mock_response.json.return_value = {
        "agent_id": agent_id,
        "status": {"state": "running", "tasks": 2},
    }
    mock_response.raise_for_status = AsyncMock()
    
    with patch("httpx.AsyncClient.get", return_value=mock_response):
        client = PAOPClient("http://localhost:8000", "test-api-key")
        result = await client.get_agent_status(agent_id)
        
        assert result["agent_id"] == agent_id
        assert result["status"]["state"] == "running"
        assert result["status"]["tasks"] == 2


async def run_all_tests():
    """Run all tests."""
    await test_health_check()
    print("Health check test passed!")
    
    await test_send_command()
    print("Send command test passed!")
    
    await test_execute_task()
    print("Execute task test passed!")
    
    await test_create_agent()
    print("Create agent test passed!")
    
    await test_list_agents()
    print("List agents test passed!")
    
    await test_get_agent_status()
    print("Get agent status test passed!")


def main():
    """Run the tests."""
    print("Testing PAOP client...")
    asyncio.run(run_all_tests())
    print("All client tests passed!")


if __name__ == "__main__":
    main()
