import pytest
from unittest.mock import patch
from harness.tools import BrowserTools
from harness.schemas import Config


def test_form_interaction():
    """Test form filling and submission interactions"""
    config = Config(
        base_url="http://localhost:5000",
        default_timeout=1000
    )

    tools = BrowserTools(config.__dict__)

    # Mock page and its methods
    mock_page = type('MockPage', (), {
        'fill': lambda self, selector, text: None,
        'select_option': lambda self, selector, value: None,
        'click': lambda self, selector, wait_until=None: None,
        'wait_for_selector': lambda self, selector, timeout=None: None,
        'query_selector': lambda self, selector: None,
        'url': 'http://localhost:5000/test'
    })()

    tools.page = mock_page

    # Test fill
    with patch.object(mock_page, 'fill') as mock_fill:
        result = tools.fill("input[name='username']", "admin")
        assert result.status == "completed"
        mock_fill.assert_called_once_with("input[name='username']", "admin")

    # Test select
    with patch.object(mock_page, 'select_option') as mock_select:
        result = tools.select("select[name='leave_type']", "年假")
        assert result.status == "completed"
        mock_select.assert_called_once_with("select[name='leave_type']", "年假")


def test_element_waiting():
    """Test element waiting functionality"""
    config = Config(
        base_url="http://localhost:5000",
        default_timeout=1000
    )

    tools = BrowserTools(config.__dict__)

    # Mock page
    mock_page = type('MockPage', (), {
        'wait_for_selector': lambda self, selector, timeout=None: None
    })()
    tools.page = mock_page

    # Test successful wait
    with patch.object(mock_page, 'wait_for_selector') as mock_wait:
        result = tools.wait_for_element("#test-element")
        assert result is True
        mock_wait.assert_called_once()

    # Test failed wait
    with patch.object(mock_page, 'wait_for_selector') as mock_wait:
        mock_wait.side_effect = Exception("Not found")
        result = tools.wait_for_element("#non-existent")
        assert result is False


def test_download_handler():
    """Test file download functionality"""
    import os
    from tempfile import TemporaryDirectory

    config = Config(
        download_dir="test_downloads"
    )

    tools = BrowserTools(config.__dict__)

    # Create temp directory
    with TemporaryDirectory() as tmpdir:
        tools.download_dir = tmpdir

        # Mock page with download support
        mock_download = type('MockDownload', (), {
            'suggested_filename': lambda self: "test.csv",
            'save_as': lambda self, path: None
        })()

        mock_page = type('MockPage', (), {
            'expect_download': lambda self, handler: type('', (), {
                '__enter__': lambda self: type('', (), {'value': mock_download})()
            })(),
            'click': lambda self, selector: None
        })()

        tools.page = mock_page

        with patch.object(mock_download, 'save_as') as mock_save:
            filepath = tools.download_file("button.export")
            assert filepath is not None
            assert os.path.basename(filepath) == "test.csv"
            assert tmpdir in filepath