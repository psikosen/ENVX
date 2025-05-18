"""
Configuration loading utilities for the Pedantic Agent Orchestration Platform (PAOP).

This module provides functions for loading and validating agent and MCP configurations
from various sources (files, environment variables, etc.).
"""

import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple

from pydantic import ValidationError

from .models import AgentConfig, MCPConfig


logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Exception raised for configuration-related errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


def load_yaml_or_json(file_path: Union[str, Path]) -> Dict[str, Any]:
    """
    Load a YAML or JSON file into a dictionary.
    
    Args:
        file_path: Path to the configuration file
        
    Returns:
        Dictionary containing the parsed configuration
        
    Raises:
        FileNotFoundError: If the file doesn't exist
        ValueError: If the file format is not supported or the file is invalid
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {file_path}")
    
    content = file_path.read_text()
    
    # Parse based on file extension
    if file_path.suffix.lower() in ('.yaml', '.yml'):
        try:
            import yaml
            config_dict = yaml.safe_load(content)
        except ImportError:
            logger.warning("PyYAML not installed. Falling back to JSON parsing.")
            try:
                config_dict = json.loads(content)
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse config as JSON (yaml unavailable): {e}")
        except Exception as e:
            raise ValueError(f"Failed to parse YAML config: {e}")
    elif file_path.suffix.lower() == '.json':
        try:
            config_dict = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON config: {e}")
    else:
        raise ValueError(f"Unsupported config file format: {file_path.suffix}")
    
    return config_dict or {}


def load_mcp_config(
    config_path: Optional[Union[str, Path]] = None,
    env_prefix: str = "MCP_"
) -> MCPConfig:
    """
    Load MCP configuration from a file and/or environment variables.
    
    Environment variables take precedence over file configuration. For example,
    if the MCP config has a field "timeout_seconds", the environment variable
    "MCP_TIMEOUT_SECONDS" will override it.
    
    Args:
        config_path: Path to the MCP configuration file (optional)
        env_prefix: Prefix for environment variables (default: "MCP_")
        
    Returns:
        MCPConfig object
        
    Raises:
        ConfigurationError: If the configuration is invalid or cannot be loaded
    """
    config_dict = {}
    
    # Load from file if provided
    if config_path:
        try:
            file_config = load_yaml_or_json(config_path)
            # Extract MCP-specific config if nested
            if 'mcp' in file_config and isinstance(file_config['mcp'], dict):
                config_dict.update(file_config['mcp'])
            else:
                config_dict.update(file_config)
        except (FileNotFoundError, ValueError) as e:
            logger.warning(f"Failed to load MCP config from file: {e}")
    
    # Override with environment variables
    env_config = {}
    for key, value in os.environ.items():
        if key.startswith(env_prefix):
            # Convert MCP_TIMEOUT_SECONDS to timeout_seconds
            config_key = key[len(env_prefix):].lower()
            
            # Handle nested keys (MCP_ENV_VAR_NAME becomes environment_variables.name)
            if config_key.startswith('env_'):
                env_var_name = config_key[4:]
                if 'environment_variables' not in env_config:
                    env_config['environment_variables'] = {}
                env_config['environment_variables'][env_var_name] = value
            else:
                # Try to convert string values to appropriate types for common settings
                if config_key in ('enabled', 'debug'):
                    value = value.lower() in ('true', 'yes', '1', 'on')
                elif config_key in ('timeout_seconds', 'retry_count', 'retry_delay_seconds'):
                    try:
                        value = int(value)
                    except ValueError:
                        logger.warning(f"Invalid integer value for {key}: {value}")
                
                env_config[config_key] = value
    
    # Merge configurations, with environment variables taking precedence
    config_dict.update(env_config)
    
    # Create and validate the MCPConfig
    try:
        return MCPConfig(**config_dict)
    except ValidationError as e:
        raise ConfigurationError(f"Invalid MCP configuration: {e}", e.errors())


def load_agent_config(
    config_path: Optional[Union[str, Path]] = None,
    env_prefix: str = "AGENT_",
    agent_id: Optional[str] = None
) -> AgentConfig:
    """
    Load agent configuration from a file and/or environment variables.
    
    Environment variables take precedence over file configuration. For example,
    if the Agent config has a field "name", the environment variable
    "AGENT_NAME" will override it.
    
    Args:
        config_path: Path to the agent configuration file (optional)
        env_prefix: Prefix for environment variables (default: "AGENT_")
        agent_id: Agent ID to use if not specified in config or environment
        
    Returns:
        AgentConfig object
        
    Raises:
        ConfigurationError: If the configuration is invalid or cannot be loaded
    """
    config_dict = {}
    
    # Load from file if provided
    if config_path:
        try:
            file_config = load_yaml_or_json(config_path)
            # Extract agent-specific config if nested
            if 'agent' in file_config and isinstance(file_config['agent'], dict):
                config_dict.update(file_config['agent'])
            else:
                config_dict.update(file_config)
        except (FileNotFoundError, ValueError) as e:
            logger.warning(f"Failed to load agent config from file: {e}")
    
    # Override with environment variables
    env_config = {}
    for key, value in os.environ.items():
        if key.startswith(env_prefix):
            # Convert AGENT_ROLE to role
            config_key = key[len(env_prefix):].lower()
            
            # Handle nested keys if needed
            if '_' in config_key:
                parts = config_key.split('_', 1)
                if len(parts) == 2:
                    section, subkey = parts
                    if section in ('tool', 'tools'):
                        # Special handling for tool configurations
                        # TODO: Implement if needed
                        continue
            
            # Try to convert string values to appropriate types for common settings
            if config_key in ('is_orchestrator'):
                value = value.lower() in ('true', 'yes', '1', 'on')
            
            env_config[config_key] = value
    
    # Merge configurations, with environment variables taking precedence
    config_dict.update(env_config)
    
    # Add agent_id if provided and not already in config
    if agent_id and 'agent_id' not in config_dict:
        config_dict['agent_id'] = agent_id
    
    # Create and validate the AgentConfig
    try:
        return AgentConfig(**config_dict)
    except ValidationError as e:
        raise ConfigurationError(f"Invalid agent configuration: {e}", e.errors())


def load_configurations(
    agent_config_path: Optional[Union[str, Path]] = None,
    mcp_config_path: Optional[Union[str, Path]] = None,
    agent_id: Optional[str] = None
) -> Tuple[AgentConfig, MCPConfig]:
    """
    Load both agent and MCP configurations.
    
    Args:
        agent_config_path: Path to the agent configuration file (optional)
        mcp_config_path: Path to the MCP configuration file (optional)
        agent_id: Agent ID to use if not specified in config or environment
        
    Returns:
        Tuple of (AgentConfig, MCPConfig)
        
    Raises:
        ConfigurationError: If any configuration is invalid or cannot be loaded
    """
    try:
        agent_config = load_agent_config(agent_config_path, agent_id=agent_id)
        mcp_config = load_mcp_config(mcp_config_path)
        return agent_config, mcp_config
    except Exception as e:
        raise ConfigurationError(f"Failed to load configurations: {e}")
