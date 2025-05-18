"""
Simple test for the FastAPI application.
"""
import sys
import os
import json
from uuid import uuid4

# Add the src directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from fastapi.testclient import TestClient
from external_interface.api import app
from external_interface.models import CommandType, CommandStatus

# Create a test client
client = TestClient(app)

# Mock API key for testing
TEST_API_KEY = "paop-api-key-placeholder"
HEADERS = {"X-API-Key": TEST_API_KEY}


def test_health_endpoint():
    """Test the health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_send_command_unauthorized():
    """Test sending a command without API key."""
    command_id = str(uuid4())
    command = {
        "command_id": command_id,
        "command_type": CommandType.LIST_AGENTS,
        "payload": {},
    }
    
    response = client.post("/command", json=command)
    assert response.status_code == 401
    assert "Invalid API key" in response.json()["detail"]


def test_send_command_authorized():
    """Test sending a command with API key."""
    command_id = str(uuid4())
    command = {
        "command_id": command_id,
        "command_type": CommandType.LIST_AGENTS,
        "payload": {},
    }
    
    response = client.post("/command", json=command, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["command_id"] == command_id
    assert response.json()["status"] == CommandStatus.SUCCESS


def test_execute_task():
    """Test executing a task."""
    agent_id = "test-agent"
    task_data = {
        "task_type": "test_task",
        "parameters": {"key": "value"},
    }
    
    response = client.post(f"/tasks/{agent_id}", json=task_data, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == CommandStatus.SUCCESS
    assert "task_id" in response.json()


def test_create_agent():
    """Test creating an agent."""
    agent_config = {
        "type": "test_agent",
        "name": "Test Agent",
    }
    
    response = client.post("/agents", json=agent_config, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == CommandStatus.SUCCESS
    assert "agent_id" in response.json()


def test_list_agents():
    """Test listing agents."""
    response = client.get("/agents", headers=HEADERS)
    assert response.status_code == 200
    assert "agents" in response.json()


def test_get_agent_status():
    """Test getting agent status."""
    agent_id = "test-agent"
    response = client.get(f"/agents/{agent_id}", headers=HEADERS)
    assert response.status_code == 200
    assert "agent_id" in response.json()


if __name__ == "__main__":
    print("Testing health endpoint...")
    test_health_endpoint()
    print("Health endpoint test passed!")
    
    print("\nTesting unauthorized command...")
    test_send_command_unauthorized()
    print("Unauthorized command test passed!")
    
    print("\nTesting authorized command...")
    test_send_command_authorized()
    print("Authorized command test passed!")
    
    print("\nTesting execute task...")
    test_execute_task()
    print("Execute task test passed!")
    
    print("\nTesting create agent...")
    test_create_agent()
    print("Create agent test passed!")
    
    print("\nTesting list agents...")
    test_list_agents()
    print("List agents test passed!")
    
    print("\nTesting get agent status...")
    test_get_agent_status()
    print("Get agent status test passed!")
    
    print("\nAll tests passed!")
