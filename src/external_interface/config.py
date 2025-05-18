"""
Configuration utilities for the PAOP external interface.

This module provides utilities for managing configuration settings for the
PAOP external interface, including API keys, URLs, and other parameters.
"""
import os
import json
import re
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, validator


class RateLimitConfig(BaseModel):
    """Configuration for rate limiting."""
    
    requests_per_minute: int = Field(60, description="Maximum requests per minute")
    burst_size: int = Field(10, description="Maximum burst size")


class APIConfig(BaseModel):
    """Configuration for the PAOP API."""
    
    host: str = Field("0.0.0.0", description="Host to bind the API server to")
    port: int = Field(8000, description="Port to bind the API server to")
    api_key: str = Field(..., description="API key for authentication")
    log_level: str = Field("INFO", description="Logging level")
    cors_origins: List[str] = Field(default_factory=list, description="Allowed CORS origins")
    max_request_size: int = Field(10485760, description="Maximum request size in bytes (10MB)")
    connection_timeout: int = Field(60, description="Connection timeout in seconds")
    max_connections: int = Field(100, description="Maximum number of connections")
    rate_limit: Optional[RateLimitConfig] = Field(None, description="Rate limiting configuration")
    
    @validator('log_level')
    def validate_log_level(cls, v):
        """Validate that the log level is valid."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}")
        return v


class ClientConfig(BaseModel):
    """Configuration for the PAOP client."""
    
    api_url: str = Field(..., description="Base URL of the PAOP API")
    api_key: str = Field(..., description="API key for authentication")
    timeout: int = Field(30, description="Request timeout in seconds")
    verify_ssl: bool = Field(True, description="Verify SSL certificates")
    max_retries: int = Field(3, description="Maximum number of retries for failed requests")
    retry_delay: float = Field(0.5, description="Delay between retries in seconds")


def _resolve_env_vars(value: Any) -> Any:
    """Resolve environment variables in string values.
    
    If the value is a string and contains environment variable references
    (e.g., ${VAR_NAME}), replace them with the corresponding environment
    variable values.
    
    Args:
        value: The value to resolve
        
    Returns:
        The resolved value
    """
    if not isinstance(value, str):
        return value
    
    # Find all environment variable references
    pattern = r'\${([A-Za-z0-9_]+)}'
    matches = re.findall(pattern, value)
    
    # Replace each reference with the environment variable value
    result = value
    for match in matches:
        env_value = os.environ.get(match, '')
        result = result.replace(f'${{{match}}}', env_value)
    
    return result


def _resolve_env_vars_in_dict(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve environment variables in a dictionary.
    
    Recursively traverses the dictionary and resolves environment variables
    in string values.
    
    Args:
        config_dict: The dictionary to process
        
    Returns:
        Dictionary with resolved environment variables
    """
    result = {}
    for key, value in config_dict.items():
        if isinstance(value, dict):
            result[key] = _resolve_env_vars_in_dict(value)
        elif isinstance(value, list):
            result[key] = [
                _resolve_env_vars_in_dict(item) if isinstance(item, dict) else
                _resolve_env_vars(item)
                for item in value
            ]
        else:
            result[key] = _resolve_env_vars(value)
    return result


def load_api_config(config_path: Optional[str] = None) -> APIConfig:
    """Load API configuration from environment variables or config file.
    
    Args:
        config_path: Optional path to the configuration file
        
    Returns:
        APIConfig instance
        
    Raises:
        ValueError: If required configuration values are missing
        FileNotFoundError: If the config file is not found
    """
    # Default configuration
    config_data = {
        "host": os.environ.get("PAOP_API_HOST", "0.0.0.0"),
        "port": int(os.environ.get("PAOP_API_PORT", "8000")),
        "api_key": os.environ.get("PAOP_API_KEY", ""),
        "log_level": os.environ.get("PAOP_LOG_LEVEL", "INFO"),
    }
    
    # If config path is provided, load from file
    if config_path:
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")
        
        with open(config_path, 'r') as f:
            file_config = json.load(f)
            
            # Resolve environment variables in the config file
            file_config = _resolve_env_vars_in_dict(file_config)
            
            # Update config_data with values from the file
            config_data.update(file_config)
    
    # Ensure API key is set
    if not config_data.get("api_key"):
        raise ValueError("API key must be provided via PAOP_API_KEY environment variable or config file")
    
    return APIConfig(**config_data)


def load_client_config(config_path: Optional[str] = None) -> ClientConfig:
    """Load client configuration from environment variables or config file.
    
    Args:
        config_path: Optional path to the configuration file
        
    Returns:
        ClientConfig instance
        
    Raises:
        ValueError: If required configuration values are missing
        FileNotFoundError: If the config file is not found
    """
    # Default configuration
    config_data = {
        "api_url": os.environ.get("PAOP_API_URL", ""),
        "api_key": os.environ.get("PAOP_API_KEY", ""),
        "timeout": int(os.environ.get("PAOP_TIMEOUT", "30")),
        "verify_ssl": os.environ.get("PAOP_VERIFY_SSL", "true").lower() == "true",
        "max_retries": int(os.environ.get("PAOP_MAX_RETRIES", "3")),
        "retry_delay": float(os.environ.get("PAOP_RETRY_DELAY", "0.5")),
    }
    
    # If config path is provided, load from file
    if config_path:
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")
        
        with open(config_path, 'r') as f:
            file_config = json.load(f)
            
            # Resolve environment variables in the config file
            file_config = _resolve_env_vars_in_dict(file_config)
            
            # Update config_data with values from the file
            config_data.update(file_config)
    
    # Ensure API URL and key are set
    if not config_data.get("api_url"):
        raise ValueError("API URL must be provided via PAOP_API_URL environment variable or config file")
    if not config_data.get("api_key"):
        raise ValueError("API key must be provided via PAOP_API_KEY environment variable or config file")
    
    return ClientConfig(**config_data)
