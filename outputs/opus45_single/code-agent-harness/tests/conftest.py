"""pytest configuration and fixtures."""

import tempfile
import shutil
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def test_repo():
    """Create a test repository structure."""
    d = tempfile.mkdtemp()
    repo = Path(d)

    (repo / "src").mkdir()
    (repo / "src" / "__init__.py").write_text("")
    (repo / "src" / "main.py").write_text('''
def hello(name: str) -> str:
    """Greet someone."""
    return f"Hello, {name}!"

def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

class Calculator:
    """A simple calculator."""

    def multiply(self, a: int, b: int) -> int:
        return a * b

    def divide(self, a: int, b: int) -> float:
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b
''')

    (repo / "tests").mkdir()
    (repo / "tests" / "__init__.py").write_text("")
    (repo / "tests" / "test_main.py").write_text('''
import pytest
from src.main import hello, add, Calculator

def test_hello():
    assert hello("World") == "Hello, World!"

def test_add():
    assert add(2, 3) == 5

class TestCalculator:
    def test_multiply(self):
        calc = Calculator()
        assert calc.multiply(3, 4) == 12

    def test_divide(self):
        calc = Calculator()
        assert calc.divide(10, 2) == 5.0

    def test_divide_by_zero(self):
        calc = Calculator()
        with pytest.raises(ValueError):
            calc.divide(1, 0)
''')

    (repo / "README.md").write_text("# Test Repository\n\nA test repo for harness testing.")
    (repo / "pyproject.toml").write_text('''
[project]
name = "test-repo"
version = "0.1.0"

[tool.pytest.ini_options]
testpaths = ["tests"]
''')

    yield repo
    shutil.rmtree(d)


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory."""
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d)
