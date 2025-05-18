# PAOP Quick Start Guide

This guide provides a quick overview of how to use the Pedantic Agent Orchestration Platform (PAOP) to create agents, assign tasks, and use the desktop-commander tool.

## Starting the System

```bash
# Start the system using docker-compose
docker-compose up --build
```

## Creating an Agent

```bash
curl -X POST "http://localhost:8000/agents" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secure-key" \
     -d '{
       "type": "desktop_agent",
       "name": "DesktopControlAgent",
       "capabilities": ["browser_control", "file_operations"]
     }'
```

Response (save the agent_id for later use):
```json
{
  "command_id": "cmd-12345",
  "status": "success",
  "result": {
    "message": "Agent created with ID agent-67890",
    "agent_id": "agent-67890"
  },
  "agent_id": "agent-67890"
}
```

## Using Desktop Commander

### Open a Website

```bash
curl -X POST "http://localhost:8000/tasks/agent-67890" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secure-key" \
     -d '{
       "task_type": "mcp_command",
       "mcp_server": "desktop-commander",
       "command": "browser",
       "parameters": {
         "action": "open",
         "url": "https://example.com"
       }
     }'
```

### Copy Text to Clipboard

```bash
curl -X POST "http://localhost:8000/tasks/agent-67890" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secure-key" \
     -d '{
       "task_type": "mcp_command",
       "mcp_server": "desktop-commander",
       "command": "clipboard",
       "parameters": {
         "action": "write",
         "text": "Example text to copy to clipboard"
       }
     }'
```

### Show a System Notification

```bash
curl -X POST "http://localhost:8000/tasks/agent-67890" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secure-key" \
     -d '{
       "task_type": "mcp_command",
       "mcp_server": "desktop-commander",
       "command": "system",
       "parameters": {
         "action": "notification",
         "title": "PAOP Alert",
         "message": "This is a notification from PAOP"
       }
     }'
```

### Read a File

```bash
curl -X POST "http://localhost:8000/tasks/agent-67890" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secure-key" \
     -d '{
       "task_type": "mcp_command",
       "mcp_server": "desktop-commander",
       "command": "file",
       "parameters": {
         "action": "read",
         "path": "/path/to/your/file.txt"
       }
     }'
```

## Using the Swagger UI

For a more interactive experience, you can use the Swagger UI:

1. Open `http://localhost:8000/docs` in your browser
2. Click the "Authorize" button and enter `your-secure-key` for the X-API-Key
3. Try out the various endpoints with the provided examples

## Next Steps

For detailed documentation, see the [User Guide](./USER_GUIDE.md).
