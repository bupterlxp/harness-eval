"""
conftest.py - Pytest configuration and fixtures.
"""

import pytest


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )


@pytest.fixture
def sample_page_state():
    """Provide a sample PageState for tests."""
    from harness.schemas import InteractableElement, PageState

    return PageState(
        url="http://localhost:5000/login",
        title="Login - HR管理系统",
        interactable_elements=[
            InteractableElement(
                tag="input",
                element_type="text",
                selector="#username",
                text=None,
                placeholder="请输入用户名",
                aria_label=None,
                name="username",
                element_id="username",
            ),
            InteractableElement(
                tag="input",
                element_type="password",
                selector="#password",
                text=None,
                placeholder="请输入密码",
                aria_label=None,
                name="password",
                element_id="password",
            ),
            InteractableElement(
                tag="button",
                element_type="submit",
                selector="#login-btn",
                text="登 录",
                placeholder=None,
                aria_label=None,
                name=None,
                element_id="login-btn",
            ),
        ],
    )


@pytest.fixture
def sample_task_steps():
    """Provide sample TaskSteps for tests."""
    from harness.schemas import TaskStep

    return [
        TaskStep(step_id=1, action="启动Mock服务", description="Initialize"),
        TaskStep(step_id=2, action="打开登录页", description="Open login page"),
        TaskStep(step_id=3, action="登录系统", description="Login"),
        TaskStep(step_id=4, action="查看仪表盘", description="View dashboard"),
        TaskStep(step_id=5, action="搜索员工", description="Search employees"),
    ]


@pytest.fixture
def mock_browser_page():
    """Provide a mock browser page for tests."""
    class MockPage:
        def __init__(self):
            self.url = "http://localhost:5000"
            self._elements = {}
            self._visible = set()

        async def goto(self, url, **kwargs):
            self.url = url

        async def title(self):
            return "Mock Page"

        async def click(self, selector, **kwargs):
            pass

        async def fill(self, selector, value, **kwargs):
            self._elements[selector] = value

        async def wait_for_selector(self, selector, **kwargs):
            return True

        async def is_visible(self, selector):
            return selector in self._visible

        async def query_selector_all(self, selector):
            return []

        async def screenshot(self, **kwargs):
            return kwargs.get("path", "screenshot.png")

    return MockPage()
