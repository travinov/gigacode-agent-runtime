"""Shared pytest configuration for GigaCode Agent Runtime."""

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
