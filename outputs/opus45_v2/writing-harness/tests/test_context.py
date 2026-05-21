"""Tests for the context module."""

import pytest

from harness.context import (
    ContextManager,
    StyleAnchor,
    EntityTracker,
    ImageryTracker,
)


class TestStyleAnchor:
    def test_to_dict(self):
        anchor = StyleAnchor(
            pov="first-person",
            tense="present",
            tone=["dark", "brooding"],
        )
        d = anchor.to_dict()
        assert d["pov"] == "first-person"
        assert d["tense"] == "present"
        assert "dark" in d["tone"]

    def test_from_dict(self):
        data = {
            "pov": "third-person-omniscient",
            "tense": "past",
            "tone": ["epic"],
            "vocabulary_level": "elevated",
        }
        anchor = StyleAnchor.from_dict(data)
        assert anchor.pov == "third-person-omniscient"
        assert anchor.vocabulary_level == "elevated"

    def test_to_prompt_injection(self):
        anchor = StyleAnchor(
            pov="first-person",
            tense="past",
            tone=["suspenseful"],
        )
        prompt = anchor.to_prompt_injection()
        assert "POV: first-person" in prompt
        assert "Tense: past" in prompt
        assert "suspenseful" in prompt


class TestEntityTracker:
    def test_check_consistency_new_attribute(self):
        entity = EntityTracker(
            name="Alice",
            entity_type="character",
            attributes={},
        )
        consistent, _ = entity.check_consistency("eye_color", "blue")
        assert consistent is True

    def test_check_consistency_matching(self):
        entity = EntityTracker(
            name="Alice",
            entity_type="character",
            attributes={"eye_color": "blue"},
        )
        consistent, _ = entity.check_consistency("eye_color", "Blue")
        assert consistent is True

    def test_check_consistency_drift(self):
        entity = EntityTracker(
            name="Alice",
            entity_type="character",
            attributes={"eye_color": "blue"},
        )
        consistent, issue = entity.check_consistency("eye_color", "brown")
        assert consistent is False
        assert "blue" in issue
        assert "brown" in issue

    def test_add_mention(self):
        entity = EntityTracker(name="Bob", entity_type="character")
        entity.add_mention(scene_id=1, attribute="hair", value="black")
        assert len(entity.mentions) == 1
        assert entity.mentions[0]["scene_id"] == 1


class TestContextManager:
    def test_create_style_anchor_thriller(self):
        cm = ContextManager()
        anchor = cm.create_style_anchor(
            pov="first-person",
            genre="psychological thriller",
            style_directives=["sparse prose"],
        )
        assert "suspenseful" in anchor.tone or "tense" in anchor.tone
        assert anchor.vocabulary_level == "spare"

    def test_create_style_anchor_romance(self):
        cm = ContextManager()
        anchor = cm.create_style_anchor(
            pov="third-person-limited",
            genre="romance",
            style_directives=["intimate"],
        )
        assert "emotional" in anchor.tone or "intimate" in anchor.tone
        assert anchor.narrative_distance == "intimate"

    def test_register_entity(self):
        cm = ContextManager()
        cm.register_entity(
            name="Sarah",
            entity_type="character",
            attributes={"hair": "red", "age": "25"},
            scene_id=0,
        )
        entity = cm.get_entity("sarah")
        assert entity is not None
        assert entity.attributes["hair"] == "red"

    def test_update_entity_attribute_consistent(self):
        cm = ContextManager()
        cm.register_entity("Tom", "character", {"eye_color": "green"}, 0)
        consistent, issue = cm.update_entity_attribute("Tom", "eye_color", "Green", 1)
        assert consistent is True
        assert issue == ""

    def test_update_entity_attribute_drift(self):
        cm = ContextManager()
        cm.register_entity("Tom", "character", {"eye_color": "green"}, 0)
        consistent, issue = cm.update_entity_attribute("Tom", "eye_color", "blue", 1)
        assert consistent is False
        assert "green" in issue.lower()

    def test_register_imagery(self):
        cm = ContextManager()
        cm.register_imagery("broken mirror", "Symbolizes fractured identity", 0, ["identity"])
        cm.register_imagery("broken mirror", "Used again", 2)

        imagery = cm._imagery.get("broken mirror")
        assert imagery is not None
        assert len(imagery.scenes_used) == 2

    def test_build_scene_context(self):
        cm = ContextManager()
        cm.create_style_anchor("first-person", "thriller", [])
        cm.register_entity("Detective", "character", {"trait": "cynical"}, 0)
        cm.set_scene_summary(0, "The crime scene")

        context = cm.build_scene_context(
            scene_id=1,
            scene_summary="Investigation begins",
            prior_content="Previous scene content here",
        )

        assert "Style Anchor" in context
        assert "Detective" in context
        assert "Scene 0: The crime scene" in context
        assert "Scene 1: Investigation begins" in context

    def test_export_import_context(self):
        cm1 = ContextManager()
        cm1.create_style_anchor("third-person-limited", "sci-fi", [])
        cm1.register_entity("Ship", "object", {"name": "Aurora"}, 0)

        exported = cm1.export_context()

        cm2 = ContextManager()
        cm2.import_context(exported)

        assert cm2.style_anchor is not None
        assert cm2.style_anchor.pov == "third-person-limited"
        assert cm2.get_entity("ship") is not None
