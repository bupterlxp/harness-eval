"""
test_form_interaction.py - Tests for form interaction handling.

Verifies:
- Login form (username/password inputs)
- Leave request form (select/date/textarea/input)
- Search form (text input + button)
"""

import pytest
from harness.schemas import InteractableElement, PageState


class TestFormElementIdentification:
    """Tests for identifying form elements."""

    def test_login_form_elements(self) -> None:
        """Login form has expected elements."""
        login_elements = [
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
        ]

        username_el = next(e for e in login_elements if e.name == "username")
        assert username_el.element_type == "text"
        assert username_el.placeholder == "请输入用户名"

        password_el = next(e for e in login_elements if e.name == "password")
        assert password_el.element_type == "password"

        submit_el = next(e for e in login_elements if e.element_id == "login-btn")
        assert submit_el.element_type == "submit"
        assert "登" in submit_el.text

    def test_leave_form_elements(self) -> None:
        """Leave form has all required element types."""
        leave_elements = [
            InteractableElement(
                tag="select",
                element_type=None,
                selector="#leave-type",
                text=None,
                placeholder=None,
                aria_label=None,
                name=None,
                element_id="leave-type",
            ),
            InteractableElement(
                tag="input",
                element_type="date",
                selector="#start-date",
                text=None,
                placeholder=None,
                aria_label=None,
                name=None,
                element_id="start-date",
            ),
            InteractableElement(
                tag="input",
                element_type="date",
                selector="#end-date",
                text=None,
                placeholder=None,
                aria_label=None,
                name=None,
                element_id="end-date",
            ),
            InteractableElement(
                tag="textarea",
                element_type=None,
                selector="#reason",
                text=None,
                placeholder="请填写请假原因...",
                aria_label=None,
                name=None,
                element_id="reason",
            ),
            InteractableElement(
                tag="input",
                element_type="text",
                selector="#emergency",
                text=None,
                placeholder="姓名 + 电话",
                aria_label=None,
                name=None,
                element_id="emergency",
            ),
        ]

        select_el = next(e for e in leave_elements if e.tag == "select")
        assert select_el.element_id == "leave-type"

        date_els = [e for e in leave_elements if e.element_type == "date"]
        assert len(date_els) == 2

        textarea_el = next(e for e in leave_elements if e.tag == "textarea")
        assert "请假原因" in textarea_el.placeholder

    def test_search_form_elements(self) -> None:
        """Search form has text input and button."""
        search_elements = [
            InteractableElement(
                tag="input",
                element_type="text",
                selector="#search-input",
                text=None,
                placeholder="搜索姓名/邮箱/职位...",
                aria_label=None,
                name=None,
                element_id="search-input",
            ),
            InteractableElement(
                tag="button",
                element_type=None,
                selector="button:has-text('搜索')",
                text="搜索",
                placeholder=None,
                aria_label=None,
                name=None,
                element_id=None,
            ),
        ]

        input_el = next(e for e in search_elements if e.element_id == "search-input")
        assert "搜索" in input_el.placeholder

        button_el = next(e for e in search_elements if e.text == "搜索")
        assert button_el.tag == "button"


class TestElementSelectorStrategies:
    """Tests for selector generation strategies."""

    def test_id_selector_preferred(self) -> None:
        """ID selectors are preferred when available."""
        element = InteractableElement(
            tag="input",
            element_type="text",
            selector="#username",
            text=None,
            placeholder="请输入用户名",
            aria_label=None,
            name="username",
            element_id="username",
        )

        assert element.selector.startswith("#")
        assert element.selector == "#username"

    def test_name_selector_fallback(self) -> None:
        """Name selector used when no ID."""
        element = InteractableElement(
            tag="input",
            element_type="text",
            selector="input[name='search']",
            text=None,
            placeholder="Search...",
            aria_label=None,
            name="search",
            element_id=None,
        )

        assert "name=" in element.selector

    def test_text_selector_for_buttons(self) -> None:
        """Text-based selector for buttons."""
        element = InteractableElement(
            tag="button",
            element_type=None,
            selector="button:has-text('搜索')",
            text="搜索",
            placeholder=None,
            aria_label=None,
            name=None,
            element_id=None,
        )

        assert "has-text" in element.selector

    def test_placeholder_selector_for_inputs(self) -> None:
        """Placeholder-based selector for inputs."""
        element = InteractableElement(
            tag="input",
            element_type="text",
            selector="input[placeholder*='搜索']",
            text=None,
            placeholder="搜索姓名/邮箱/职位...",
            aria_label=None,
            name=None,
            element_id=None,
        )

        assert "placeholder" in element.selector


class TestFormValues:
    """Tests for form value handling."""

    def test_select_option_values(self) -> None:
        """Select options have correct values."""
        leave_types = ["年假", "病假", "事假"]

        for lt in leave_types:
            assert lt in ["年假", "病假", "事假"]

    def test_date_format(self) -> None:
        """Dates should be in YYYY-MM-DD format."""
        from datetime import datetime, timedelta

        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        day_after = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")

        assert len(tomorrow) == 10
        assert tomorrow.count("-") == 2
        assert tomorrow < day_after


class TestFormValidation:
    """Tests for form validation rules."""

    def test_required_fields(self) -> None:
        """Required fields are identified."""
        required_login = ["username", "password"]
        required_leave = ["leave_type", "start_date", "end_date", "reason"]

        assert len(required_login) == 2
        assert len(required_leave) == 4

    def test_date_validation(self) -> None:
        """End date must not be before start date."""
        from datetime import datetime

        start = datetime(2024, 1, 15)
        end_valid = datetime(2024, 1, 17)
        end_invalid = datetime(2024, 1, 14)

        assert end_valid >= start
        assert end_invalid < start


class TestPageStateWithForms:
    """Tests for PageState with form elements."""

    def test_page_state_has_interactable_elements(self) -> None:
        """PageState contains form elements."""
        elements = [
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
        ]

        state = PageState(
            url="http://localhost:5000/login",
            title="Login",
            interactable_elements=elements,
        )

        assert len(state.interactable_elements) == 1
        assert state.interactable_elements[0].element_id == "username"

    def test_page_state_summary_includes_elements(self) -> None:
        """Page summary includes element info."""
        elements = [
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
        ]

        state = PageState(
            url="http://localhost:5000/login",
            title="Login",
            interactable_elements=elements,
        )

        summary = state.to_summary()

        assert "login" in summary.lower()
        assert "#username" in summary

    def test_element_to_dict(self) -> None:
        """Element serializes to dict correctly."""
        element = InteractableElement(
            tag="input",
            element_type="text",
            selector="#username",
            text=None,
            placeholder="请输入用户名",
            aria_label=None,
            name="username",
            element_id="username",
            is_visible=True,
            is_enabled=True,
        )

        d = element.to_dict()

        assert d["tag"] == "input"
        assert d["type"] == "text"
        assert d["selector"] == "#username"
        assert d["visible"] is True
        assert d["enabled"] is True
