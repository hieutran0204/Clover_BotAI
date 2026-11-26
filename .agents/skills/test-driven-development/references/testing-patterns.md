# Testing Patterns Reference (Python)

Quick reference of Python testing patterns — pytest, httpx/TestClient, and general async testing — illustrating the universal principles from the `test-driven-development` skill. The principles (Arrange-Act-Assert, naming, mock discipline, anti-patterns) apply in any ecosystem; the syntax and tooling shown here are Python/FastAPI-specific.

## Table of Contents

- [Test Structure (Arrange-Act-Assert)](#test-structure-arrange-act-assert)
- [Test Naming Conventions](#test-naming-conventions)
- [Common Assertions](#common-assertions)
- [Mocking Patterns](#mocking-patterns)
- [FastAPI / Integration Testing](#fastapi--integration-testing)
- [Async Testing](#async-testing)
- [Test Anti-Patterns](#test-anti-patterns)

## Test Structure (Arrange-Act-Assert)

```python
def test_create_task_sets_default_status():
    # Arrange
    input_data = {"title": "Test Task", "priority": "high"}

    # Act
    result = create_task(input_data)

    # Assert
    assert result.title == "Test Task"
    assert result.priority == "high"
    assert result.status == "pending"
```

## Test Naming Conventions

```python
# Pattern: test_[unit]_[expected behavior]_[condition]
class TestTaskService:
    def test_create_task_sets_default_pending_status(self): ...
    def test_create_task_raises_validation_error_when_title_is_empty(self): ...
    def test_create_task_trims_whitespace_from_title(self): ...
    def test_create_task_generates_unique_id_for_each_task(self): ...
```

## Common Assertions

```python
# Equality
assert result == expected
assert result is None
assert result is not None

# Collections
assert len(result) == 3
assert item in result
assert "key" in result_dict
assert result_dict["key"] == "value"

# Approximate
import math
assert math.isclose(result, 0.3, rel_tol=1e-5)

# Exceptions
import pytest
with pytest.raises(ValidationError):
    create_task({"title": ""})

with pytest.raises(ValidationError, match="title is required"):
    create_task({"title": ""})

# Async
import pytest
@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result == expected
```

## Mocking Patterns

### Mock Functions with pytest-mock

```python
def test_sends_email_on_task_creation(mocker):
    mock_send = mocker.patch("app.services.email.send_email")
    
    create_task({"title": "Test", "notify": True})
    
    mock_send.assert_called_once_with(
        to="user@example.com",
        subject="Task created"
    )
```

### Mock at Boundaries Only

```
Mock these:                    Don't mock these:
├── Database calls             ├── Internal utility functions
├── HTTP requests              ├── Business logic
├── File system operations     ├── Data transformations
├── External API calls         ├── Validation functions
└── Time/Date (when needed)    └── Pure functions
```

### Fixtures for Common Setup

```python
import pytest
from httpx import AsyncClient
from app.main import app

@pytest.fixture
async def client():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

@pytest.fixture
def auth_headers(test_user_token):
    return {"Authorization": f"Bearer {test_user_token}"}
```

## FastAPI / Integration Testing

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_create_task_returns_201(client, auth_headers):
    response = await client.post(
        "/api/v1/tasks",
        json={"title": "Test Task"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test Task"
    assert data["status"] == "pending"
    assert "id" in data

@pytest.mark.asyncio
async def test_create_task_returns_422_for_invalid_input(client, auth_headers):
    response = await client.post(
        "/api/v1/tasks",
        json={"title": ""},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] is not None

@pytest.mark.asyncio
async def test_create_task_returns_401_without_auth(client):
    response = await client.post(
        "/api/v1/tasks",
        json={"title": "Test Task"},
    )
    assert response.status_code == 401
```

## Async Testing

```python
import pytest
import asyncio

# Use pytest-asyncio
@pytest.mark.asyncio
async def test_async_service():
    result = await some_service.do_work()
    assert result.status == "completed"

# pytest.ini or pyproject.toml config
# [tool.pytest.ini_options]
# asyncio_mode = "auto"  # auto-marks all async tests
```

## Test Anti-Patterns

| Anti-Pattern | Problem | Better Approach |
|---|---|---|
| Testing implementation details | Breaks on refactor | Test inputs/outputs |
| Snapshot everything | No one reviews snapshot diffs | Assert specific values |
| Shared mutable state | Tests pollute each other | Use fixtures with function scope |
| Testing third-party code | Wastes time, not your bug | Mock the boundary |
| Skipping tests to pass CI | Hides real bugs | Fix or delete the test |
| Using `pytest.mark.skip` permanently | Dead code | Remove or fix it |
| Overly broad assertions | Doesn't catch regressions | Be specific |
| No async error handling | Swallowed errors, false passes | Always `await` async tests |
| `sleep()` in tests | Flaky, slow | Use event-driven assertions or mocks |
