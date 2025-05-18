#!/bin/bash
# Make all scripts executable

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Make all scripts executable
chmod +x $DIR/*.sh

echo "All scripts in $DIR are now executable."
