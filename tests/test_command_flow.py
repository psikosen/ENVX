"""
End-to-end test for the PAOP command flow.

This script tests the complete flow of sending commands to the PAOP API and
receiving responses. It requires a running PAOP container with the API server.
"""
import os
import sys
import json
import asyncio
import argparse
import logging
from typing import Dict, Any

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from external_interface.client import PAOPClient
from external_interface.models import CommandType, CommandStatus

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def test_health_check(client: PAOPClient) -> bool:
    """Test the health check endpoint."""
    try:
        logger.info("Testing health check...")
        result = await client.health_check()
        if result.get("status") == "ok":
            logger.info("Health check passed")
            return True
        else:
            logger.error(f"Health check failed: {result}")
            return False
    except Exception as e:
        logger.error(f"Health check failed with exception: {str(e)}")
        return False


async def test_create_agent(client: PAOPClient) -> Dict[str, Any]:
    """Test creating an agent."""
    try:
        logger.info("Testing agent creation...")
        agent_config = {
            "type": "test_agent",
            "name": "Test Agent",
            "capabilities": ["test"],
        }
        
        result = await client.create_agent(agent_config)
        if result.status == CommandStatus.SUCCESS and result.agent_id:
            logger.info(f"Agent created successfully with ID: {result.agent_id}")
            return {"success": True, "agent_id": result.agent_id}
        else:
            logger.error(f"Agent creation failed: {result.error}")
            return {"success": False, "error": result.error}
    except Exception as e:
        logger.error(f"Agent creation failed with exception: {str(e)}")
        return {"success": False, "error": str(e)}


async def test_execute_task(client: PAOPClient, agent_id: str) -> Dict[str, Any]:
    """Test executing a task on an agent."""
    try:
        logger.info(f"Testing task execution on agent {agent_id}...")
        task_data = {
            "task_type": "test_task",
            "parameters": {
                "test_param": "test_value",
            },
        }
        
        result = await client.execute_task(agent_id, task_data)
        if result.status == CommandStatus.SUCCESS:
            logger.info(f"Task executed successfully with ID: {result.task_id}")
            return {"success": True, "task_id": result.task_id}
        else:
            logger.error(f"Task execution failed: {result.error}")
            return {"success": False, "error": result.error}
    except Exception as e:
        logger.error(f"Task execution failed with exception: {str(e)}")
        return {"success": False, "error": str(e)}


async def test_agent_status(client: PAOPClient, agent_id: str) -> Dict[str, Any]:
    """Test getting agent status."""
    try:
        logger.info(f"Testing getting status for agent {agent_id}...")
        result = await client.get_agent_status(agent_id)
        if "error" not in result:
            logger.info(f"Agent status retrieved successfully: {result}")
            return {"success": True, "status": result}
        else:
            logger.error(f"Getting agent status failed: {result['error']}")
            return {"success": False, "error": result['error']}
    except Exception as e:
        logger.error(f"Getting agent status failed with exception: {str(e)}")
        return {"success": False, "error": str(e)}


async def test_list_agents(client: PAOPClient) -> Dict[str, Any]:
    """Test listing all agents."""
    try:
        logger.info("Testing listing all agents...")
        result = await client.list_agents()
        if "error" not in result:
            logger.info(f"Agents listed successfully: {result}")
            return {"success": True, "agents": result.get("agents", [])}
        else:
            logger.error(f"Listing agents failed: {result['error']}")
            return {"success": False, "error": result['error']}
    except Exception as e:
        logger.error(f"Listing agents failed with exception: {str(e)}")
        return {"success": False, "error": str(e)}


async def run_all_tests(api_url: str, api_key: str) -> Dict[str, Any]:
    """Run all tests."""
    client = PAOPClient(api_url, api_key)
    results = {}
    
    # Test health check
    results["health_check"] = await test_health_check(client)
    if not results["health_check"]:
        logger.error("Health check failed, skipping remaining tests")
        return results
    
    # Test create agent
    agent_result = await test_create_agent(client)
    results["create_agent"] = agent_result.get("success", False)
    
    if agent_result.get("success", False):
        agent_id = agent_result["agent_id"]
        
        # Test execute task
        task_result = await test_execute_task(client, agent_id)
        results["execute_task"] = task_result.get("success", False)
        
        # Test agent status
        status_result = await test_agent_status(client, agent_id)
        results["agent_status"] = status_result.get("success", False)
    
    # Test list agents (should work regardless of agent creation)
    list_result = await test_list_agents(client)
    results["list_agents"] = list_result.get("success", False)
    
    return results


async def main_async():
    """Async entry point for the test script."""
    parser = argparse.ArgumentParser(description="PAOP End-to-End Test")
    parser.add_argument("--api-url", required=True, help="Base URL of the PAOP API")
    parser.add_argument("--api-key", required=True, help="API key for authentication")
    
    args = parser.parse_args()
    
    # Run all tests
    results = await run_all_tests(args.api_url, args.api_key)
    
    # Print summary
    logger.info("Test Results Summary:")
    for test, result in results.items():
        logger.info(f"  {test}: {'PASS' if result else 'FAIL'}")
    
    # Exit with success if all tests passed
    if all(results.values()):
        logger.info("All tests passed")
        return 0
    else:
        logger.error("Some tests failed")
        return 1


def main():
    """Entry point for the test script."""
    exit_code = asyncio.run(main_async())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
