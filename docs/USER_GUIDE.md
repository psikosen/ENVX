# PAOP User Guide

## Introduction

The Pedantic Agent Orchestration Platform (PAOP) is a system for orchestrating AI agents in a distributed environment. This guide provides detailed instructions on how to use PAOP's API to create agents, assign tasks, and utilize tools like the desktop-commander.

## Table of Contents

1. [System Architecture](#system-architecture)
2. [API Authentication](#api-authentication)
3. [Creating and Managing Agents](#creating-and-managing-agents)
4. [Assigning and Managing Tasks](#assigning-and-managing-tasks)
5. [Using Tools with Agents](#using-tools-with-agents)
6. [Desktop Commander Integration](#desktop-commander-integration)
7. [API Reference](#api-reference)
8. [Troubleshooting](#troubleshooting)

## System Architecture

PAOP follows a modular architecture:

- **External Interface**: A FastAPI service that exposes REST endpoints for client interaction
- **Orchestrator**: Manages agents and processes commands
- **Agents**: Handle specific tasks based on their configuration and capabilities
- **MCP (Message Command Processor)**: Allows agents to interact with external tools like desktop-commander

## API Authentication

All API endpoints (except `/health`) require API key authentication via the `X-API-Key` header.

Example:
```bash
curl -X POST "http://localhost:8000/agents" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secure-key" \
     -d '{"type": "data_processor", "name": "DataProcessor1"}'
```

## Creating and Managing Agents

### Creating a New Agent

To create a new agent, send a POST request to the `/agents` endpoint with the agent configuration.

#### Example Request:
```json
POST /agents
{
  "type": "data_processor",
  "name": "DataProcessorAgent1",
  "capabilities": ["process_csv", "transform_json"],
  "config": {
    "max_memory": "2GB",
    "timeout": 300
  }
}
```

#### Example Response:
```json
{
  "command_id": "cmd-12345",
  "status": "success",
  "result": {
    "message": "Agent created with ID agent-67890",
    "agent_id": "agent-67890"
  },
  "error": null,
  "agent_id": "agent-67890"
}
```

### Listing All Agents

To list all agents, send a GET request to the `/agents` endpoint.

#### Example Request:
```
GET /agents
```

#### Example Response:
```json
{
  "agents": [
    {
      "id": "agent-67890",
      "type": "data_processor",
      "status": "running",
      "config": {
        "type": "data_processor",
        "name": "DataProcessorAgent1",
        "capabilities": ["process_csv", "transform_json"],
        "config": {
          "max_memory": "2GB",
          "timeout": 300
        }
      }
    }
  ]
}
```

### Getting Agent Status

To get the status of a specific agent, send a GET request to the `/agents/{agent_id}` endpoint.

#### Example Request:
```
GET /agents/agent-67890
```

#### Example Response:
```json
{
  "agent_id": "agent-67890",
  "status": {
    "type": "data_processor",
    "status": "running",
    "config": {
      "type": "data_processor",
      "name": "DataProcessorAgent1",
      "capabilities": ["process_csv", "transform_json"],
      "config": {
        "max_memory": "2GB",
        "timeout": 300
      }
    }
  }
}
```

### Deleting an Agent

To delete an agent, send a command to the `/command` endpoint with the `delete_agent` command type.

#### Example Request:
```json
POST /command
{
  "command_id": "cmd-12345",
  "command_type": "delete_agent",
  "target_id": "agent-67890",
  "payload": {}
}
```

#### Example Response:
```json
{
  "command_id": "cmd-12345",
  "status": "success",
  "result": {
    "message": "Agent agent-67890 deleted"
  },
  "error": null
}
```

## Assigning and Managing Tasks

### Executing a Task on an Agent

Tasks can be assigned to agents by sending a POST request to the `/tasks/{agent_id}` endpoint with the task details.

#### Example Task Request (Data Processing):
```json
POST /tasks/agent-67890
{
  "task_type": "process_data",
  "input_data": "sample data to process",
  "parameters": {
    "format": "json",
    "validate": true
  }
}
```

#### Example Task Request (MCP Command for Desktop Actions):
```json
POST /tasks/agent-67890
{
  "task_type": "mcp_command",
  "mcp_server": "desktop-commander",
  "command": "browser",
  "parameters": {
    "action": "open",
    "url": "https://example.com"
  }
}
```

#### Example Response:
```json
{
  "command_id": "task-12345",
  "status": "success",
  "result": {
    "message": "Task created on agent agent-67890",
    "task_id": "task-67890"
  },
  "error": null,
  "task_id": "task-67890"
}
```

### Getting Task Status

To check the status of a task, send a command to the `/command` endpoint with the `get_task_status` command type.

#### Example Request:
```json
POST /command
{
  "command_id": "cmd-12345",
  "command_type": "get_task_status",
  "payload": {
    "task_id": "task-67890"
  }
}
```

#### Example Response:
```json
{
  "command_id": "cmd-12345",
  "status": "success",
  "result": {
    "task_id": "task-67890",
    "status": "completed"
  },
  "error": null
}
```

### Canceling a Task

To cancel a task, send a command to the `/command` endpoint with the `cancel_task` command type.

#### Example Request:
```json
POST /command
{
  "command_id": "cmd-12345",
  "command_type": "cancel_task",
  "payload": {
    "task_id": "task-67890"
  }
}
```

#### Example Response:
```json
{
  "command_id": "cmd-12345",
  "status": "success",
  "result": {
    "message": "Task task-67890 canceled"
  },
  "error": null
}
```

## Using Tools with Agents

Agents can be configured to use different tools through the TaskDefinition. The most common tool is the MCP (Message Command Processor) which allows interaction with external systems like desktop-commander.

### Tool-Specific Task Types

1. **MCP Commands** (`mcp_command`): Execute commands through MCP to control external systems
2. **Internal Processing** (`internal_process`): Process data directly within the agent
3. **Status Updates** (`status_update`): Update agent status
4. **Configuration Updates** (`configuration_update`): Update agent configuration

### Example MCP Task:

```json
{
  "task_id": "task-12345",
  "task_type": "mcp_command",
  "source_agent_id": "agent-orchestrator",
  "target_agent_id": "agent-67890",
  "priority": 1,
  "payload": {
    "mcp_server": "desktop-commander",
    "command": "clipboard",
    "parameters": {
      "action": "write",
      "text": "Example clipboard text"
    }
  },
  "timeout_seconds": 30
}
```

## Desktop Commander Integration

The Desktop Commander tool allows agents to interact with the user's desktop environment, controlling browsers, applications, and system functions.

### Configuration

Desktop Commander is configured by default in the PAOP system through the `mcp_config.yml` file:

```yaml
mcpServers:
  desktop-commander:
    command: npx
    args:
      - -y
      - "@wonderwhy-er/desktop-commander"
```

### Supported Commands

Desktop Commander supports the following command categories:

1. **Browser Control**:
   ```json
   {
     "task_type": "mcp_command",
     "mcp_server": "desktop-commander",
     "command": "browser",
     "parameters": {
       "action": "open",
       "url": "https://example.com"
     }
   }
   ```

2. **Clipboard Management**:
   ```json
   {
     "task_type": "mcp_command",
     "mcp_server": "desktop-commander",
     "command": "clipboard",
     "parameters": {
       "action": "write",
       "text": "Text to copy to clipboard"
     }
   }
   ```

3. **System Control**:
   ```json
   {
     "task_type": "mcp_command",
     "mcp_server": "desktop-commander",
     "command": "system",
     "parameters": {
       "action": "notification",
       "title": "Alert",
       "message": "Task completed successfully"
     }
   }
   ```

4. **File Operations**:
   ```json
   {
     "task_type": "mcp_command",
     "mcp_server": "desktop-commander",
     "command": "file",
     "parameters": {
       "action": "read",
       "path": "/path/to/file.txt"
     }
   }
   ```

### Complete Desktop Commander Actions Reference

#### Browser Actions
- **open**: Opens a URL in the default browser
  ```json
  {"action": "open", "url": "https://example.com"}
  ```
- **search**: Searches for a query in the default search engine
  ```json
  {"action": "search", "query": "search query"}
  ```
- **back**: Navigates back one page
  ```json
  {"action": "back"}
  ```
- **forward**: Navigates forward one page
  ```json
  {"action": "forward"}
  ```
- **refresh**: Refreshes the current page
  ```json
  {"action": "refresh"}
  ```
- **screenshot**: Takes a screenshot of the current page
  ```json
  {"action": "screenshot", "path": "/path/to/save/screenshot.png"}
  ```

#### Clipboard Actions
- **read**: Reads the clipboard contents
  ```json
  {"action": "read"}
  ```
- **write**: Writes text to the clipboard
  ```json
  {"action": "write", "text": "Text to clipboard"}
  ```
- **clear**: Clears the clipboard
  ```json
  {"action": "clear"}
  ```

#### System Actions
- **notification**: Displays a system notification
  ```json
  {"action": "notification", "title": "Title", "message": "Message"}
  ```
- **speak**: Uses text-to-speech to speak text
  ```json
  {"action": "speak", "text": "Hello world"}
  ```
- **shutdown**: Shuts down the computer
  ```json
  {"action": "shutdown"}
  ```
- **restart**: Restarts the computer
  ```json
  {"action": "restart"}
  ```
- **sleep**: Puts the computer to sleep
  ```json
  {"action": "sleep"}
  ```

#### File Actions
- **read**: Reads a file
  ```json
  {"action": "read", "path": "/path/to/file.txt"}
  ```
- **write**: Writes to a file
  ```json
  {"action": "write", "path": "/path/to/file.txt", "content": "File content"}
  ```
- **delete**: Deletes a file
  ```json
  {"action": "delete", "path": "/path/to/file.txt"}
  ```
- **copy**: Copies a file
  ```json
  {"action": "copy", "source": "/path/to/source.txt", "destination": "/path/to/destination.txt"}
  ```
- **move**: Moves a file
  ```json
  {"action": "move", "source": "/path/to/source.txt", "destination": "/path/to/destination.txt"}
  ```

## API Reference

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Root endpoint with API information |
| `/health` | GET | Health check endpoint |
| `/docs` | GET | Swagger UI documentation |
| `/redoc` | GET | ReDoc documentation |
| `/command` | POST | Send a command to the orchestrator |
| `/tasks/{agent_id}` | POST | Execute a task on a specific agent |
| `/agents` | POST | Create a new agent |
| `/agents` | GET | List all agents |
| `/agents/{agent_id}` | GET | Get the status of a specific agent |

### Command Types

| Command Type | Description |
|--------------|-------------|
| `execute_task` | Execute a task on an agent |
| `cancel_task` | Cancel a task that is in progress or pending |
| `get_task_status` | Get the status of a task |
| `create_agent` | Create a new agent |
| `delete_agent` | Delete an agent |
| `list_agents` | List all agents |
| `get_agent_status` | Get the status of an agent |
| `get_system_status` | Get the status of the system |
| `update_configuration` | Update system configuration |

### Task Types

| Task Type | Description |
|-----------|-------------|
| `mcp_command` | Execute a command through MCP (e.g., desktop-commander) |
| `internal_process` | Process data internally within the agent |
| `status_update` | Update agent status |
| `configuration_update` | Update agent configuration |

## Troubleshooting

### Common Issues

1. **Authentication Errors**:
   - Ensure you're providing the correct API key in the `X-API-Key` header
   - Check that the API key matches the one in the configuration or environment variables

2. **Agent Not Found**:
   - Verify the agent ID is correct
   - Check if the agent has been deleted or hasn't been created yet

3. **MCP Tool Errors**:
   - Ensure the MCP tools are properly configured
   - Check that the desktop-commander is installed (`npx -y @wonderwhy-er/desktop-commander`)
   - Verify that the MCP server is enabled in the configuration

4. **Task Execution Failures**:
   - Check the task parameters for correctness
   - Verify that the agent has the required capabilities
   - Check if the task has timed out

### Logging

PAOP logs are available in the console output when running the Docker container. For more verbose logging, set the `PAOP_LOG_LEVEL` environment variable to `DEBUG`.

```bash
docker run -p 8000:8000 -e PAOP_API_KEY="your-secure-key" -e PAOP_LOG_LEVEL=DEBUG paop:dev
```

### Support

For additional support or to report bugs, please create an issue in the GitHub repository or contact the PAOP team.
