#!/bin/bash
# Initialize Git repository for PAOP project

echo "Initializing Git repository for PAOP project..."

# Initialize the repository
git init

# Add all files
git add .

# Make initial commit
git commit -m "Initial commit for PAOP project"

# Create develop branch
git checkout -b develop

# Show current status
echo -e "\nCurrent Git status:"
git status

# Show branches
echo -e "\nGit branches:"
git branch

echo -e "\nGit repository has been initialized with both main and develop branches."
echo "Please run the following command to make the repository accessible to other team members:"
echo "git remote add origin <your-remote-repository-url>"
echo "git push -u origin main"
echo "git push -u origin develop"
