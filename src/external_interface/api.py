"""
FastAPI implementation of the external command interface for PAOP.

This module provides a REST API for external clients to send commands to the PAOP
orchestrator and agents running inside the Docker container.
"""
from typing import Any, Dict, List, Optional
import logging
import uuid
import os

from fastapi import FastAPI, HTTPException, Depends, Header, Request, status, Body
from pydantic import BaseModel

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
from .config import load_api_config

# Setup logging
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="PAOP External Interface",
    description="API for sending commands to Pedantic Agent Orchestration Platform",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Load configuration
config = load_api_config()

# Import actual orchestrator client
# Use absolute import instead of relative import
from src.agent_framework.orchestrator_client import OrchestratorClient, get_client_instance

# Dependency for getting orchestrator client
async def get_orchestrator_client():
    """Dependency for getting the orchestrator client."""
    # Get the singleton instance and ensure it's initialized
    from src.agent_framework.orchestrator_client import get_client_instance
    return await get_client_instance()


# API key authentication
def verify_api_key(x_api_key: str = Header(...)):
    """Verify the API key against configuration."""
    if not x_api_key or x_api_key != config.api_key:
        logger.warning(f"Invalid API key attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return x_api_key


@app.get("/")
async def root():
    """Root endpoint that provides basic API information."""
    return {
        "name": "PAOP External Interface",
        "version": "0.1.0",
        "description": "API for sending commands to Pedantic Agent Orchestration Platform",
        "endpoints": [
            "/",
            "/health",
            "/command",
            "/tasks/{agent_id}",
            "/agents",
            "/agents/{agent_id}",
            "/ollama/models",
            "/ollama/models/pull"
        ],
        "documentation": {
            "swagger_ui": "/docs",
            "redoc": "/redoc",
            "openapi_json": "/openapi.json"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/command", response_model=ExternalCommandResponse, status_code=200)
async def send_command(
    command: ExternalCommandRequest = Body(
        ...,
        examples={
            "System Status": {
                "summary": "Get system status",
                "value": {
                    "command_id": "cmd-" + str(uuid.uuid4()),
                    "command_type": "get_system_status",
                    "target_id": None,
                    "payload": {}
                }
            },
            "List Agents": {
                "summary": "List all agents",
                "value": {
                    "command_id": "cmd-" + str(uuid.uuid4()),
                    "command_type": "list_agents",
                    "target_id": None,
                    "payload": {}
                }
            }
        }
    ),
    orchestrator_client: OrchestratorClient = Depends(get_orchestrator_client),
    api_key: str = Depends(verify_api_key),
):
    """Send a command to the PAOP orchestrator."""
    logger.info(f"Received command: {command.command_type} (ID: {command.command_id})")
    
    try:
        # Forward the command to the orchestrator
        response = await orchestrator_client.send_command(command)
        return response
    except Exception as e:
        logger.error(f"Error processing command: {str(e)}", exc_info=True)
        return ExternalCommandResponse(
            command_id=command.command_id,
            status=CommandStatus.FAILURE,
            error=f"Error processing command: {str(e)}"
        )


@app.post("/tasks/{agent_id}", response_model=ExecuteTaskResponse, status_code=200)
async def execute_task(
    agent_id: str,
    task_request: Dict[str, Any] = Body(
        ...,
        examples={
            "Process Data Task": {
                "summary": "Execute a data processing task",
                "value": {
                    "task_type": "process_data",
                    "input_data": "sample data to process",
                    "parameters": {
                        "format": "json",
                        "validate": True
                    }
                }
            },
            "LLM Task": {
                "summary": "Execute an LLM task",
                "value": {
                    "task_type": "llm_request",
                    "model_config": {
                        "provider": "ollama",
                        "model_name": "llama3",
                        "temperature": 0.7
                    },
                    "request_payload": {
                        "prompt": "Explain the concept of recursion in programming."
                    }
                }
            },
            "MCP Command Task": {
                "summary": "Execute a desktop commander task",
                "value": {
                    "task_type": "mcp_command",
                    "mcp_server": "desktop-commander",
                    "command": "browser",
                    "parameters": {
                        "action": "open",
                        "url": "https://example.com"
                    }
                }
            }
        }
    ),
    orchestrator_client: OrchestratorClient = Depends(get_orchestrator_client),
    api_key: str = Depends(verify_api_key),
):
    """Execute a task on a specific agent."""
    # Generate a command ID
    command_id = str(uuid.uuid4())
    
    # Create an ExecuteTaskRequest
    command = ExecuteTaskRequest(
        command_id=command_id,
        target_id=agent_id,
        payload=task_request,
    )
    
    logger.info(f"Executing task on agent {agent_id}: {task_request.get('task_type', 'unknown')}")
    
    try:
        # Forward the command to the orchestrator
        response = await orchestrator_client.send_command(command)
        
        # Convert the generic response to an ExecuteTaskResponse
        return ExecuteTaskResponse(
            command_id=response.command_id,
            status=response.status,
            result=response.result,
            error=response.error,
            task_id=response.result.get("task_id") if response.result else None
        )
    except Exception as e:
        logger.error(f"Error executing task: {str(e)}", exc_info=True)
        return ExecuteTaskResponse(
            command_id=command_id,
            status=CommandStatus.FAILURE,
            error=f"Error executing task: {str(e)}",
            task_id=None
        )


@app.post("/agents", response_model=CreateAgentResponse, status_code=200)
async def create_agent(
    agent_config: Dict[str, Any] = Body(
        ...,
        examples={
            "Data Processor Agent": {
                "summary": "Create a data processor agent",
                "value": {
                    "type": "data_processor",
                    "name": "DataProcessorAgent1",
                    "capabilities": ["process_csv", "transform_json"],
                    "config": {
                        "max_memory": "2GB",
                        "timeout": 300
                    }
                }
            },
            "LLM Agent": {
                "summary": "Create an LLM agent",
                "value": {
                    "type": "llm_agent",
                    "name": "OllamaAgent",
                    "capabilities": ["text_generation", "code_generation"],
                    "config": {
                        "llm_provider": "ollama",
                        "model_name": "llama3",
                        "default_prompt_template": "You are a helpful assistant. Answer the following query: {query}"
                    }
                }
            },
            "Desktop Commander Agent": {
                "summary": "Create a desktop commander agent",
                "value": {
                    "type": "desktop_agent",
                    "name": "DesktopCommanderAgent",
                    "capabilities": ["browser_control", "clipboard_management", "system_control"],
                    "config": {
                        "mcp_server": "desktop-commander",
                        "llm_provider": "gemini",
                        "model_name": "gemini-pro",
                        "default_prompt_template": "You are a helpful assistant that controls the desktop. Perform the following task: {task}"
                    }
                }
            }
        }
    ),
    orchestrator_client: OrchestratorClient = Depends(get_orchestrator_client),
    api_key: str = Depends(verify_api_key),
):
    """Create a new agent."""
    # Generate a command ID
    command_id = str(uuid.uuid4())
    
    # Create a CreateAgentRequest
    command = CreateAgentRequest(
        command_id=command_id,
        payload={"agent_type": agent_config.get("type", "default"), **agent_config},
    )
    
    logger.info(f"Creating agent of type: {agent_config.get('type', 'default')}")
    
    try:
        # Forward the command to the orchestrator
        response = await orchestrator_client.send_command(command)
        
        # Convert the generic response to a CreateAgentResponse
        return CreateAgentResponse(
            command_id=response.command_id,
            status=response.status,
            result=response.result,
            error=response.error,
            agent_id=response.result.get("agent_id") if response.result else None
        )
    except Exception as e:
        logger.error(f"Error creating agent: {str(e)}", exc_info=True)
        return CreateAgentResponse(
            command_id=command_id,
            status=CommandStatus.FAILURE,
            error=f"Error creating agent: {str(e)}",
            agent_id=None
        )


@app.get("/agents", response_model=Dict[str, Any])
async def list_agents(
    orchestrator_client: OrchestratorClient = Depends(get_orchestrator_client),
    api_key: str = Depends(verify_api_key),
):
    """List all agents."""
    # Generate a command ID
    command_id = str(uuid.uuid4())
    
    # Create a command to list agents
    command = ExternalCommandRequest(
        command_id=command_id,
        command_type=CommandType.LIST_AGENTS,
        payload={},
    )
    
    logger.info("Listing agents")
    
    try:
        # Forward the command to the orchestrator
        response = await orchestrator_client.send_command(command)
        
        # Return the result
        if response.status == CommandStatus.SUCCESS and response.result:
            return {"agents": response.result.get("agents", [])}
        else:
            return {"agents": [], "error": response.error}
    except Exception as e:
        logger.error(f"Error listing agents: {str(e)}", exc_info=True)
        return {"agents": [], "error": f"Error listing agents: {str(e)}"}


@app.get("/agents/{agent_id}", response_model=Dict[str, Any])
async def get_agent_status(
    agent_id: str,
    orchestrator_client: OrchestratorClient = Depends(get_orchestrator_client),
    api_key: str = Depends(verify_api_key),
):
    """Get status of a specific agent."""
    # Generate a command ID
    command_id = str(uuid.uuid4())
    
    # Create a command to get agent status
    command = ExternalCommandRequest(
        command_id=command_id,
        command_type=CommandType.GET_AGENT_STATUS,
        target_id=agent_id,
        payload={},
    )
    
    logger.info(f"Getting status for agent {agent_id}")
    
    try:
        # Forward the command to the orchestrator
        response = await orchestrator_client.send_command(command)
        
        # Return the result
        if response.status == CommandStatus.SUCCESS and response.result:
            return {"agent_id": agent_id, "status": response.result}
        else:
            return {"agent_id": agent_id, "error": response.error}
    except Exception as e:
        logger.error(f"Error getting agent status: {str(e)}", exc_info=True)
        return {"agent_id": agent_id, "error": f"Error getting agent status: {str(e)}"}

# Import routes (must be after FastAPI app definition)
from src.external_interface.ollama import router as ollama_router

# Include routes
app.include_router(ollama_router)
