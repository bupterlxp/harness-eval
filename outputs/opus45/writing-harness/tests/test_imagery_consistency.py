"""
test_imagery_consistency.py - Tests for imagery table preventing reference drift

Tests that the context manager's imagery table maintains consistency
of obsession objects and sensory signals across scenes.
"""

import pytest
from harness.context import ContextManager, ContextCategory
from harness.schemas import ImageryEntry


class TestImageryTableBasics:
    """Test basic imagery table operations"""

    def test_set_imagery_table(self):
        """Can set imagery table in context"""
        ctx = ContextManager()

        imagery = [
            {
                "name": "vulture_eye",
                "description": "pale blue eye with a film over it",
                "first_scene": 0
            },
            {
                "name": "heartbeat",
                "description": "sound like a watch wrapped in cotton",
                "first_scene": 3
            }
        ]

        ctx.set_imagery_table(imagery)

        entry = ctx.get("imagery_table")
        assert entry is not None
        assert entry.category == ContextCategory.IMAGERY_TABLE
        assert "vulture_eye" in entry.content
        assert "heartbeat" in entry.content

    def test_imagery_table_pinned(self):
        """Imagery table is pinned and survives compression"""
        ctx = ContextManager()

        imagery = [{"name": "test_image", "description": "test", "first_scene": 0}]
        ctx.set_imagery_table(imagery)

        compressed = ctx.compress(target_tokens=100)

        pinned_keys = [e.key for e in compressed if e.pinned]
        assert "imagery_table" in pinned_keys

    def test_empty_imagery_table(self):
        """Empty imagery table doesn't add entry"""
        ctx = ContextManager()
        ctx.set_imagery_table([])

        entry = ctx.get("imagery_table")
        assert entry is None


class TestImageryConsistency:
    """Test imagery consistency across scenes"""

    def test_obsession_object_referenced_consistently(self):
        """Obsession object should be trackable across scenes"""
        ctx = ContextManager()

        imagery = [
            {
                "name": "vulture_eye",
                "description": "pale blue eye with a film over it, like that of a vulture",
                "first_scene": 0,
                "category": "obsession_object"
            }
        ]
        ctx.set_imagery_table(imagery)

        scene_content = """
        I could see nothing else of the old man's face or person:
        for I had directed the ray, as if by instinct, precisely upon the damned spot.
        The vulture eye was open—wide, wide open.
        """

        ctx.add_scene_history(0, "Introduced the vulture eye")
        ctx.add_scene_history(1, "Watched by night, eye always closed")
        ctx.add_scene_history(2, scene_content)

        built = ctx.build_prompt_context()
        assert "vulture_eye" in built

    def test_imagery_table_format_for_llm(self):
        """Imagery table is formatted for LLM consumption"""
        ctx = ContextManager()

        imagery = [
            {
                "name": "vulture_eye",
                "description": "pale blue eye with a film over it",
                "first_scene": 0
            },
            {
                "name": "death_watch_beetle",
                "description": "tick-tick sound in the wall at midnight",
                "first_scene": 1
            },
            {
                "name": "heartbeat",
                "description": "low, dull, quick sound like a watch in cotton",
                "first_scene": 3
            }
        ]
        ctx.set_imagery_table(imagery)

        entry = ctx.get("imagery_table")
        content = entry.content

        assert "ESTABLISHED IMAGERY" in content
        assert "introduced scene 0" in content or "scene 0" in content
        assert "vulture_eye" in content
        assert "death_watch_beetle" in content
        assert "heartbeat" in content

    def test_scene_history_ordered(self):
        """Scene history maintains order for reference"""
        ctx = ContextManager()

        ctx.add_scene_history(0, "First scene")
        ctx.add_scene_history(1, "Second scene")
        ctx.add_scene_history(2, "Third scene")

        scenes = ctx.get_by_category(ContextCategory.SCENE_HISTORY)
        assert len(scenes) == 3


class TestImageryDriftPrevention:
    """Test that imagery table helps prevent reference drift"""

    def test_imagery_injected_into_prompt(self):
        """Imagery table is included in built prompt"""
        ctx = ContextManager()

        imagery = [
            {
                "name": "vulture_eye",
                "description": "pale blue eye, like a vulture's",
                "first_scene": 0
            }
        ]
        ctx.set_imagery_table(imagery)
        ctx.add(ContextCategory.TASK_SPEC, "spec", "Task spec here")

        prompt = ctx.build_prompt_context()

        assert "vulture_eye" in prompt
        assert "IMAGERY" in prompt.upper()

    def test_imagery_higher_priority_than_history(self):
        """Imagery table has higher priority than scene history"""
        ctx = ContextManager()

        ctx.set_imagery_table([{"name": "test", "description": "test", "first_scene": 0}])

        for i in range(10):
            ctx.add_scene_history(i, f"Scene {i} content " * 50)

        compressed = ctx.compress(target_tokens=500)

        categories = [e.category for e in compressed]
        assert ContextCategory.IMAGERY_TABLE in categories

    def test_narrator_voice_always_present(self):
        """Narrator voice is always included to prevent voice drift"""
        ctx = ContextManager()

        ctx.set_narrator_voice("TRUE!—nervous—very, very dreadfully nervous I had been and am!")

        for i in range(10):
            ctx.add_scene_history(i, f"Scene {i} " * 100)

        compressed = ctx.compress(target_tokens=300)

        entry = None
        for e in compressed:
            if e.category == ContextCategory.NARRATOR_VOICE:
                entry = e
                break

        assert entry is not None
        assert "nervous" in entry.content


class TestImageryEntrySchema:
    """Test ImageryEntry schema validation"""

    def test_imagery_entry_creation(self):
        """Can create valid imagery entry"""
        entry = ImageryEntry(
            image_id="img_0",
            name="vulture_eye",
            description="pale blue eye with a film",
            category="obsession_object",
            first_scene=0,
            references=[0, 1, 2, 4],
            metaphor_chain=["eye", "evil eye", "damned spot"]
        )

        assert entry.image_id == "img_0"
        assert entry.first_scene == 0
        assert 4 in entry.references
        assert "evil eye" in entry.metaphor_chain

    def test_imagery_entry_tracks_references(self):
        """Imagery entry can track which scenes reference it"""
        entry = ImageryEntry(
            image_id="img_1",
            name="heartbeat",
            description="sound like a watch in cotton",
            category="sensory_signal",
            first_scene=3,
            references=[3]
        )

        entry.references.append(4)
        entry.references.append(5)
        entry.references.append(6)

        assert len(entry.references) == 4
        assert entry.references == [3, 4, 5, 6]

    def test_metaphor_chain_linkage(self):
        """Imagery can track metaphor chain evolution"""
        entry = ImageryEntry(
            image_id="img_2",
            name="auditory_signal",
            description="evolving sound motif",
            category="sensory_signal",
            first_scene=1,
            metaphor_chain=[
                "death-watches in the wall",
                "watch wrapped in cotton",
                "heartbeat growing louder",
                "louder—louder—louder!"
            ]
        )

        assert len(entry.metaphor_chain) == 4
        assert "louder" in entry.metaphor_chain[-1]
