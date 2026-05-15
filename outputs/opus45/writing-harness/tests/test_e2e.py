"""
test_e2e.py - End-to-end tests for the complete harness

Tests running through FEATURE_EXAMPLE to generate a 2000+ word story.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from harness.core import Harness, create_harness
from harness.schemas import ExecutionState, TaskSpec, StyleSpec


IDEAL_INPUT = """
体裁:心理惊悚 / 哥特短篇
篇幅:约 2000–2500 词(英文)
视角:第一人称不可靠叙述者
核心张力:叙述者向读者倾诉自己策划并实施的一桩谋杀,并坚称自己神志清醒
关键约束:
  - 杀机来自一个具体而非理性的执念物(如身体某部位、器官、物件)
  - 必须有"延宕铺垫(七夜窥伺)→ 第八夜爆发"的双段式时间结构
  - 杀人后必须有"看似完美的隐藏",但被一种感官信号(声/影/气味)逐渐瓦解
  - 结尾必须是叙述者在外人面前主动崩溃、自我招供
风格要求:
  - 大量破折号、感叹号、词语重复("louder, louder, louder")
  - 直接呼告读者("you fancy me mad")
  - 以听觉意象为主导(心跳、怀表、墙中虫鸣构成隐喻链)
"""


class TestTaskSpecParsing:
    """Test parsing of IDEAL_INPUT"""

    def test_parse_genre(self):
        """Parses genre correctly"""
        harness = Harness()
        spec = harness.parse_task_input(IDEAL_INPUT)

        assert "心理惊悚" in spec.genre or "thriller" in spec.genre.lower() or "gothic" in spec.genre.lower()

    def test_parse_pov(self):
        """Parses point of view"""
        harness = Harness()
        spec = harness.parse_task_input(IDEAL_INPUT)

        assert "first" in spec.pov.lower() or "第一人称" in spec.pov

    def test_parse_core_tension(self):
        """Parses core tension"""
        harness = Harness()
        spec = harness.parse_task_input(IDEAL_INPUT)

        assert spec.core_tension is not None
        assert len(spec.core_tension) > 0

    def test_parse_style_requirements(self):
        """Parses style requirements"""
        harness = Harness()
        spec = harness.parse_task_input(IDEAL_INPUT)

        assert spec.style.dash_density == "high"
        assert spec.style.exclamation_density == "high"


class TestComponentIntegration:
    """Test integration between components"""

    def test_tools_registered(self):
        """Domain tools are registered"""
        harness = create_harness()

        assert "generate_narrator_voice" in harness.tools
        assert "generate_plot_outline" in harness.tools
        assert "generate_scene_outline" in harness.tools
        assert "draft_scene" in harness.tools
        assert "check_consistency" in harness.tools
        assert "revise_style" in harness.tools
        assert "assemble_final" in harness.tools

    def test_hooks_configured(self):
        """Lifecycle hooks are configured"""
        harness = create_harness()

        assert harness._approval_hook is not None
        assert harness._audit_hook is not None

    def test_state_store_initialized(self):
        """State store is ready"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = Harness(db_path=Path(tmpdir) / "test.db")
            assert harness.state_store is not None


class TestMockedExecution:
    """Test execution with mocked LLM calls"""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM responses"""
        with patch("harness.domain.tools._call_llm") as mock:
            mock.side_effect = self._mock_llm_response
            yield mock

    def _mock_llm_response(self, prompt: str, max_tokens: int = 2000, temperature: float = 0.7) -> str:
        """Generate mock LLM responses based on prompt content"""
        if "voice sample" in prompt.lower() or "narrator voice" in prompt.lower():
            return "TRUE!—nervous—very, very dreadfully nervous I had been! But why will you say that I am mad? The disease had sharpened my senses—not destroyed them."

        if "plot outline" in prompt.lower() or "seven-beat" in prompt.lower():
            return """{
                "beats": [
                    {"beat_number": 1, "name": "obsession_establishment", "description": "Narrator introduces themselves and the eye", "target_word_ratio": 0.1, "key_imagery": ["vulture_eye"], "emotional_arc": "defensive"},
                    {"beat_number": 2, "name": "delay_period", "description": "Seven nights of watching", "target_word_ratio": 0.25, "key_imagery": ["lantern", "darkness"], "emotional_arc": "building"},
                    {"beat_number": 3, "name": "trigger_event", "description": "Eighth night begins differently", "target_word_ratio": 0.05, "key_imagery": ["eye_open"], "emotional_arc": "anticipation"},
                    {"beat_number": 4, "name": "climax", "description": "The murder", "target_word_ratio": 0.15, "key_imagery": ["heartbeat"], "emotional_arc": "frenzy"},
                    {"beat_number": 5, "name": "concealment", "description": "Hiding the body", "target_word_ratio": 0.15, "key_imagery": ["floorboards"], "emotional_arc": "triumph"},
                    {"beat_number": 6, "name": "external_pressure", "description": "Police arrive", "target_word_ratio": 0.15, "key_imagery": ["chairs"], "emotional_arc": "confidence"},
                    {"beat_number": 7, "name": "breakdown", "description": "Hearing the heartbeat", "target_word_ratio": 0.15, "key_imagery": ["heartbeat_louder"], "emotional_arc": "collapse"}
                ],
                "obsession_object": "the old man's vulture eye",
                "trigger_event": "the eye opens on the eighth night",
                "concealment_method": "dismemberment under floorboards",
                "exposure_signal": "phantom heartbeat",
                "confession_moment": "shrieking admission to police"
            }"""

        if "scene" in prompt.lower() and "outline" in prompt.lower():
            return """{
                "scenes": [
                    {"scene_id": 0, "beat_number": 1, "title": "The Introduction", "time_marker": "present", "location": "unnamed", "key_events": ["narrator claims sanity", "describes the eye"], "imagery_to_establish": ["vulture_eye"], "imagery_to_reference": [], "target_word_count": 200, "emotional_beat": "defensive", "style_notes": "heavy on dashes and direct address"},
                    {"scene_id": 1, "beat_number": 2, "title": "Seven Nights", "time_marker": "night 1-7", "location": "old man's chamber", "key_events": ["nightly visits", "eye always closed"], "imagery_to_establish": ["lantern", "darkness"], "imagery_to_reference": ["vulture_eye"], "target_word_count": 400, "emotional_beat": "patience", "style_notes": "repetitive structure"},
                    {"scene_id": 2, "beat_number": 3, "title": "The Eighth Night", "time_marker": "night 8", "location": "old man's chamber", "key_events": ["sound wakes old man", "eye opens"], "imagery_to_establish": ["heartbeat"], "imagery_to_reference": ["vulture_eye", "lantern"], "target_word_count": 200, "emotional_beat": "anticipation", "style_notes": "building tension"},
                    {"scene_id": 3, "beat_number": 4, "title": "The Act", "time_marker": "night 8", "location": "old man's chamber", "key_events": ["murder", "heartbeat stops"], "imagery_to_establish": [], "imagery_to_reference": ["heartbeat", "vulture_eye"], "target_word_count": 300, "emotional_beat": "frenzy", "style_notes": "climactic intensity"},
                    {"scene_id": 4, "beat_number": 5, "title": "The Concealment", "time_marker": "night 8", "location": "old man's chamber", "key_events": ["dismemberment", "under floorboards"], "imagery_to_establish": ["floorboards"], "imagery_to_reference": [], "target_word_count": 250, "emotional_beat": "triumph", "style_notes": "grim satisfaction"},
                    {"scene_id": 5, "beat_number": 6, "title": "The Visit", "time_marker": "4am", "location": "house", "key_events": ["police arrive", "narrator confident"], "imagery_to_establish": ["chairs"], "imagery_to_reference": ["floorboards"], "target_word_count": 300, "emotional_beat": "false confidence", "style_notes": "ironic ease"},
                    {"scene_id": 6, "beat_number": 7, "title": "The Breakdown", "time_marker": "4am", "location": "old man's chamber", "key_events": ["heartbeat returns", "grows louder", "confession"], "imagery_to_establish": [], "imagery_to_reference": ["heartbeat", "floorboards"], "target_word_count": 350, "emotional_beat": "collapse", "style_notes": "escalating repetition, exclamations"}
                ]
            }"""

        if "draft" in prompt.lower() and "scene" in prompt.lower():
            scene_texts = [
                "TRUE!—nervous—very, very dreadfully nervous I had been and am; but why will you say that I am mad? The disease had sharpened my senses—not destroyed—not dulled them. Above all was the sense of hearing acute. I heard all things in the heaven and in the earth.",
                "And every night, about midnight, I turned the latch of his door and opened it—oh so gently! And then, when I had made an opening sufficient for my head, I put in a dark lantern, all closed, closed, that no light shone out, and then I thrust in my head.",
                "Upon the eighth night I was more than usually cautious in opening the door. Never before that night had I felt the extent of my own powers—of my sagacity. To think that there I was, opening the door, little by little, and he not even to dream of my secret deeds or thoughts.",
                "With a loud yell, I threw open the lantern and leaped into the room. He shrieked once—once only. In an instant I dragged him to the floor, and pulled the heavy bed over him. The heart beat on with a muffled sound.",
                "First of all I dismembered the corpse. I cut off the head and the arms and the legs. I then took up three planks from the flooring of the chamber, and deposited all between the scantlings.",
                "I smiled,—for what had I to fear? I bade the gentlemen welcome. The shriek, I said, was my own in a dream. I took my visitors all over the house. I led them, at length, to his chamber.",
                "The ringing became more distinct:—it continued and became more distinct. It was a low, dull, quick sound—much such a sound as a watch makes when enveloped in cotton. Louder—louder—louder! 'Villains!' I shrieked, 'dissemble no more! I admit the deed!—tear up the planks! here, here!—It is the beating of his hideous heart!'"
            ]
            import re
            scene_match = re.search(r'scene[_\s]*(\d+)', prompt.lower())
            scene_idx = int(scene_match.group(1)) if scene_match else 0
            return scene_texts[min(scene_idx, len(scene_texts) - 1)]

        if "consistency" in prompt.lower():
            return '{"passed": true, "issues": [], "imagery_coverage": {}, "timeline_valid": true, "voice_coherence_score": 0.95}'

        if "style" in prompt.lower() and "revision" in prompt.lower():
            return '{"revised_scenes": []}'

        if "assembly" in prompt.lower() or "final" in prompt.lower():
            return """TRUE!—nervous—very, very dreadfully nervous I had been and am; but why will you say that I am mad?

And every night, about midnight, I turned the latch of his door. Upon the eighth night I was more than usually cautious.

With a loud yell, I threw open the lantern and leaped into the room. First of all I dismembered the corpse.

I smiled,—for what had I to fear? But the ringing became more distinct. Louder—louder—louder!

'Villains!' I shrieked, 'I admit the deed!—tear up the planks!—here, here!—It is the beating of his hideous heart!'"""

        return "Default mock response"

    def test_full_execution_with_mocks(self, mock_llm):
        """Run full execution with mocked LLM"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = create_harness(
                db_path=Path(tmpdir) / "test.db",
                trajectory_dir=Path(tmpdir) / "trajectories",
                auto_approve=True
            )

            final = harness.run(IDEAL_INPUT)

            assert final.current_state == ExecutionState.COMPLETE
            assert final.final_draft is not None
            assert len(final.final_draft) > 0


class TestTrajectoryRecording:
    """Test V component trajectory recording"""

    def test_trajectory_file_created(self):
        """Trajectory JSONL file is created"""
        with tempfile.TemporaryDirectory() as tmpdir:
            from harness.evaluation import TrajectoryRecorder
            from harness.schemas import ExecutionState, EventType

            recorder = TrajectoryRecorder("test-session", tmpdir)
            recorder.record(
                state_before=ExecutionState.INIT,
                state_after=ExecutionState.PARSE_SPEC,
                event=EventType.START
            )

            assert recorder.output_path.exists()

    def test_trajectory_contains_steps(self):
        """Trajectory records all steps"""
        with tempfile.TemporaryDirectory() as tmpdir:
            from harness.evaluation import TrajectoryRecorder
            from harness.schemas import ExecutionState, EventType

            recorder = TrajectoryRecorder("test-session", tmpdir)

            recorder.record(
                state_before=ExecutionState.INIT,
                state_after=ExecutionState.PARSE_SPEC,
                event=EventType.START,
                reasoning="Starting execution"
            )

            recorder.record(
                state_before=ExecutionState.PARSE_SPEC,
                state_after=ExecutionState.NARRATOR_VOICE,
                event=EventType.SPEC_PARSED,
                tool_called="parse_task_spec",
                tool_input={"raw": "test"},
                tool_output_summary="Parsed successfully"
            )

            entries = recorder.get_entries()
            assert len(entries) == 2
            assert entries[0].reasoning == "Starting execution"
            assert entries[1].tool_called == "parse_task_spec"


class TestSampleComparison:
    """Test comparison with reference sample"""

    def test_comparison_dimensions(self):
        """Comparison covers structure, style, and imagery"""
        sample_path = Path("./samples/the_tell_tale_heart.txt")
        if not sample_path.exists():
            pytest.skip("Sample file not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            harness = Harness(db_path=Path(tmpdir) / "test.db")

            harness._current_session = harness.state_store.create_session()
            harness._current_session.final_draft = """
            TRUE!—nervous—very, very dreadfully nervous I had been and am!
            But why will you say that I am mad? The disease had sharpened my senses.
            I heard all things in the heaven and in the earth.
            """ * 20

            report = harness.compare_with_sample(sample_path)

            assert len(report.structure_comparisons) > 0
            assert len(report.style_comparisons) > 0
            assert 0.0 <= report.overall_alignment_score <= 1.0
