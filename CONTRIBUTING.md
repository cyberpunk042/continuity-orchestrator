# Contributing to Continuity Orchestrator

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

---

## Table of Contents

1. [Code of Conduct](#code-of-conduct)
2. [Getting Started](#getting-started)
3. [Development Setup](#development-setup)
4. [Making Changes](#making-changes)
5. [Testing](#testing)
6. [Submitting Changes](#submitting-changes)
7. [Style Guidelines](#style-guidelines)
8. [Architecture Overview](#architecture-overview)

---

## Code of Conduct

This project follows a simple standard:
- Be respectful and constructive
- Focus on the work, not the person
- Help others learn and grow

---

## Getting Started

### Prerequisites

- Python 3.11+
- Git
- (Optional) Docker for testing containers

### First-Time Setup

```bash
# Clone the repository
git clone https://github.com/cyberpunk042/continuity-orchestrator.git
cd continuity-orchestrator

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in development mode
pip install -e ".[dev]"

# Verify setup
pytest --collect-only  # Should show 255+ tests
```

---

## Development Setup

### Project Structure

```
continuity-orchestrator/
├── src/                    # Main source code
│   ├── main.py             # CLI entry point
│   ├── adapters/           # Integration adapters (email, SMS, etc.)
│   ├── engine/             # Core tick engine
│   ├── models/             # Data models (Pydantic)
│   ├── policy/             # Policy loading and evaluation
│   ├── site/               # Static site generator
│   └── templates/          # Template resolution
│
├── policy/                 # Default policy configuration
├── templates/              # Message and site templates
├── tests/                  # Test suite
├── docs/                   # Documentation
├── examples/               # Example configurations
└── scripts/                # Helper scripts
```

### Key Components

| Component | Purpose | Location |
|-----------|---------|----------|
| **Tick Engine** | Core execution loop | `src/engine/tick.py` |
| **State Model** | Pydantic state schema | `src/models/state.py` |
| **Policy Loader** | YAML policy parsing | `src/policy/loader.py` |
| **Adapter Registry** | Integration dispatch | `src/adapters/registry.py` |
| **Site Generator** | Static HTML output | `src/site/generator.py` |

---

## Making Changes

### Branch Naming

Use descriptive branch names:

```bash
feature/add-slack-adapter
fix/renewal-timezone-bug
docs/improve-quickstart
refactor/split-main-py
```

### Commit Messages

Follow conventional commits:

```bash
feat: add Slack adapter for notifications
fix: handle timezone-naive deadlines correctly
docs: clarify renewal process in QUICKSTART
test: add coverage for release trigger flow
refactor: extract CLI commands to separate modules
chore: update dependencies
```

### Types

| Type | When to use |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `test` | Adding/fixing tests |
| `refactor` | Code restructuring without behavior change |
| `chore` | Maintenance, dependencies |
| `style` | Formatting, no code change |

---

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_tick_integration.py

# Run tests matching a pattern
pytest -k "test_renewal"

# Verbose output
pytest -v
```

### Writing Tests

Place tests in `tests/` directory:

```python
# tests/test_my_feature.py
import pytest
from src.engine.tick import run_tick

def test_my_new_feature():
    """Test that my feature works correctly."""
    # Arrange
    state = create_test_state()
    
    # Act
    result = run_tick(state, policy)
    
    # Assert
    assert result.state_changed is True
    assert result.new_state == "WARNING"
```

### Test Categories

- **Unit tests** — Test individual functions
- **Integration tests** — Test components working together
- **Adapter tests** — Test external integrations (mocked)

---

## Submitting Changes

### Pull Request Process

1. **Fork** the repository
2. **Create** a feature branch from `main`
3. **Make** your changes with appropriate tests
4. **Ensure** all tests pass: `pytest`
5. **Check** code style: `ruff check src`
6. **Push** to your fork
7. **Open** a Pull Request with clear description

### PR Description Template

```markdown
## Summary
Brief description of changes.

## Changes
- Added X
- Fixed Y
- Updated Z

## Testing
How was this tested?

## Checklist
- [ ] Tests pass locally
- [ ] Documentation updated if needed
- [ ] No new linting errors
```

### Review Process

- All PRs require at least one review
- CI must pass (tests, linting)
- Maintainer will merge after approval

---

## Style Guidelines

### Python

- Follow PEP 8
- Use type hints for function signatures
- Document public functions with docstrings

```python
def renew_deadline(state: State, hours: int) -> State:
    """
    Extend the deadline by the specified hours.
    
    Args:
        state: Current state object (will be mutated)
        hours: Number of hours to extend
        
    Returns:
        Updated state object
    """
    ...
```

### Linting

```bash
# Check for issues
ruff check src

# Auto-fix where possible
ruff check --fix src

# Type checking (optional)
mypy src
```

### File Organization

- One class per file (generally)
- Group related functions
- Keep modules focused

---

## Architecture Overview

### The Tick Cycle

```
┌─────────────────────────────────────────────────────────────┐
│                      run_tick()                              │
├─────────────────────────────────────────────────────────────┤
│ Phase 1: Initialize context and tick ID                     │
│ Phase 2: Compute time fields (TTD, overdue)                 │
│ Phase 3: Check for manual release trigger                    │
│ Phase 4: Evaluate policy rules                               │
│ Phase 5: Apply state mutations                               │
│ Phase 6: Select actions for current stage                    │
│ Phase 7: Execute adapters                                    │
│ Phase 8: Write audit log and persist state                   │
└─────────────────────────────────────────────────────────────┘
```

### State Flow

```
State (JSON) → Load → Run Tick → Mutate → Save → State (JSON)
                         ↓
                   Execute Actions
                         ↓
                   Write Audit Log
```

### Adding a New Adapter

1. Create `src/adapters/my_adapter.py`:

```python
from .base import BaseAdapter, ExecutionContext, AdapterReceipt

class MyAdapter(BaseAdapter):
    """My custom adapter."""
    
    def is_configured(self) -> bool:
        return bool(os.environ.get("MY_API_KEY"))
    
    def execute(self, context: ExecutionContext) -> AdapterReceipt:
        # Implementation here
        ...
```

2. Register in `src/adapters/registry.py`
3. Add tests in `tests/test_my_adapter.py`
4. Update documentation

---

## Questions?

- Open an issue for bugs or feature requests
- Check existing issues before creating new ones
- Be specific about what you're trying to accomplish

---

*Thank you for contributing!*
