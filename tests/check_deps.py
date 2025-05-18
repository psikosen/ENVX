"""
Verify PAOP dependencies installation.

This script checks if all required dependencies are installed and reports any
missing packages.
"""
import sys
import subprocess
import importlib.util


def check_package(package_name):
    """Check if a package is installed."""
    spec = importlib.util.find_spec(package_name)
    return spec is not None


def print_status(package_name, installed):
    """Print the status of a package."""
    status = "INSTALLED" if installed else "MISSING"
    status_color = "\033[92m" if installed else "\033[91m"  # Green if installed, red if missing
    print(f"{status_color}{status}\033[0m - {package_name}")


def main():
    """Check all required dependencies."""
    packages = [
        # Core packages
        "fastapi", 
        "pydantic", 
        "uvicorn", 
        "httpx",
        
        # Testing packages
        "pytest",
        "pytest-asyncio",
        
        # Utils
        "structlog",
    ]
    
    print("===== Checking PAOP External Interface Dependencies =====")
    
    missing = []
    for package in packages:
        installed = check_package(package)
        print_status(package, installed)
        if not installed:
            missing.append(package)
    
    print("\n===== Summary =====")
    if missing:
        print(f"\033[91mMissing {len(missing)} packages:\033[0m")
        print(f"Run: pip install -r requirements-external.txt")
    else:
        print(f"\033[92mAll required packages are installed!\033[0m")
    
    return len(missing)


if __name__ == "__main__":
    sys.exit(main())
