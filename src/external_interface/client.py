"""
Client tool for interacting with the PAOP external command interface.

This module provides a command-line tool and SDK for sending commands to the
PAOP API and receiving responses.
"""
import argparse
import json
import sys
import uuid
import os
import time
import asyncio
from typing import Any, Dict, List, Optional, Union, Callable
import logging

import httpx
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
from .config import load_client_config, ClientConfig

# Setup logging
logger = logging.getLogger(__name__)


class PAOPClientError(Exception):
    """Base exception for PAOP client errors."""
    pass


class PAOPAPIError(PAOPClientError):
    """Exception raised when the API returns an error."""
    
    def __init__(self, status_code: int, detail: str):
        """Initialize the exception.
        
        Args:
            status_code: HTTP status code
            detail: Error detail
        """
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


class PAOPCommandError(PAOPClientError):
    """Exception raised when a command fails."""
    
    def __init__(self, command_id: str, error: str):
        """Initialize the exception.
        
        Args:
            command_id: ID of the command that failed
            error: Error message
        """
        self.command_id = command_id
        self.error = error
        super().__init__(f"Command {command_id} failed: {error}")


class PAOPConnectionError(PAOPClientError):
    """Exception raised when there is a connection error."""
    pass


class PAOPTimeoutError(PAOPClientError):
    """Exception raised when a request times out."""
    pass


class PAOPClient:
    """Client for interacting with the PAOP API."""
    
    def __init__(
        self, 
        base_url: str = None, 
        api_key: str = None, 
        config: Optional[ClientConfig] = None,
        timeout: int = None,
        verify_ssl: bool = None,
        max_retries: int = None,
        retry_delay: float = None,
    ):
        """Initialize the PAOP client.
        
        Args:
            base_url: Base URL of the PAOP API (e.g., http://localhost:8000)
            api_key: API key for authentication
            config: ClientConfig instance
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
            max_retries: Maximum number of retries for failed requests
            retry_delay: Delay between retries in seconds
        """
        # Use provided config or load from environment
        if config is None:
            if base_url is not None and api_key is not None:
                self.config = ClientConfig(
                    api_url=base_url,
                    api_key=api_key,
                    timeout=timeout or 30,
                    verify_ssl=verify_ssl if verify_ssl is not None else True,
                    max_retries=max_retries or 3,
                    retry_delay=retry_delay or 0.5,
                )
            else:
                self.config = load_client_config()
        else:
            self.config = config
        
        # Override config with explicit parameters if provided
        if base_url is not None:
            self.config.api_url = base_url
        if api_key is not None:
            self.config.api_key = api_key
        if timeout is not None:
            self.config.timeout = timeout
        if verify_ssl is not None:
            self.config.verify_ssl = verify_ssl
        if max_retries is not None:
            self.config.max_retries = max_retries
        if retry_delay is not None:
            self.config.retry_delay = retry_delay
        
        # Ensure the base URL doesn't have a trailing slash
        self.base_url = self.config.api_url.rstrip('/')
        
        # Set headers
        self.headers = {
            "X-API-Key": self.config.api_key,
            "Content-Type": "application/json",
            "User-Agent": f"PAOP-Client/1.0",
        }
    
    async def _make_request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        retry_on_status: List[int] = [429, 502, 503, 504],
    ) -> Dict[str, Any]:
        """Make an HTTP request with retry logic.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (without base URL)
            json_data: JSON data to send
            params: Query parameters
            retry_on_status: HTTP status codes to retry on
            
        Returns:
            Response JSON data
            
        Raises:
            PAOPAPIError: If the API returns an error
            PAOPConnectionError: If there is a connection error
            PAOPTimeoutError: If the request times out
        """
        url = f"{self.base_url}{path}"
        retries = 0
        last_error = None
        
        while retries <= self.config.max_retries:
            try:
                async with httpx.AsyncClient(
                    timeout=self.config.timeout,
                    verify=self.config.verify_ssl,
                ) as client:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=self.headers,
                        json=json_data,
                        params=params,
                    )
                    
                    # Check if the response is a retry candidate
                    if response.status_code in retry_on_status and retries < self.config.max_retries:
                        # Get retry delay from Retry-After header or use default
                        retry_after = response.headers.get("Retry-After")
                        if retry_after and retry_after.isdigit():
                            delay = int(retry_after)
                        else:
                            delay = self.config.retry_delay * (2 ** retries)  # Exponential backoff
                        
                        logger.warning(
                            f"Request failed with status {response.status_code}, "
                            f"retrying in {delay} seconds ({retries+1}/{self.config.max_retries})"
                        )
                        
                        await asyncio.sleep(delay)
                        retries += 1
                        continue
                    
                    # Raise an exception for 4xx and 5xx responses
                    response.raise_for_status()
                    
                    # Return the JSON response
                    return response.json()
                
            except httpx.TimeoutException as e:
                last_error = e
                if retries < self.config.max_retries:
                    delay = self.config.retry_delay * (2 ** retries)
                    logger.warning(
                        f"Request timed out, retrying in {delay} seconds "
                        f"({retries+1}/{self.config.max_retries})"
                    )
                    await asyncio.sleep(delay)
                    retries += 1
                else:
                    logger.error(f"Request timed out after {self.config.max_retries} retries")
                    raise PAOPTimeoutError(f"Request timed out after {self.config.max_retries} retries") from e
            
            except httpx.HTTPStatusError as e:
                # Get error details from response
                status_code = e.response.status_code
                try:
                    detail = e.response.json().get("detail", str(e))
                except (ValueError, json.JSONDecodeError):
                    detail = str(e)
                
                # Log the error
                logger.error(f"API error {status_code}: {detail}")
                
                # Raise a specific exception
                raise PAOPAPIError(status_code, detail) from e
            
            except httpx.HTTPError as e:
                last_error = e
                if retries < self.config.max_retries:
                    delay = self.config.retry_delay * (2 ** retries)
                    logger.warning(
                        f"HTTP error: {str(e)}, retrying in {delay} seconds "
                        f"({retries+1}/{self.config.max_retries})"
                    )
                    await asyncio.sleep(delay)
                    retries += 1
                else:
                    logger.error(f"HTTP error after {self.config.max_retries} retries: {str(e)}")
                    raise PAOPConnectionError(f"HTTP error: {str(e)}") from e
        
        # If we get here, all retries failed
        if last_error:
            raise PAOPConnectionError(f"Request failed after {self.config.max_retries} retries") from last_error
        else:
            raise PAOPConnectionError(f"Request failed after {self.config.max_retries} retries")
    
    async def health_check(self) -> Dict[str, str]:
        """Check the health of the PAOP API.
        
        Returns:
            Health status (e.g., {"status": "ok"})
            
        Raises:
            PAOPAPIError: If the API returns an error
            PAOPConnectionError: If there is a connection error
            PAOPTimeoutError: If the request times out
        """
        return await self._make_request("GET", "/health")
    
    async def send_command(self, command: ExternalCommandRequest) -> ExternalCommandResponse:
        """Send a command to the PAOP API.
        
        Args:
            command: Command to send
            
        Returns:
            Response from the API
            
        Raises:
            PAOPAPIError: If the API returns an error
            PAOPConnectionError: If there is a connection error
            PAOPTimeoutError: If the request times out
            PAOPCommandError: If the command fails
        """
        response_data = await self._make_request("POST", "/command", json_data=command.dict())
        response = ExternalCommandResponse(**response_data)
        
        if response.status == CommandStatus.FAILURE:
            raise PAOPCommandError(response.command_id, response.error or "Unknown error")
        
        return response
    
    async def execute_task(self, agent_id: str, task_data: Dict[str, Any]) -> ExecuteTaskResponse:
        """Execute a task on a specific agent.
        
        Args:
            agent_id: ID of the agent to execute the task on
            task_data: Task data
            
        Returns:
            Response from the API
            
        Raises:
            PAOPAPIError: If the API returns an error
            PAOPConnectionError: If there is a connection error
            PAOPTimeoutError: If the request times out
            PAOPCommandError: If the command fails
        """
        response_data = await self._make_request("POST", f"/tasks/{agent_id}", json_data=task_data)
        response = ExecuteTaskResponse(**response_data)
        
        if response.status == CommandStatus.FAILURE:
            raise PAOPCommandError(response.command_id, response.error or "Unknown error")
        
        return response
    
    async def create_agent(self, agent_config: Dict[str, Any]) -> CreateAgentResponse:
        """Create a new agent.
        
        Args:
            agent_config: Agent configuration
            
        Returns:
            Response from the API
            
        Raises:
            PAOPAPIError: If the API returns an error
            PAOPConnectionError: If there is a connection error
            PAOPTimeoutError: If the request times out
            PAOPCommandError: If the command fails
        """
        response_data = await self._make_request("POST", "/agents", json_data=agent_config)
        response = CreateAgentResponse(**response_data)
        
        if response.status == CommandStatus.FAILURE:
            raise PAOPCommandError(response.command_id, response.error or "Unknown error")
        
        return response
    
    async def list_agents(self) -> Dict[str, Any]:
        """List all agents.
        
        Returns:
            List of agents
            
        Raises:
            PAOPAPIError: If the API returns an error
            PAOPConnectionError: If there is a connection error
            PAOPTimeoutError: If the request times out
        """
        return await self._make_request("GET", "/agents")
    
    async def get_agent_status(self, agent_id: str) -> Dict[str, Any]:
        """Get status of a specific agent.
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            Agent status
            
        Raises:
            PAOPAPIError: If the API returns an error
            PAOPConnectionError: If there is a connection error
            PAOPTimeoutError: If the request times out
        """
        return await self._make_request("GET", f"/agents/{agent_id}")


async def main_async():
    """Async entry point for the command-line tool."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    # Parse arguments
    parser = argparse.ArgumentParser(description="PAOP Client Tool")
    parser.add_argument("--config", help="Path to client configuration file")
    parser.add_argument("--api-url", help="Base URL of the PAOP API (overrides config)")
    parser.add_argument("--api-key", help="API key for authentication (overrides config)")
    parser.add_argument("--timeout", type=int, help="Request timeout in seconds (overrides config)")
    parser.add_argument("--no-verify-ssl", dest="verify_ssl", action="store_false", help="Disable SSL verification")
    
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Health check command
    health_parser = subparsers.add_parser("health", help="Check API health")
    
    # List agents command
    list_agents_parser = subparsers.add_parser("list-agents", help="List all agents")
    
    # Get agent status command
    agent_status_parser = subparsers.add_parser("agent-status", help="Get agent status")
    agent_status_parser.add_argument("agent_id", help="ID of the agent")
    
    # Execute task command
    execute_task_parser = subparsers.add_parser("execute-task", help="Execute a task on an agent")
    execute_task_parser.add_argument("agent_id", help="ID of the agent")
    execute_task_parser.add_argument("task_file", help="Path to JSON file containing task data")
    
    # Create agent command
    create_agent_parser = subparsers.add_parser("create-agent", help="Create a new agent")
    create_agent_parser.add_argument("config_file", help="Path to JSON file containing agent configuration")
    
    # Raw command command
    raw_command_parser = subparsers.add_parser("raw-command", help="Send a raw command")
    raw_command_parser.add_argument("command_file", help="Path to JSON file containing command data")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    try:
        # Load configuration
        if args.config:
            client_config = load_client_config(args.config)
        else:
            client_config = None
        
        # Create client
        client = PAOPClient(
            base_url=args.api_url,
            api_key=args.api_key,
            config=client_config,
            timeout=args.timeout,
            verify_ssl=args.verify_ssl if args.verify_ssl is not None else None,
        )
        
        # Execute command
        if args.command == "health":
            result = await client.health_check()
            print(json.dumps(result, indent=2))
        
        elif args.command == "list-agents":
            result = await client.list_agents()
            print(json.dumps(result, indent=2))
        
        elif args.command == "agent-status":
            result = await client.get_agent_status(args.agent_id)
            print(json.dumps(result, indent=2))
        
        elif args.command == "execute-task":
            # Verify that the task file exists
            if not os.path.exists(args.task_file):
                logger.error(f"Task file not found: {args.task_file}")
                return 1
            
            # Read the task data
            with open(args.task_file, 'r') as f:
                task_data = json.load(f)
            
            result = await client.execute_task(args.agent_id, task_data)
            print(json.dumps(result.dict(), indent=2))
        
        elif args.command == "create-agent":
            # Verify that the config file exists
            if not os.path.exists(args.config_file):
                logger.error(f"Config file not found: {args.config_file}")
                return 1
            
            # Read the agent configuration
            with open(args.config_file, 'r') as f:
                agent_config = json.load(f)
            
            result = await client.create_agent(agent_config)
            print(json.dumps(result.dict(), indent=2))
        
        elif args.command == "raw-command":
            # Verify that the command file exists
            if not os.path.exists(args.command_file):
                logger.error(f"Command file not found: {args.command_file}")
                return 1
            
            # Read the command data
            with open(args.command_file, 'r') as f:
                command_data = json.load(f)
            
            # Generate a command ID if not provided
            if "command_id" not in command_data:
                command_data["command_id"] = str(uuid.uuid4())
            
            command = ExternalCommandRequest(**command_data)
            result = await client.send_command(command)
            print(json.dumps(result.dict(), indent=2))
        
        return 0
    
    except PAOPAPIError as e:
        logger.error(f"API error {e.status_code}: {e.detail}")
        return 1
    
    except PAOPCommandError as e:
        logger.error(f"Command error: {e}")
        return 1
    
    except PAOPConnectionError as e:
        logger.error(f"Connection error: {e}")
        return 1
    
    except PAOPTimeoutError as e:
        logger.error(f"Timeout error: {e}")
        return 1
    
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        return 1
    
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON: {e}")
        return 1
    
    except ValueError as e:
        logger.error(f"Value error: {e}")
        return 1
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


def main():
    """Entry point for the command-line tool."""
    import asyncio
    exit_code = asyncio.run(main_async())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
