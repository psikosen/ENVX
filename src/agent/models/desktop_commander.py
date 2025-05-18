"""
Desktop Commander specific models for the PAOP system.

These models provide a strongly-typed interface for interacting with the 
Desktop Commander tool through the MCP.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union, Literal
from pydantic import BaseModel, Field, validator


class BrowserAction(str, Enum):
    """Supported browser actions for Desktop Commander."""
    
    OPEN = "open"
    SEARCH = "search"
    BACK = "back"
    FORWARD = "forward"
    REFRESH = "refresh"
    SCREENSHOT = "screenshot"


class BrowserCommandParams(BaseModel):
    """Parameters for browser commands."""
    
    action: BrowserAction = Field(..., description="Browser action to perform")
    url: Optional[str] = Field(None, description="URL to open or navigate to")
    query: Optional[str] = Field(None, description="Search query")
    path: Optional[str] = Field(None, description="Path to save screenshot")
    
    @validator('url')
    def validate_url_for_open(cls, v, values):
        """Validate that URL is provided for open action."""
        if values.get('action') == BrowserAction.OPEN and not v:
            raise ValueError("url is required for 'open' action")
        return v
    
    @validator('query')
    def validate_query_for_search(cls, v, values):
        """Validate that query is provided for search action."""
        if values.get('action') == BrowserAction.SEARCH and not v:
            raise ValueError("query is required for 'search' action")
        return v
    
    @validator('path')
    def validate_path_for_screenshot(cls, v, values):
        """Validate that path is provided for screenshot action."""
        if values.get('action') == BrowserAction.SCREENSHOT and not v:
            raise ValueError("path is required for 'screenshot' action")
        return v


class ClipboardAction(str, Enum):
    """Supported clipboard actions for Desktop Commander."""
    
    READ = "read"
    WRITE = "write"
    CLEAR = "clear"


class ClipboardCommandParams(BaseModel):
    """Parameters for clipboard commands."""
    
    action: ClipboardAction = Field(..., description="Clipboard action to perform")
    text: Optional[str] = Field(None, description="Text to write to clipboard")
    
    @validator('text')
    def validate_text_for_write(cls, v, values):
        """Validate that text is provided for write action."""
        if values.get('action') == ClipboardAction.WRITE and not v:
            raise ValueError("text is required for 'write' action")
        return v


class SystemAction(str, Enum):
    """Supported system actions for Desktop Commander."""
    
    NOTIFICATION = "notification"
    SPEAK = "speak"
    SHUTDOWN = "shutdown"
    RESTART = "restart"
    SLEEP = "sleep"


class SystemCommandParams(BaseModel):
    """Parameters for system commands."""
    
    action: SystemAction = Field(..., description="System action to perform")
    title: Optional[str] = Field(None, description="Title for notification")
    message: Optional[str] = Field(None, description="Message for notification")
    text: Optional[str] = Field(None, description="Text to speak")
    
    @validator('title', 'message')
    def validate_notification_params(cls, v, values, **kwargs):
        """Validate notification parameters."""
        field_name = kwargs['field'].name
        if values.get('action') == SystemAction.NOTIFICATION:
            if field_name in ('title', 'message') and not v:
                raise ValueError(f"{field_name} is required for 'notification' action")
        return v
    
    @validator('text')
    def validate_text_for_speak(cls, v, values):
        """Validate that text is provided for speak action."""
        if values.get('action') == SystemAction.SPEAK and not v:
            raise ValueError("text is required for 'speak' action")
        return v


class FileAction(str, Enum):
    """Supported file actions for Desktop Commander."""
    
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    COPY = "copy"
    MOVE = "move"


class FileCommandParams(BaseModel):
    """Parameters for file commands."""
    
    action: FileAction = Field(..., description="File action to perform")
    path: Optional[str] = Field(None, description="Path to the file")
    content: Optional[str] = Field(None, description="Content to write to file")
    source: Optional[str] = Field(None, description="Source path for copy/move")
    destination: Optional[str] = Field(None, description="Destination path for copy/move")
    
    @validator('path')
    def validate_path(cls, v, values):
        """Validate that path is provided for certain actions."""
        if values.get('action') in (FileAction.READ, FileAction.WRITE, FileAction.DELETE) and not v:
            raise ValueError(f"path is required for '{values.get('action')}' action")
        return v
    
    @validator('content')
    def validate_content_for_write(cls, v, values):
        """Validate that content is provided for write action."""
        if values.get('action') == FileAction.WRITE and not v:
            raise ValueError("content is required for 'write' action")
        return v
    
    @validator('source', 'destination')
    def validate_source_destination(cls, v, values, **kwargs):
        """Validate source and destination for copy/move actions."""
        field_name = kwargs['field'].name
        if values.get('action') in (FileAction.COPY, FileAction.MOVE):
            if field_name in ('source', 'destination') and not v:
                raise ValueError(f"{field_name} is required for '{values.get('action')}' action")
        return v


class DesktopCommanderCommand(BaseModel):
    """Command to be sent to Desktop Commander MCP server."""
    
    command: Literal["browser", "clipboard", "system", "file"] = Field(
        ..., description="Command category"
    )
    parameters: Union[
        BrowserCommandParams, 
        ClipboardCommandParams, 
        SystemCommandParams, 
        FileCommandParams
    ] = Field(..., description="Command parameters")
    
    @validator('parameters')
    def validate_parameters_type(cls, v, values):
        """Validate that the parameters match the command type."""
        command = values.get('command')
        if command == "browser" and not isinstance(v, BrowserCommandParams):
            raise ValueError("parameters must be BrowserCommandParams for 'browser' command")
        elif command == "clipboard" and not isinstance(v, ClipboardCommandParams):
            raise ValueError("parameters must be ClipboardCommandParams for 'clipboard' command")
        elif command == "system" and not isinstance(v, SystemCommandParams):
            raise ValueError("parameters must be SystemCommandParams for 'system' command")
        elif command == "file" and not isinstance(v, FileCommandParams):
            raise ValueError("parameters must be FileCommandParams for 'file' command")
        return v


class MCPDesktopCommanderTask(BaseModel):
    """Task definition for executing a Desktop Commander command through MCP."""
    
    task_type: Literal["mcp_command"] = Field("mcp_command", description="Type of task")
    mcp_server: Literal["desktop-commander"] = Field(
        "desktop-commander", description="MCP server to use"
    )
    command: Literal["browser", "clipboard", "system", "file"] = Field(
        ..., description="Command category"
    )
    parameters: Dict[str, Any] = Field(..., description="Command-specific parameters")
