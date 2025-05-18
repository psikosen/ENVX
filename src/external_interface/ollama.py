"""
Ollama model management endpoints for the PAOP API.

This module provides FastAPI endpoints for managing Ollama models.
"""

from typing import Any, Dict, List
import logging

from fastapi import APIRouter, Depends, HTTPException, Body, Path, Query
from pydantic import BaseModel

from src.agent.clients import OllamaClient, OllamaClientException, ollama_client
from src.agent.models.llm import OllamaModelInfo, OllamaModelPullRequest
from src.external_interface.api import verify_api_key

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(
    prefix="/ollama",
    tags=["ollama"],
    dependencies=[Depends(verify_api_key)],
)


# Response models
class OllamaListModelsResponse(BaseModel):
    """Response for listing Ollama models."""
    
    models: List[OllamaModelInfo]


class OllamaPullModelResponse(BaseModel):
    """Response for pulling an Ollama model."""
    
    status: str
    message: str
    details: Dict[str, Any]


# API endpoints
@router.get("/models", response_model=OllamaListModelsResponse)
async def list_ollama_models():
    """List all available Ollama models."""
    try:
        models = await ollama_client.list_models()
        return OllamaListModelsResponse(models=models)
    except OllamaClientException as e:
        logger.error(f"Failed to list Ollama models: {str(e)}")
        raise HTTPException(
            status_code=e.status_code or 500,
            detail=f"Failed to list Ollama models: {e.message}",
        )
    except Exception as e:
        logger.error(f"Unexpected error listing Ollama models: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}",
        )


@router.post("/models/pull", response_model=OllamaPullModelResponse)
async def pull_ollama_model(
    pull_request: OllamaModelPullRequest = Body(...),
):
    """Pull a model from the Ollama library."""
    try:
        result = await ollama_client.pull_model(
            model_name=pull_request.name,
            insecure=pull_request.insecure,
        )
        
        return OllamaPullModelResponse(
            status="success",
            message=f"Started pulling model: {pull_request.name}",
            details=result,
        )
    except OllamaClientException as e:
        logger.error(f"Failed to pull Ollama model: {str(e)}")
        raise HTTPException(
            status_code=e.status_code or 500,
            detail=f"Failed to pull Ollama model: {e.message}",
        )
    except Exception as e:
        logger.error(f"Unexpected error pulling Ollama model: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}",
        )
