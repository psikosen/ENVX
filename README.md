## Documentation

For detailed instructions on using PAOP, please refer to the following documentation:

- [Quick Start Guide](./docs/QUICK_START.md) - Get started quickly with PAOP
- [LLM and Desktop Tools Guide](./docs/LLM_DESKTOP_TOOLS.md) - Learn how to use LLMs and desktop tools
- [User Guide](./docs/USER_GUIDE.md) - Comprehensive documentation on using PAOP
- [API Documentation](http://localhost:8000/docs) - Interactive API documentation (when running)

# PAOP - Pedantic Agent Orchestration Platform

## Overview
PAOP is a platform for orchestrating AI agents in a distributed environment.

## Issues Resolution

### Import Error
The application was encountering an import error:
```
ImportError: cannot import name 'OrchestratorClient' from 'src.agent_framework.orchestrator'
```

This occurred because:
1. `src/external_interface/api.py` was trying to import `OrchestratorClient` from `src.agent_framework.orchestrator`
2. The class `OrchestratorClient` was defined in `src/agent_framework/orchestrator_client.py`, not in `orchestrator.py`

#### Solution
The issue was resolved by adding an import statement in `orchestrator.py` to import and re-export the `OrchestratorClient` class:

```python
# Import and re-export the OrchestratorClient to fix the circular import issue
from .orchestrator_client import OrchestratorClient
```

### Async Error
After fixing the import error, the application encountered an event loop error:
```
RuntimeError: no running event loop
```

This occurred because:
1. The `OrchestratorClient` class was trying to start a background task in its constructor using `asyncio.create_task()`
2. FastAPI was initializing the client in a non-asyncio context through its dependency system

#### Solution
The issue was resolved by:
1. Refactoring the `OrchestratorClient` class to use proper async initialization
2. Implementing a singleton pattern with async initialization
3. Updating the FastAPI dependency to use the async initialization

```python
# In orchestrator_client.py
async def get_client_instance():
    """Get and initialize the client instance."""
    await _client_instance.initialize()
    return _client_instance

# In api.py
async def get_orchestrator_client():
    """Dependency for getting the orchestrator client."""
    return await get_client_instance()
```

## Running the Application

### Using Docker
```bash
# Build and run with docker-compose
docker-compose up --build

# Or using Docker directly
docker build -t paop:dev .
docker run -p 8000:8000 -e PAOP_API_KEY="your-secure-key" paop:dev
```

### API Endpoints
The API exposes the following endpoints:

- `GET /health` - Health check endpoint
- `POST /command` - Send a command to the orchestrator
- `POST /tasks/{agent_id}` - Execute a task on a specific agent
- `POST /agents` - Create a new agent
- `GET /agents` - List all agents
- `GET /agents/{agent_id}` - Get the status of a specific agent

All endpoints (except `/health`) require API key authentication via the `X-API-Key` header.

### Swagger Documentation
To make the API easier to use, we've added comprehensive Swagger documentation including:

1. Request body examples for all endpoints
2. Response models with examples
3. Interactive documentation available at:
   - `/docs` - Swagger UI
   - `/redoc` - ReDoc UI

#### How to Use the Swagger UI
1. Navigate to `http://localhost:8000/docs`
2. Click on an endpoint to expand it
3. Click on "Try it out" to test the endpoint
4. Use the provided examples or modify them as needed
5. For authenticated endpoints, you need to click the "Authorize" button and enter `your-secure-key` for the `X-API-Key` header

## Development

### Project Structure
```
/app
├── config/         # Configuration files
├── scripts/        # Utility scripts
└── src/
    ├── agent_framework/
    │   ├── orchestrator.py          # Orchestrator implementation
    │   └── orchestrator_client.py   # Orchestrator client
    └── external_interface/
        ├── api.py                   # FastAPI implementation
        ├── config.py                # API configuration
        ├── main.py                  # Entry point
        └── models.py                # API models
```

### Notes for Future Development
1. The orchestrator and client implementations should be reviewed to ensure they don't have circular dependencies
2. Consider refactoring to a cleaner architecture with clear separation of concerns
3. Add more thorough testing, especially for API endpoints and orchestrator functionality
