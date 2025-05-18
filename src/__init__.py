# Initialize the __init__.py file to make 'src' a proper package
# This helps with imports in both local and Docker environments

__all__ = ["agent", "agent_framework", "external_interface"]# This file makes the src directory a Python package