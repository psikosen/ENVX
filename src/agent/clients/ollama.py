"""
Ollama client for the PAOP system.

This module provides a client for interacting with the Ollama API.
"""

import os
import json
import logging
import aiohttp
from typing import Any, Dict, List, Optional, Union
from pydantic import ValidationError

from ..models.llm import OllamaModelInfo, OllamaModelPullRequest

logger = logging.getLogger(__name__)


class OllamaClientException(Exception):
    """Exception raised for Ollama client errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class OllamaClient:
    """Client for interacting with the Ollama API."""
    
    def __init__(self, host: Optional[str] = None):
        """
        Initialize the Ollama client.
        
        Args:
            host: Ollama API host (default: from environment variable OLLAMA_HOST)
        """
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        if not self.host.startswith(("http://", "https://")):
            self.host = f"http://{self.host}"
        
        # Ensure the host doesn't end with a slash
        self.host = self.host.rstrip("/")
        
        logger.debug(f"Initialized Ollama client with host: {self.host}")
    
    async def _request(
        self, 
        method: str, 
        endpoint: str, 
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make a request to the Ollama API.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., "/api/tags")
            json_data: JSON data to send in the request body
            params: Query parameters
            
        Returns:
            Response data as a dictionary
            
        Raises:
            OllamaClientException: If the request fails
        """
        url = f"{self.host}{endpoint}"
        headers = {"Content-Type": "application/json"}
        
        logger.debug(f"Making {method} request to {url}")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=method,
                    url=url,
                    json=json_data,
                    params=params,
                    headers=headers,
                ) as response:
                    if response.content_type == "application/json":
                        data = await response.json()
                    else:
                        data = await response.text()
                        # Try to parse as JSON anyway, if possible
                        try:
                            data = json.loads(data)
                        except json.JSONDecodeError:
                            pass
                    
                    if response.status >= 400:
                        error_message = data.get("error", "Unknown error") if isinstance(data, dict) else "Unknown error"
                        raise OllamaClientException(
                            message=f"Ollama API error: {error_message}",
                            status_code=response.status,
                            details=data if isinstance(data, dict) else {"response": data},
                        )
                    
                    return data
        except aiohttp.ClientError as e:
            raise OllamaClientException(f"Failed to connect to Ollama API: {str(e)}")
    
    async def list_models(self) -> List[OllamaModelInfo]:
        """
        List all models available in Ollama.
        
        Returns:
            List of model information
            
        Raises:
            OllamaClientException: If the request fails
        """
        response = await self._request("GET", "/api/tags")
        
        # Parse the response
        try:
            models = []
            for model_data in response.get("models", []):
                # Convert the response to OllamaModelInfo
                model = OllamaModelInfo(
                    name=model_data.get("name"),
                    size=model_data.get("size", 0),
                    modified_at=model_data.get("modified_at", ""),
                    details=model_data,
                )
                models.append(model)
            
            return models
        except ValidationError as e:
            raise OllamaClientException(f"Failed to parse Ollama model list: {str(e)}")
    
    async def pull_model(self, model_name: str, insecure: bool = False) -> Dict[str, Any]:
        """
        Pull a model from the Ollama library.
        
        Args:
            model_name: Name of the model to pull
            insecure: Whether to skip TLS verification
            
        Returns:
            Response data
            
        Raises:
            OllamaClientException: If the request fails
        """
        data = {"name": model_name}
        if insecure:
            data["insecure"] = True
        
        response = await self._request("POST", "/api/pull", json_data=data)
        
        return response
    
    async def generate(
        self,
        model_name: str,
        prompt: str,
        system: Optional[str] = None,
        stream: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Generate text with an Ollama model.
        
        Args:
            model_name: Name of the model to use
            prompt: Prompt to send to the model
            system: System prompt (if supported by the model)
            stream: Whether to stream the response
            **kwargs: Additional parameters to send to the model
            
        Returns:
            Response data
            
        Raises:
            OllamaClientException: If the request fails
        """
        data = {
            "model": model_name,
            "prompt": prompt,
        }
        
        # Add optional parameters
        if system:
            data["system"] = system
        
        # Add any additional parameters
        for key, value in kwargs.items():
            if value is not None:
                data[key] = value
        
        endpoint = "/api/chat" if stream else "/api/generate"
        response = await self._request("POST", endpoint, json_data=data)
        
        return response


# Create a global instance for easy access
ollama_client = OllamaClient()
