"""Context Manager component - manages and maintains writing context"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field


@dataclass
class StyleAnchor:
    """Represents a style anchor point to maintain consistency"""
    name: str
    value: str
    description: str = ""


@dataclass
class ContextSnapshot:
    """Snapshot of the current writing context"""
    narrative_style: List[str] = field(default_factory=list)
    character_info: Dict[str, Dict[str, str]] = field(default_factory=dict)
    setting_details: Dict[str, Dict[str, str]] = field(default_factory=dict)
    plot_points: List[str] = field(default_factory=list)
    theme_elements: List[str] = field(default_factory=dict)
    previously_used_elements: Dict[str, List[str]] = field(default_factory=dict)


class ContextManager:
    """Manages writing context and maintains consistency throughout the story"""

    def __init__(self, task_spec: Any):
        self.task_spec = task_spec
        self.style_anchors: List[StyleAnchor] = []
        self.context_snapshot = ContextSnapshot()
        self._initialize_context()

    def _initialize_context(self) -> None:
        """Initialize context from task specification"""
        # Add style directives as anchors
        for directive in self.task_spec.style_directives:
            self.style_anchors.append(StyleAnchor(
                name=f"style:{directive}",
                value=directive,
                description=f"Style directive: {directive}"
            ))

        # Add POV as anchor
        self.style_anchors.append(StyleAnchor(
            name="narrative_pov",
            value=self.task_spec.pov,
            description=f"Narrative perspective: {self.task_spec.pov}"
        ))

        # Initialize context snapshot with genre information
        self.context_snapshot.narrative_style.append(f"Genre: {self.task_spec.genre}")
        self.context_snapshot.narrative_style.append(f"POV: {self.task_spec.pov}")

    def add_style_anchor(self, name: str, value: str, description: str = "") -> None:
        """Add a style anchor to maintain consistency"""
        self.style_anchors.append(StyleAnchor(name, value, description))

    def add_character(self, character_id: str, details: Dict[str, str]) -> None:
        """Add character information to context"""
        self.context_snapshot.character_info[character_id] = details

    def add_setting(self, setting_id: str, details: Dict[str, str]) -> None:
        """Add setting information to context"""
        self.context_snapshot.setting_details[setting_id] = details

    def add_plot_point(self, point: str) -> None:
        """Add a plot point to context"""
        self.context_snapshot.plot_points.append(point)

    def add_theme_element(self, element: str) -> None:
        """Add a theme element to context"""
        self.context_snapshot.theme_elements.append(element)

    def track_element(self, category: str, element: str) -> None:
        """Track used elements to avoid drift"""
        if category not in self.context_snapshot.previously_used_elements:
            self.context_snapshot.previously_used_elements[category] = []
        self.context_snapshot.previously_used_elements[category].append(element)

    def get_context(self, additional_context: str = "") -> str:
        """Get formatted context for current scene generation"""
        context_parts = []

        # Add narrative style information
        if self.context_snapshot.narrative_style:
            context_parts.append("## Narrative Style")
            context_parts.extend(f"- {style}" for style in self.context_snapshot.narrative_style)
            context_parts.append("")

        # Add character information
        if self.context_snapshot.character_info:
            context_parts.append("## Characters")
            for char_id, details in self.context_snapshot.character_info.items():
                context_parts.append(f"- {char_id}: {', '.join(f'{k}: {v}' for k, v in details.items())}")
            context_parts.append("")

        # Add setting information
        if self.context_snapshot.setting_details:
            context_parts.append("## Settings")
            for set_id, details in self.context_snapshot.setting_details.items():
                context_parts.append(f"- {set_id}: {', '.join(f'{k}: {v}' for k, v in details.items())}")
            context_parts.append("")

        # Add plot points
        if self.context_snapshot.plot_points:
            context_parts.append("## Plot Points")
            context_parts.extend(f"- {point}" for point in self.context_snapshot.plot_points)
            context_parts.append("")

        # Add previously used elements
        if self.context_snapshot.previously_used_elements:
            context_parts.append("## Previously Used Elements")
            for category, elements in self.context_snapshot.previously_used_elements.items():
                if elements:
                    context_parts.append(f"### {category}:")
                    context_parts.extend(f"- {elem}" for elem in elements[:5])  # Show top 5
                    if len(elements) > 5:
                        context_parts.append(f"- ...and {len(elements) - 5} more")
            context_parts.append("")

        # Add additional context
        if additional_context:
            context_parts.append("## Previous Scenes Summary")
            context_parts.append(additional_context)

        # Add style anchors injection
        context_parts.append("## Style Anchors (MUST maintain throughout this scene)")
        context_parts.extend(f"- {anchor.name}: {anchor.value}" for anchor in self.style_anchors)

        return "\n".join(context_parts)

    def get_style_anchors_injection(self) -> str:
        """Get just the style anchors injection string"""
        if not self.style_anchors:
            return ""

        anchors_str = ", ".join([f"{anchor.name}={anchor.value}" for anchor in self.style_anchors])
        return f"\n\nIMPORTANT: Maintain these style anchors throughout: {anchors_str}"

    def check_for_drift(self, text: str, category: str = "general") -> List[str]:
        """Check for potential consistency drift in the text"""
        issues = []

        # Simple placeholder drift detection
        # In a real implementation, this would use NLP to detect inconsistencies

        # Check for character description drift
        if category == "characters" and self.context_snapshot.character_info:
            for char_id, details in self.context_snapshot.character_info.items():
                for trait, value in details.items():
                    if value.lower() in text.lower():
                        # Track that we've seen this trait
                        self.track_element(f"char_{char_id}_{trait}", value)

        # Check for setting drift
        if category == "settings" and self.context_snapshot.setting_details:
            for set_id, details in self.context_snapshot.setting_details.items():
                for attr, value in details.items():
                    if value.lower() in text.lower():
                        self.track_element(f"setting_{set_id}_{attr}", value)

        return issues

    def save_context(self, path: str) -> None:
        """Save context snapshot to file"""
        snapshot_dict = {
            "narrative_style": self.context_snapshot.narrative_style,
            "character_info": self.context_snapshot.character_info,
            "setting_details": self.context_snapshot.setting_details,
            "plot_points": self.context_snapshot.plot_points,
            "theme_elements": self.context_snapshot.theme_elements,
            "previously_used_elements": self.context_snapshot.previously_used_elements
        }

        with open(path, "w") as f:
            json.dump(snapshot_dict, f, indent=2, ensure_ascii=False)

    def load_context(self, path: str) -> None:
        """Load context snapshot from file"""
        with open(path, "r") as f:
            snapshot_dict = json.load(f)

        self.context_snapshot.narrative_style = snapshot_dict.get("narrative_style", [])
        self.context_snapshot.character_info = snapshot_dict.get("character_info", {})
        self.context_snapshot.setting_details = snapshot_dict.get("setting_details", {})
        self.context_snapshot.plot_points = snapshot_dict.get("plot_points", [])
        self.context_snapshot.theme_elements = snapshot_dict.get("theme_elements", [])
        self.context_snapshot.previously_used_elements = snapshot_dict.get("previously_used_elements", {})