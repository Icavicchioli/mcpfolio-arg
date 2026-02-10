# Dependency Management Guide

## Overview

This project uses modern Python packaging standards with pinned dependencies for reproducible builds.

## Files

- **`pyproject.toml`** - Modern Python project configuration (PEP 621)
- **`requirements.txt`** - Production dependencies with exact versions
- **`requirements-dev.txt`** - Development dependencies with exact versions
- **`.python-version`** - Python version specification (3.11.14)

## Installation

### Production Environment

```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install production dependencies
pip install -r requirements.txt
```

### Development Environment

```bash
# Install all development tools
pip install -r requirements-dev.txt

# Or install with optional dependencies from pyproject.toml
pip install -e ".[dev]"
```

## Dependency Groups

### Core Production Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| langgraph | 1.0.7 | State machine orchestration |
| langchain-core | 1.2.7 | LangChain framework |
| langchain-ollama | 1.0.1 | Ollama integration |
| langchain-mcp-adapters | 0.2.1 | MCP to LangChain adapter |
| mcp | 1.26.0 | Model Context Protocol |
| fastmcp | 2.14.4 | Fast MCP server framework |
| yfinance | 1.1.0 | Financial data from Yahoo Finance |
| pandas | 3.0.0 | Data manipulation |
| structlog | 25.5.0 | Structured logging |
| python-json-logger | 4.0.0 | JSON log formatting |

### Development Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| pytest | 9.0.2 | Testing framework |
| pytest-asyncio | 1.3.0 | Async test support |
| pytest-cov | 7.0.0 | Code coverage |
| pytest-mock | 3.15.1 | Mocking utilities |
| black | 24.10.0 | Code formatter |
| ruff | 0.8.5 | Fast linter |
| mypy | 1.14.1 | Static type checker |
| pre-commit | 4.0.1 | Git hooks manager |

## Updating Dependencies

### Check for Updates

```bash
# List outdated packages
pip list --outdated

# Check specific package
pip show langgraph
```

### Update a Single Package

```bash
# Update and test
pip install --upgrade langgraph==<new-version>
pytest tests/

# If tests pass, update requirements.txt
pip freeze | grep langgraph > temp.txt
```

### Update All Dependencies

**⚠️ CAUTION:** Test thoroughly before deploying!

```bash
# Create backup
cp requirements.txt requirements.txt.bak

# Update all to latest compatible versions
pip install --upgrade -r requirements.txt

# Generate new pinned requirements
pip freeze > requirements.txt

# Run full test suite
pytest tests/ --cov=src

# If tests fail, restore backup
mv requirements.txt.bak requirements.txt
pip install -r requirements.txt
```

### Using Dependabot

GitHub Dependabot is configured to automatically:
- Check for updates weekly (Mondays at 9 AM UTC)
- Create PRs for security updates
- Update GitHub Actions versions

See `.github/dependabot.yml` for configuration.

## Version Pinning Strategy

### Production Dependencies

**Exact pinning** (`==`) for:
- Core framework dependencies (langgraph, langchain-*)
- Financial data libraries (yfinance, pandas)
- All dependencies to ensure reproducibility

### Development Dependencies

**Exact pinning** (`==`) for:
- Testing frameworks
- Code quality tools
- Type checkers

### Rationale

1. **Reproducibility**: Exact versions ensure identical behavior across environments
2. **Security**: Known versions can be audited and scanned
3. **Stability**: Prevents unexpected breaking changes
4. **Testing**: Changes are deliberate and tested

## Security

### Vulnerability Scanning

```bash
# Install safety
pip install safety

# Check for known vulnerabilities
safety check

# Check with detailed output
safety check --json --output safety-report.json
```

### Automated Scanning

- **CI Pipeline**: Runs `safety check` on every push
- **Dependabot**: Automatically opens PRs for security updates
- **Pre-commit**: Can run safety checks before commits

## Troubleshooting

### Dependency Conflicts

```bash
# Check for conflicts
pip check

# Resolve with pip-tools
pip install pip-tools
pip-compile pyproject.toml
```

### Version Mismatches

```bash
# Reinstall from requirements.txt
pip uninstall -r requirements.txt -y
pip install -r requirements.txt
```

### Cache Issues

```bash
# Clear pip cache
pip cache purge

# Reinstall without cache
pip install --no-cache-dir -r requirements.txt
```

## Best Practices

1. **Always pin versions** in requirements.txt
2. **Test before updating** - run full test suite
3. **Update regularly** but deliberately
4. **Review changelogs** before major version bumps
5. **Use virtual environments** to isolate dependencies
6. **Document breaking changes** in commit messages
7. **Keep security updates current** - don't ignore Dependabot PRs

## Compatibility

### Python Versions

- **Required**: Python 3.11 or 3.12
- **Tested**: 3.11.14 (primary), 3.12.x
- **Not supported**: Python 3.10 or earlier, Python 3.13+

### Operating Systems

- **Linux**: Primary development platform
- **macOS**: Fully supported
- **Windows**: Compatible (use WSL2 for best experience)

## CI/CD Integration

Dependencies are automatically verified in CI:

```yaml
# .github/workflows/ci.yml
- name: Install dependencies
  run: |
    pip install -r requirements.txt
    pip install -r requirements-dev.txt
```

See `.github/workflows/` for complete CI configuration.
