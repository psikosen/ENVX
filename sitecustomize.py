"""
This module is automatically imported by Python on startup.
It adds the necessary paths to sys.path to ensure proper imports in the Docker container.
"""
import sys
import os

# Add the /app directory to the Python path
if '/app' not in sys.path:
    sys.path.insert(0, '/app')
