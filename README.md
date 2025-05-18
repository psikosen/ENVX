## Documentation

For detailed instructions on using PAOP, please refer to the following documentation:

- [Quick Start Guide](./docs/QUICK_START.md) - Get started quickly with PAOP
- [LLM and Desktop Tools Guide](./docs/LLM_DESKTOP_TOOLS.md) - Learn how to use LLMs and desktop tools
- [User Guide](./docs/USER_GUIDE.md) - Comprehensive documentation on using PAOP
- [API Documentation](http://localhost:8000/docs) - Interactive API documentation (when running)

# PAOP - Pedantic Agent Orchestration Platform

## Overview
PAOP is a platform for orchestrating AI agents in a distributed environment.
  
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
