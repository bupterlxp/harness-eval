#!/usr/bin/env python3
"""Test suite for the short story generation harness"""

import pytest
import os
import json
from uuid import UUID
from unittest.mock import Mock, patch
from harness import Harness, TaskSpec, StoryGenre, Perspective
from harness.state import StateStore
from harness.context import ContextManager
from harness.tools import ToolRegistry
from harness.schemas import GenerationState


@pytest.fixture
def mock_openai_response():
    """Mock OpenAI API response"""
    mock_response = Mock()
    mock_choice = Mock()
    mock_choice.message.content = json.dumps({
        "voice_sample": "TRUE!—nervous—very, very dreadfully nervous I had been and am! but why will you say that I am mad?",
        "perspective": "first_person",
        "unreliable": True,
        "core_motivation": "obsession with an old man's eye",
        "speaking_style": {
            "sentence_length": "short",
            "punctuation": "exclamation, dashes, repetition",
            "tone": "tense, paranoid"
        }
    })
    mock_response.choices = [mock_choice]
    return mock_response


@pytest.fixture
def test_task_spec():
    """Create a test task specification"""
    return TaskSpec(
        genre=[StoryGenre.PSYCHOLOGICAL_THRILLER],
        length_words=(1000, 1500),
        perspective=Perspective.FIRST_PERSON,
        core_tension="narrator commits murder and is haunted",
        key_constraints={
            "seven_night_delay": True,
            "auditory_imagery": True,
            "unreliable_narrator": True
        },
        style_requirements={
            "dashes": True,
            "exclamation": True,
            "direct_address": True
        },
        raw_input="Test task"
    )


@pytest.fixture
def harness():
    """Create a test harness instance"""
    with patch('openai.OpenAI'):
        harness = Harness(db_path=":memory:")
        yield harness
        harness.close()


class TestStateStore:
    """Test the StateStore component"""

    def test_create_session(self):
        """Test creating a new session"""
        store = StateStore(db_path=":memory:")
        session = store.create_session()
        assert isinstance(session.session_id, UUID)
        assert session.current_state == GenerationState.INITIALIZED
        store.close()

    def test_snapshot_and_recover(self, test_task_spec):
        """Test snapshotting and recovering session state"""
        store = StateStore(db_path=":memory:")
        session = store.create_session(test_task_spec.dict())

        # Create snapshot
        test_data = {"key": "value", "count": 42}
        store.snapshot(session.session_id, GenerationState.PARSED_TASK, test_data)

        # Retrieve snapshot
        snapshot = store.get_latest_snapshot(session.session_id)
        assert snapshot == test_data

        store.close()


class TestContextManager:
    """Test the ContextManager component"""

    def test_context_compression(self):
        """Test context compression functionality"""
        manager = ContextManager(max_context_size=100)
        manager.set_task_spec({"test": "data"})
        manager.set_style_requirements({"style": "test"})

        # Add lots of content
        for i in range(100):
            manager.add_current_scene({"id": i, "content": "x" * 100})

        compressed, tokens = manager.compress_context()
        assert tokens <= 100
        assert "task_spec" in compressed


class TestTools:
    """Test tool registry and tools"""

    def test_tool_registry(self):
        """Test tool registration"""
        registry = ToolRegistry()
        from harness.domain.tools import GenerateNarratorProfileTool

        tool = GenerateNarratorProfileTool()
        registry.register_tool(tool)
        assert tool.name in registry.list_tools()
        assert registry.get_tool(tool.name) == tool


class TestExecutionLoop:
    """Test execution loop state machine"""

    @patch('openai.OpenAI')
    def test_execution_states(self, mock_openai, harness, test_task_spec):
        """Test execution loop state transitions"""
        # Mock the LLM responses
        mock_openai.return_value.chat.completions.create.return_value = Mock(
            choices=[Mock(message=Mock(content=json.dumps({
                "voice_sample": "Test narrator voice",
                "perspective": "first_person",
                "unreliable": True,
                "core_motivation": "test",
                "speaking_style": {"punctuation": "exclamation"}
            })))]
        )

        # Create session
        session_info = harness.create_session(test_task_spec)
        assert harness.current_session.session_id == session_info.session_id
        assert harness.get_current_state() == GenerationState.PARSED_TASK

        # Run first step
        result = harness.run_step()
        assert result['completed'] == True
        assert result['next_state'] == GenerationState.GENERATED_NARRATOR.value


class TestEndToEnd:
    """End-to-end test with mocked LLM"""

    @patch('openai.OpenAI')
    def test_full_pipeline(self, mock_openai, test_task_spec):
        """Test full generation pipeline with mocked LLM"""
        # Mock multiple LLM calls
        mock_responses = [
            # Narrator profile
            Mock(choices=[Mock(message=Mock(content=json.dumps({
                "voice_sample": "Test narrator voice",
                "perspective": "first_person",
                "unreliable": True,
                "core_motivation": "test",
                "speaking_style": {"punctuation": "exclamation"}
            })))]),
            # Plot outline
            Mock(choices=[Mock(message=Mock(content=json.dumps({
                "title": "Test Story",
                "core_tension": "test",
                "setup_beats": ["setup"],
                "delay_segment": ["night 1", "night 2", "night 3", "night 4", "night 5", "night 6", "night 7"],
                "climax": ["murder"],
                "concealment": ["hide body"],
                "exposure": ["police"],
                "confession": ["confess"]
            })))]),
            # Scene outline
            Mock(choices=[Mock(message=Mock(content=json.dumps({
                "scenes": [{
                    "scene_id": 1,
                    "title": "Opening",
                    "pov": "first_person",
                    "time_position": "midnight",
                    "key_imagery": ["heartbeat", "clock"],
                    "beats": ["introduce narrator"]
                }]
            })))]),
            # Draft scene
            Mock(choices=[Mock(message=Mock(content="Test scene content"))]),
            # Consistency check
            Mock(choices=[Mock(message=Mock(content=json.dumps({
                "consistent": True,
                "issues": [],
                "imagery_discrepancies": [],
                "timeline_discrepancies": [],
                "constraint_violations": []
            })))]),
            # Style revision
            Mock(choices=[Mock(message=Mock(content="Revised scene content"))]),
            # Final assembly
            Mock(choices=[Mock(message=Mock(content="Test Story"))])
        ]

        mock_openai.return_value.chat.completions.create.side_effect = mock_responses

        # Run harness
        with patch('os.environ.get', return_value="gpt-3.5-turbo"):
            harness = Harness(db_path=":memory:")
            session_info = harness.create_session(test_task_spec)

            # Run to completion
            result = harness.run_to_completion(max_steps=20)

            assert result['success'] == True
            assert 'manuscript' in result['result']
            assert result['result']['word_count'] > 0

            harness.close()


if __name__ == "__main__":
    pytest.main([__file__])