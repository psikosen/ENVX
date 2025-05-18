"""
MCP client wrapper for the Pedantic Agent Orchestration Platform (PAOP).

This module provides an abstraction layer for interacting with the DesktopCommanderMCP tool.
It handles loading MCP configuration, executing commands, and error handling.
"""

import os
import json
import logging
import subprocess
import time
from typing import Any, Dict, List, Optional, Union
from pathlib import Path

from pydantic import ValidationError

from .models import MCPConfig, TaskDefinition, TaskResponse, TaskStatus


logger = logging.getLogger(__name__)


class MCPException(Exception):
    """Exception raised for MCP-related errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class MCPClient:
    """
    Client for interacting with the DesktopCommanderMCP tool.
    
    This class abstracts the details of calling the MCP executable, handling
    configuration, error conditions, and retries.
    """
    
    def __init__(self, config: MCPConfig):
        """
        Initialize the MCP client with the provided configuration.
        
        Args:
            config: MCPConfig object containing configuration for MCP interaction
        """
        self.config = config
        self._validate_config()
        logger.info(f"Initialized MCP client with config: {self.config.model_dump(exclude={'api_key'})}")
    
    @classmethod
    def from_config_file(cls, config_path: Union[str, Path]) -> "MCPClient":
        """
        Create an MCPClient instance from a configuration file.
        
        Args:
            config_path: Path to the MCP configuration file (YAML or JSON)
            
        Returns:
            MCPClient instance
            
        Raises:
            FileNotFoundError: If the config file doesn't exist
            ValidationError: If the config is invalid
            ValueError: If the config file format is not supported
        """
        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"MCP config file not found: {config_path}")
        
        content = config_path.read_text()
        
        # Parse based on file extension
        if config_path.suffix.lower() in ('.yaml', '.yml'):
            try:
                import yaml
                config_dict = yaml.safe_load(content)
            except ImportError:
                logger.warning("PyYAML not installed. Falling back to JSON parsing.")
                config_dict = json.loads(content)
            except Exception as e:
                raise ValueError(f"Failed to parse YAML config: {e}")
        elif config_path.suffix.lower() == '.json':
            try:
                config_dict = json.loads(content)
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse JSON config: {e}")
        else:
            raise ValueError(f"Unsupported config file format: {config_path.suffix}")
        
        # Extract MCP-specific config if nested
        if 'mcp' in config_dict and isinstance(config_dict['mcp'], dict):
            config_dict = config_dict['mcp']
        
        try:
            mcp_config = MCPConfig(**config_dict)
            return cls(mcp_config)
        except ValidationError as e:
            raise ValidationError(f"Invalid MCP configuration: {e}", e.errors())
    
    def _validate_config(self) -> None:
        """
        Validate the MCP configuration.
        
        Raises:
            MCPException: If the configuration is invalid or missing required fields
        """
        if not self.config.enabled:
            logger.warning("MCP integration is disabled in configuration")
            return
        
        if not self.config.executable_path:
            raise MCPException("MCP executable path is required when MCP is enabled")
        
        # Check if executable exists and is executable
        executable = Path(self.config.executable_path)
        if not executable.exists():
            raise MCPException(f"MCP executable not found: {executable}")
        
        # Additional validation could be added here based on specific MCP requirements
    
    def execute_command(self, command: str, args: List[str] = None) -> Dict[str, Any]:
        """
        Execute an MCP command with the given arguments.
        
        Args:
            command: The MCP command to execute
            args: List of command-line arguments to pass to the MCP executable
            
        Returns:
            Dictionary containing the command output
            
        Raises:
            MCPException: If the command execution fails
        """
        if not self.config.enabled:
            raise MCPException("Cannot execute command: MCP integration is disabled")
        
        args = args or []
        cmd = [self.config.executable_path, command, *args]
        
        # Prepare environment with configured variables
        env = os.environ.copy()
        env.update(self.config.environment_variables)
        
        # Add API key if provided
        if self.config.api_key:
            env["MCP_API_KEY"] = self.config.api_key
        
        retry_count = 0
        last_error = None
        
        while retry_count <= self.config.retry_count:
            if retry_count > 0:
                logger.warning(
                    f"Retrying MCP command (attempt {retry_count}/{self.config.retry_count})"
                    f" after error: {last_error}"
                )
                time.sleep(self.config.retry_delay_seconds)
            
            try:
                logger.debug(f"Executing MCP command: {' '.join(cmd)}")
                result = subprocess.run(
                    cmd,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.config.timeout_seconds,
                    check=False,  # We'll handle the return code ourselves
                )
                
                if result.returncode != 0:
                    error_msg = f"MCP command failed with exit code {result.returncode}: {result.stderr.strip()}"
                    logger.error(error_msg)
                    last_error = error_msg
                    retry_count += 1
                    continue
                
                # Try to parse JSON output
                try:
                    output = json.loads(result.stdout)
                    logger.debug(f"MCP command succeeded with JSON output")
                    return output
                except json.JSONDecodeError:
                    # If not JSON, return as plain text
                    logger.debug(f"MCP command succeeded with plain text output")
                    return {"stdout": result.stdout.strip()}
                
            except subprocess.TimeoutExpired as e:
                error_msg = f"MCP command timed out after {self.config.timeout_seconds} seconds"
                logger.error(error_msg)
                last_error = error_msg
                retry_count += 1
                continue
                
            except Exception as e:
                error_msg = f"Error executing MCP command: {str(e)}"
                logger.error(error_msg)
                last_error = error_msg
                retry_count += 1
                continue
        
        # If we get here, all retries failed
        raise MCPException(
            f"MCP command failed after {self.config.retry_count} retries: {last_error}",
            details={
                "command": command,
                "args": args,
                "last_error": last_error
            }
        )
    
    def process_task(self, task: TaskDefinition) -> TaskResponse:
        """
        Process a task using the MCP tool.
        
        Args:
            task: The task definition to process
            
        Returns:
            TaskResponse containing the result of the task
            
        Raises:
            MCPException: If the task processing fails
        """
        logger.info(f"Processing MCP task: {task.task_id} ({task.task_type})")
        
        # Basic validation
        if task.task_type.value != "mcp_command":
            return TaskResponse(
                task_id=task.task_id,
                agent_id="mcp_client",  # This will be overridden by the agent
                status=TaskStatus.FAILED,
                error_message=f"MCPClient can only process tasks of type 'mcp_command', got '{task.task_type}'"
            )
        
        # Extract command details from payload
        try:
            command = task.payload.get("command")
            if not command:
                raise ValueError("Missing 'command' in task payload")
            
            args = task.payload.get("args", [])
            if not isinstance(args, list):
                raise ValueError("Task payload 'args' must be a list")
            
        except (KeyError, ValueError) as e:
            return TaskResponse(
                task_id=task.task_id,
                agent_id="mcp_client",
                status=TaskStatus.FAILED,
                error_message=f"Invalid task payload: {str(e)}"
            )
        
        # Execute the command
        try:
            result = self.execute_command(command, args)
            return TaskResponse(
                task_id=task.task_id,
                agent_id="mcp_client",
                status=TaskStatus.COMPLETED,
                result_payload=result
            )
        except MCPException as e:
            return TaskResponse(
                task_id=task.task_id,
                agent_id="mcp_client",
                status=TaskStatus.FAILED,
                error_message=str(e)
            )
