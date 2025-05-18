# PAOP Quick Start Guide for LLM and Desktop Tools

This guide shows how to use PAOP with LLM providers (Ollama, Gemini) and the Desktop Commander tool.

## Starting the System

```bash
# Create a .env file with your API keys (optional)
cp .env.example .env
# Edit the .env file to add your API keys

# Start the system using docker-compose
docker-compose up --build
```

## Managing Ollama Models

### List Available Models

```bash
curl -X GET "http://localhost:8000/ollama/models" \
     -H "X-API-Key: your-secure-key"
```

### Pull a New Model

```bash
curl -X POST "http://localhost:8000/ollama/models/pull" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secure-key" \
     -d '{
       "name": "llama3"
     }'
```

## Creating an LLM Agent

```bash
curl -X POST "http://localhost:8000/agents" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secure-key" \
     -d '{
       "type": "llm_agent",
       "name": "TextGenerationAgent",
       "capabilities": ["text_generation", "code_generation"],
       "config": {
         "llm_provider": "ollama",
         "model_name": "llama3",
         "default_prompt_template": "You are a helpful assistant. Answer the following query: {query}"
       }
     }'
```

## Creating a Desktop Agent with LLM Integration

```bash
curl -X POST "http://localhost:8000/agents" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secure-key" \
     -d '{
       "type": "desktop_agent",
       "name": "DesktopCommanderAgent",
       "capabilities": ["browser_control", "clipboard_management", "system_control"],
       "config": {
         "mcp_server": "desktop-commander",
         "llm_provider": "gemini",
         "model_name": "gemini-pro",
         "default_prompt_template": "You are a helpful assistant that controls the desktop. Perform the following task: {task}"
       }
     }'
```

Save the agent_id for use in the next steps.

## Sending Tasks to the LLM Agent

### Text Generation Task

```bash
curl -X POST "http://localhost:8000/tasks/AGENT_ID" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secure-key" \
     -d '{
       "task_type": "llm_request",
       "model_config": {
         "provider": "ollama",
         "model_name": "llama3",
         "temperature": 0.7
       },
       "request_payload": {
         "prompt": "Explain the concept of recursion in programming."
       }
     }'
```

### Code Generation Task

```bash
curl -X POST "http://localhost:8000/tasks/AGENT_ID" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secure-key" \
     -d '{
       "task_type": "llm_request",
       "model_config": {
         "provider": "ollama",
         "model_name": "llama3",
         "temperature": 0.2
       },
       "request_payload": {
         "prompt": "Write a Python function to calculate the Fibonacci sequence."
       }
     }'
```

## Using Desktop Commander with Natural Language

```bash
curl -X POST "http://localhost:8000/tasks/AGENT_ID" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secure-key" \
     -d '{
       "task_type": "llm_request",
       "model_config": {
         "provider": "gemini",
         "model_name": "gemini-pro",
         "temperature": 0.2
       },
       "request_payload": {
         "prompt": "Open the website example.com in my browser"
       },
       "use_tools": true,
       "tool_configs": [
         {
           "tool_id": "desktop-commander",
           "tool_type": "mcp",
           "enabled": true
         }
       ]
     }'
```

## Direct Desktop Commander Tasks

### Open a Website

```bash
curl -X POST "http://localhost:8000/tasks/AGENT_ID" \
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

### System Notification

```bash
curl -X POST "http://localhost:8000/tasks/AGENT_ID" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secure-key" \
     -d '{
       "task_type": "mcp_command",
       "mcp_server": "desktop-commander",
       "command": "system",
       "parameters": {
         "action": "notification",
         "title": "Task Completed",
         "message": "Your task has been completed successfully!"
       }
     }'
```

## Using the Swagger UI

For a more interactive experience, you can use the Swagger UI:

1. Open `http://localhost:8000/docs` in your browser
2. Click the "Authorize" button and enter `your-secure-key` for the X-API-Key
3. Try out the various endpoints with the provided examples
