"""
Orchestrator client for PAOP.

This module provides a client for communicating with the PAOP orchestrator.
"""
import logging
import asyncio
from typing import Any, Dict, List, Optional, ClassVar

from src.external_interface.models import (
    CommandType,
    CommandStatus,
    ExternalCommandRequest,
    ExternalCommandResponse,
)

logger = logging.getLogger(__name__)


class OrchestratorClient:
    """Client for communicating with the PAOP orchestrator."""
    
    # Class variable to store the singleton instance
    _instance: ClassVar[Optional['OrchestratorClient']] = None
    _initialized: ClassVar[bool] = False
    
    def __new__(cls, *args, **kwargs):
        """Implement singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, max_retries: int = 3, retry_delay: float = 0.5):
        """Initialize the orchestrator client.
        
        Args:
            max_retries: Maximum number of retries for failed commands
            retry_delay: Delay between retries in seconds
        """
        # Only initialize once
        if OrchestratorClient._initialized:
            return
            
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._command_queue = asyncio.Queue()
        self._response_queues = {}
        self._command_processor_task = None
        OrchestratorClient._initialized = True
    
    async def initialize(self):
        """Initialize the client asynchronously.
        
        This method should be called in an async context to properly
        set up the command processor.
        """
        if self._command_processor_task is None:
            # Start the command processor only if it hasn't been started
            self._command_processor_task = asyncio.create_task(self._process_commands())
            logger.debug("Command processor task started")
    
    async def _process_commands(self):
        """Process commands from the queue."""
        logger.debug("Command processor started")
        while True:
            try:
                command, response_queue = await self._command_queue.get()
                try:
                    # Process the command
                    logger.debug(f"Processing command: {command.command_id}")
                    response = await self._execute_command(command)
                    
                    # Put the response in the response queue
                    await response_queue.put(response)
                except Exception as e:
                    logger.error(f"Error processing command: {str(e)}", exc_info=True)
                    # Create error response
                    error_response = ExternalCommandResponse(
                        command_id=command.command_id,
                        status=CommandStatus.FAILURE,
                        error=f"Error processing command: {str(e)}",
                    )
                    await response_queue.put(error_response)
                finally:
                    self._command_queue.task_done()
            except Exception as e:
                logger.error(f"Unhandled exception in command processor: {str(e)}", exc_info=True)
                # Continue processing other commands
                await asyncio.sleep(1)
    
    async def _execute_command(self, command: ExternalCommandRequest) -> ExternalCommandResponse:
        """Execute a command on the orchestrator.
        
        This is where the actual communication with the orchestrator happens.
        In a real implementation, this would send the command to the orchestrator
        and wait for the response.
        """
        # Integrate with Developer B's agent framework here
        from .orchestrator import process_command
        return await process_command(command)
    
    async def send_command(self, command: ExternalCommandRequest) -> ExternalCommandResponse:
        """Send a command to the orchestrator.
        
        Args:
            command: The command to send
            
        Returns:
            The response from the orchestrator
        """
        # Ensure the client is initialized
        await self.initialize()
        
        logger.info(f"Sending command to orchestrator: {command.command_type} (ID: {command.command_id})")
        
        # Create a response queue for this command
        response_queue = asyncio.Queue()
        self._response_queues[command.command_id] = response_queue
        
        # Put the command in the queue
        await self._command_queue.put((command, response_queue))
        
        # Wait for the response
        response = await response_queue.get()
        
        # Clean up
        del self._response_queues[command.command_id]
        
        return response

# Create a single instance for the application
_client_instance = OrchestratorClient()

async def get_client_instance():
    """Get and initialize the client instance.
    
    Returns:
        An initialized OrchestratorClient instance
    """
    await _client_instance.initialize()
    return _client_instance
