"""
Environment variable utilities for the PAOP system.

This module provides functions for loading environment variables from .env files.
"""

import os
import logging
from typing import Any, Dict, Optional
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def load_env_file(env_file: Optional[str] = None) -> Dict[str, str]:
    """
    Load environment variables from a .env file.
    
    Args:
        env_file: Path to the .env file (optional)
        
    Returns:
        Dictionary of environment variables loaded from the file
    """
    # Try to find .env file in standard locations
    if env_file is None:
        # Try current directory first
        potential_paths = [
            Path.cwd() / ".env",
            Path.home() / ".env",
            Path(__file__).parent.parent.parent / ".env",
        ]
        
        for path in potential_paths:
            if path.exists():
                env_file = str(path)
                break
    
    # Load the .env file if found
    if env_file and Path(env_file).exists():
        logger.info(f"Loading environment variables from {env_file}")
        load_dotenv(env_file)
    else:
        logger.warning("No .env file found. Using existing environment variables.")
    
    # Return a copy of the environment variables
    return dict(os.environ)


def get_api_key(provider: str) -> Optional[str]:
    """
    Get an API key for a specific provider from environment variables.
    
    Args:
        provider: Provider name (e.g., "gemini", "anthropic")
        
    Returns:
        API key if found, None otherwise
    """
    # Define the environment variable names for each provider
    env_var_mapping = {
        "gemini": "GEMINI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "ollama": None,  # Ollama doesn't require an API key
    }
    
    # Get the environment variable name
    env_var_name = env_var_mapping.get(provider.lower())
    if env_var_name is None:
        return None
    
    # Get the API key from environment variables
    api_key = os.environ.get(env_var_name)
    
    # Log a warning if the API key is not found
    if api_key is None:
        logger.warning(f"API key for {provider} not found in environment variables")
    
    return api_key
