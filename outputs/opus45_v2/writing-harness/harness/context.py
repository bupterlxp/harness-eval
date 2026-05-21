"""Context Manager module for managing creative writing context.

Implements mechanisms to prevent style drift and reference drift by maintaining
voice anchors, imagery tracking, and entity consistency across scenes.
"""

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class StyleAnchor:
    """Voice/style anchor to maintain consistent narrative voice."""
    pov: str = ""
    tense: str = "past"
    tone: list[str] = field(default_factory=list)
    sentence_patterns: list[str] = field(default_factory=list)
    vocabulary_level: str = "moderate"
    signature_phrases: list[str] = field(default_factory=list)
    narrative_distance: str = "close"
    genre_conventions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StyleAnchor":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_prompt_injection(self) -> str:
        """Convert style anchor to a prompt string for injection."""
        parts = [
            "## Style Anchor (MUST FOLLOW)",
            f"- POV: {self.pov}",
            f"- Tense: {self.tense}",
            f"- Tone: {', '.join(self.tone) if self.tone else 'neutral'}",
            f"- Vocabulary: {self.vocabulary_level}",
            f"- Narrative distance: {self.narrative_distance}",
        ]
        if self.sentence_patterns:
            parts.append(f"- Sentence patterns: {', '.join(self.sentence_patterns)}")
        if self.signature_phrases:
            parts.append(f"- Signature elements: {', '.join(self.signature_phrases)}")
        if self.genre_conventions:
            parts.append(f"- Genre conventions: {', '.join(self.genre_conventions)}")
        return "\n".join(parts)


@dataclass
class EntityTracker:
    """Tracks entity attributes for consistency checking."""
    name: str
    entity_type: str
    attributes: dict[str, str] = field(default_factory=dict)
    first_mention_scene: int = 0
    mentions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EntityTracker":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def add_mention(self, scene_id: int, attribute: str, value: str) -> None:
        self.mentions.append({
            "scene_id": scene_id,
            "attribute": attribute,
            "value": value,
        })

    def check_consistency(self, attribute: str, value: str) -> tuple[bool, str]:
        """Check if a new value is consistent with established attributes."""
        if attribute in self.attributes:
            existing = self.attributes[attribute]
            if existing.lower() != value.lower():
                return False, f"{self.name}'s {attribute} was '{existing}' but now '{value}'"
        return True, ""


@dataclass
class ImageryTracker:
    """Tracks recurring imagery and metaphors for coherence."""
    motif: str
    description: str
    scenes_used: list[int] = field(default_factory=list)
    associated_meanings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TimelineEvent:
    """Tracks timeline events for temporal consistency."""
    event: str
    scene_id: int
    relative_time: str
    absolute_markers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ContextManager:
    """Manages creative context including style anchors and entity tracking."""

    def __init__(self):
        self._style_anchor: StyleAnchor | None = None
        self._entities: dict[str, EntityTracker] = {}
        self._imagery: dict[str, ImageryTracker] = {}
        self._timeline: list[TimelineEvent] = []
        self._genre: str = ""
        self._structural_constraints: list[str] = []
        self._scene_summaries: dict[int, str] = {}

    @property
    def style_anchor(self) -> StyleAnchor | None:
        return self._style_anchor

    def set_style_anchor(self, anchor: StyleAnchor) -> None:
        """Set the master style anchor."""
        self._style_anchor = anchor

    def create_style_anchor(
        self,
        pov: str,
        genre: str,
        style_directives: list[str],
    ) -> StyleAnchor:
        """Create a style anchor from task specifications."""
        anchor = StyleAnchor(pov=pov)
        self._genre = genre

        genre_lower = genre.lower()
        if "thriller" in genre_lower or "惊悚" in genre_lower:
            anchor.tone = ["tense", "atmospheric", "suspenseful"]
            anchor.sentence_patterns = ["short punchy sentences for tension", "longer for dread"]
            anchor.genre_conventions = ["build suspense", "delayed reveals", "sensory details"]
        elif "romance" in genre_lower or "言情" in genre_lower:
            anchor.tone = ["emotional", "intimate", "warm"]
            anchor.sentence_patterns = ["flowing emotional passages", "internal reflection"]
            anchor.genre_conventions = ["emotional beats", "relationship focus", "sensory romance"]
        elif "sci-fi" in genre_lower or "科幻" in genre_lower:
            anchor.tone = ["wonder", "technical", "speculative"]
            anchor.sentence_patterns = ["balance exposition with action"]
            anchor.genre_conventions = ["world-building", "scientific grounding", "sense of scale"]
        elif "fantasy" in genre_lower or "奇幻" in genre_lower:
            anchor.tone = ["epic", "mythic", "immersive"]
            anchor.sentence_patterns = ["evocative descriptions", "rhythmic prose"]
            anchor.genre_conventions = ["magic system consistency", "world coherence"]
        else:
            anchor.tone = ["engaging", "clear"]
            anchor.genre_conventions = ["genre-appropriate pacing"]

        for directive in style_directives:
            directive_lower = directive.lower()
            if "sparse" in directive_lower or "简洁" in directive_lower:
                anchor.vocabulary_level = "spare"
            elif "literary" in directive_lower or "文学" in directive_lower:
                anchor.vocabulary_level = "elevated"
            if "distant" in directive_lower:
                anchor.narrative_distance = "distant"
            elif "intimate" in directive_lower or "亲密" in directive_lower:
                anchor.narrative_distance = "intimate"

        self._style_anchor = anchor
        return anchor

    def register_entity(
        self,
        name: str,
        entity_type: str,
        attributes: dict[str, str],
        scene_id: int = 0,
    ) -> None:
        """Register an entity with its initial attributes."""
        key = name.lower()
        self._entities[key] = EntityTracker(
            name=name,
            entity_type=entity_type,
            attributes=attributes,
            first_mention_scene=scene_id,
        )

    def update_entity_attribute(
        self,
        name: str,
        attribute: str,
        value: str,
        scene_id: int,
    ) -> tuple[bool, str]:
        """Update an entity attribute, checking for inconsistency."""
        key = name.lower()
        if key not in self._entities:
            self.register_entity(name, "unknown", {attribute: value}, scene_id)
            return True, ""

        entity = self._entities[key]
        is_consistent, issue = entity.check_consistency(attribute, value)
        if not is_consistent:
            return False, issue

        entity.attributes[attribute] = value
        entity.add_mention(scene_id, attribute, value)
        return True, ""

    def get_entity(self, name: str) -> EntityTracker | None:
        """Get an entity tracker by name."""
        return self._entities.get(name.lower())

    def get_all_entities(self) -> dict[str, EntityTracker]:
        """Get all registered entities."""
        return self._entities.copy()

    def register_imagery(
        self,
        motif: str,
        description: str,
        scene_id: int,
        meanings: list[str] | None = None,
    ) -> None:
        """Register a recurring image or motif."""
        key = motif.lower()
        if key in self._imagery:
            self._imagery[key].scenes_used.append(scene_id)
        else:
            self._imagery[key] = ImageryTracker(
                motif=motif,
                description=description,
                scenes_used=[scene_id],
                associated_meanings=meanings or [],
            )

    def add_timeline_event(
        self,
        event: str,
        scene_id: int,
        relative_time: str,
        absolute_markers: list[str] | None = None,
    ) -> None:
        """Add a timeline event for temporal tracking."""
        self._timeline.append(TimelineEvent(
            event=event,
            scene_id=scene_id,
            relative_time=relative_time,
            absolute_markers=absolute_markers or [],
        ))

    def set_scene_summary(self, scene_id: int, summary: str) -> None:
        """Store a scene summary for context injection."""
        self._scene_summaries[scene_id] = summary

    def set_structural_constraints(self, constraints: list[str]) -> None:
        """Set structural constraints for the narrative."""
        self._structural_constraints = constraints

    def build_scene_context(
        self,
        scene_id: int,
        scene_summary: str,
        prior_content: str,
    ) -> str:
        """Build the full context injection for a scene generation.

        This is called before each scene to inject:
        - Style anchor (prevents voice drift)
        - Entity registry (prevents attribute drift)
        - Prior scene summaries (maintains continuity)
        - Imagery tracking (maintains motif coherence)
        """
        parts = []

        if self._style_anchor:
            parts.append(self._style_anchor.to_prompt_injection())

        if self._entities:
            entity_lines = ["## Established Entities (MAINTAIN CONSISTENCY)"]
            for entity in self._entities.values():
                attrs = ", ".join(f"{k}: {v}" for k, v in entity.attributes.items())
                entity_lines.append(f"- {entity.name} ({entity.entity_type}): {attrs}")
            parts.append("\n".join(entity_lines))

        if self._imagery:
            imagery_lines = ["## Recurring Imagery/Motifs"]
            for img in self._imagery.values():
                imagery_lines.append(f"- {img.motif}: {img.description}")
            parts.append("\n".join(imagery_lines))

        if scene_id > 0 and self._scene_summaries:
            summary_lines = ["## Prior Scene Summaries"]
            for sid in sorted(self._scene_summaries.keys()):
                if sid < scene_id:
                    summary_lines.append(f"Scene {sid}: {self._scene_summaries[sid]}")
            if len(summary_lines) > 1:
                parts.append("\n".join(summary_lines))

        parts.append(f"## Current Scene\nScene {scene_id}: {scene_summary}")

        if prior_content:
            parts.append(f"## Recent Narrative (for continuity)\n{prior_content[-2000:]}")

        return "\n\n".join(parts)

    def get_consistency_context(self) -> dict[str, Any]:
        """Get context needed for consistency checking."""
        return {
            "entities": {k: v.to_dict() for k, v in self._entities.items()},
            "imagery": {k: v.to_dict() for k, v in self._imagery.items()},
            "timeline": [e.to_dict() for e in self._timeline],
            "style_anchor": self._style_anchor.to_dict() if self._style_anchor else {},
        }

    def export_context(self) -> dict[str, Any]:
        """Export full context state."""
        return {
            "style_anchor": self._style_anchor.to_dict() if self._style_anchor else {},
            "entities": {k: v.to_dict() for k, v in self._entities.items()},
            "imagery": {k: v.to_dict() for k, v in self._imagery.items()},
            "timeline": [e.to_dict() for e in self._timeline],
            "genre": self._genre,
            "structural_constraints": self._structural_constraints,
            "scene_summaries": self._scene_summaries,
        }

    def import_context(self, data: dict[str, Any]) -> None:
        """Import context state."""
        if data.get("style_anchor"):
            self._style_anchor = StyleAnchor.from_dict(data["style_anchor"])
        self._entities = {
            k: EntityTracker.from_dict(v)
            for k, v in data.get("entities", {}).items()
        }
        self._imagery = {
            k: ImageryTracker(**v)
            for k, v in data.get("imagery", {}).items()
        }
        self._timeline = [TimelineEvent(**e) for e in data.get("timeline", [])]
        self._genre = data.get("genre", "")
        self._structural_constraints = data.get("structural_constraints", [])
        self._scene_summaries = data.get("scene_summaries", {})
