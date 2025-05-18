"""
Client libraries for the PAOP system.

This package provides client libraries for interacting with various services.
"""

from .ollama import OllamaClient, OllamaClientException, ollama_client

__all__ = [
    "OllamaClient",
    "OllamaClientException",
    "ollama_client",
]
