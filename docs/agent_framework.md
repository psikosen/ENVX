# Agent Framework Component

This component is part of the Pedantic Agent Orchestration Platform (PAOP) and provides the core agent implementation, configuration management, and MCP tool integration.

## Key Features

- **Pydantic Models**: Robust data models for agent configuration, task processing, and MCP integration
- **Agent & Orchestrator Classes**: Core agent implementation with specialized orchestrator capabilities
- **MCP Client**: Wrapper for interacting with DesktopCommanderMCP tools
- **Configuration Management**: Flexible configuration loading from files and environment variables
- **Multi-Agent Support**: Supervisor script for running multiple agents in a single container

## Directory Structure

- `src/agent/models/`: Pydantic data models
- `src/agent/agent.py`: Agent and OrchestratorAgent classes
- `src/agent/mcp_client.py`: MCP client wrapper
- `src/agent/config.py`: Configuration loading utilities
- `src/main.py`: Entry point for running a single agent
- `src/supervisor.py`: Script for running multiple agents

## Usage

### Running a Single Agent

```bash
python src/main.py --agent-config /path/to/agent_config.yml --mcp-config /path/to/mcp_config.yml --agent-id my-agent
```

To run as an orchestrator:

```bash
python src/main.py --agent-config /path/to/agent_config.yml --mcp-config /path/to/mcp_config.yml --role orchestrator
```

### Running Multiple Agents with Supervisor

```bash
python src/supervisor.py --config /path/to/supervisor.yml
```

## Testing

To run the unit tests:

```bash
python -m pytest tests/unit/
```

## Configuration Files

### Agent Configuration

```yaml
# Agent identity
agent_id: worker-1
role: worker  # or "orchestrator"
name: Worker Agent 1
description: General-purpose worker agent

# Tools configuration
tools:
  - tool_id: mcp-tool
    tool_type: mcp
    enabled: true
    config:
      timeout_seconds: 30
```

### MCP Configuration

```yaml
mcp:
  enabled: true
  executable_path: /usr/local/bin/desktopcommander-mcp
  config_path: /app/config/mcp
  timeout_seconds: 30
  retry_count: 3
  retry_delay_seconds: 2
  
  environment_variables:
    MCP_LOG_LEVEL: INFO
    MCP_CONFIG_DIR: /app/config/mcp
```

### Supervisor Configuration

```yaml
# Global settings
mcp_config_path: /app/config/mcp_config.yml

# Define agents to run in the container
agents:
  - agent_id: orchestrator-1
    role: orchestrator
    name: Main Orchestrator
    
  - agent_id: worker-1
    role: worker
    name: Worker Agent 1
    
  - agent_id: worker-2
    role: worker
    name: Worker Agent 2
```

## Integration with External Command Interface

The agent framework is designed to be controlled via an external command interface implemented by Developer C. This interface allows for sending tasks to agents and receiving responses.

### Task Types

The agent framework supports the following task types:

- **MCP_COMMAND**: Execute a command via the MCP tool
- **INTERNAL_PROCESS**: Process data internally
- **STATUS_UPDATE**: Update agent status
- **CONFIGURATION_UPDATE**: Update agent configuration

### Task Flow

1. External command is received via the interface
2. Command is converted to a TaskDefinition
3. TaskDefinition is processed by an agent
4. Agent returns a TaskResponse
5. TaskResponse is converted to an external command response

## Future Development

- Implement robust inter-agent communication
- Add plugin/tool architecture for extensibility
- Improve error handling and retry strategies
- Add performance metrics and monitoring
