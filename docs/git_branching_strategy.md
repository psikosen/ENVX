# Git Branching Strategy

This document outlines the Git branching strategy for the Pedantic Agent Orchestration Platform (PAOP) project.

## Main Branches

- **main**: The production branch. This branch contains code that is ready for deployment to production environments.
  - This branch is protected and requires pull request reviews before merging.
  - Direct commits to `main` are not allowed.

- **develop**: The integration branch. All feature branches are merged into this branch.
  - This branch is used for testing features together before promotion to production.
  - It should always be in a deployable state.

## Supporting Branches

- **feature/\<name\>**: Feature branches are used to develop new features.
  - Always branch from: `develop`
  - Always merge back into: `develop`
  - Naming convention: `feature/add-authentication`, `feature/implement-logging`, etc.

- **hotfix/\<name\>**: Hotfix branches are used to quickly patch production releases.
  - Always branch from: `main`
  - Always merge back into: `main` AND `develop`
  - Naming convention: `hotfix/fix-critical-bug`, `hotfix/security-vulnerability`, etc.

- **release/\<version\>**: Release branches support preparation of a new production release.
  - Always branch from: `develop`
  - Always merge back into: `main` AND `develop`
  - Naming convention: `release/1.0.0`, `release/2.3.1`, etc.

## Commit Messages

Commit messages should follow a consistent format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

Where:

- **type** is one of: feat, fix, docs, style, refactor, test, chore
- **scope** is the area of the code affected (optional)
- **subject** is a short description of the change
- **body** is a detailed description of the change (optional)
- **footer** is for noting breaking changes and referencing issues (optional)

Examples:

```
feat(api): add authentication endpoint

fix(docker): correct environment variable name in Dockerfile

docs: update README with setup instructions
```

## Pull Requests

All code changes should be made through pull requests:

1. Create a branch from `develop` (for features) or `main` (for hotfixes)
2. Make your changes
3. Submit a pull request to the appropriate branch
4. Request reviews from team members
5. Address any feedback
6. Merge once approved

## Tags and Releases

All releases should be tagged with semantic versioning:

- Major.Minor.Patch (e.g., 1.0.0, 1.1.0, 1.1.1)
- Major version for incompatible API changes
- Minor version for new functionality in a backward-compatible manner
- Patch version for backward-compatible bug fixes
