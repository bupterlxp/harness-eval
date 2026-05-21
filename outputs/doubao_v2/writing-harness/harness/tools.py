"""Tool Registry component - provides access to writing tools"""

from typing import Dict, Any, Callable, Optional
from dataclasses import dataclass
import json


@dataclass
class Tool:
    """Represents a single tool with its schema and implementation"""
    name: str
    description: str
    input_schema: Dict[str, Any]
    implementation: Callable[[Dict[str, Any]], Dict[str, Any]]


class ToolRegistry:
    """Registry for managing available writing tools"""

    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        """Register all default writing tools"""

        # Outline generation tool
        self.register_tool(Tool(
            name="generate_outline",
            description="Generate story outline from premise",
            input_schema={
                "type": "object",
                "properties": {
                    "premise": {"type": "string", "description": "Story premise/seed"},
                    "genre": {"type": "string", "description": "Story genre"},
                    "structural_constraints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of structural constraints"
                    }
                },
                "required": ["premise", "genre"]
            },
            implementation=self._generate_outline
        ))

        # Scene generation tool
        self.register_tool(Tool(
            name="generate_scene",
            description="Generate a single scene based on context and requirements",
            input_schema={
                "type": "object",
                "properties": {
                    "scene_summary": {"type": "string", "description": "Scene summary"},
                    "previous_context": {"type": "string", "description": "Context from previous scenes"},
                    "style_directives": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of style directives"
                    },
                    "pov": {"type": "string", "description": "Narrative perspective"}
                },
                "required": ["scene_summary", "previous_context"]
            },
            implementation=self._generate_scene
        ))

        # Consistency check tool
        self.register_tool(Tool(
            name="check_consistency",
            description="Check text for consistency issues",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to check"},
                    "previous_content": {"type": "string", "description": "Previous story content for comparison"}
                },
                "required": ["text"]
            },
            implementation=self._check_consistency
        ))

        # Style refinement tool
        self.register_tool(Tool(
            name="refine_style",
            description="Refine text to match style directives",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to refine"},
                    "style_directives": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of style directives"
                    },
                    "pov": {"type": "string", "description": "Narrative perspective"}
                },
                "required": ["text", "style_directives"]
            },
            implementation=self._refine_style
        ))

    def register_tool(self, tool: Tool) -> None:
        """Register a new tool in the registry"""
        self.tools[tool.name] = tool

    def get_tool(self, tool_name: str) -> Optional[Tool]:
        """Get a tool by name"""
        return self.tools.get(tool_name)

    def list_tools(self) -> list[str]:
        """List all available tool names"""
        return list(self.tools.keys())

    # Tool implementations
    def _generate_outline(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Default outline generation implementation"""
        # This would normally call an LLM
        premise = params["premise"]
        genre = params.get("genre", "generic")
        constraints = params.get("structural_constraints", [])

        return {
            "success": True,
            "beats": [
                "Introduction",
                "Inciting Incident",
                "Rising Action",
                "Climax",
                "Falling Action",
                "Resolution"
            ],
            "scenes": [
                {"id": 1, "summary": f"Introduction to the {genre} world"},
                {"id": 2, "summary": "Conflict emerges"},
                {"id": 3, "summary": "Main character faces challenges"},
                {"id": 4, "summary": "Climactic confrontation"},
                {"id": 5, "summary": "Resolution of the conflict"}
            ]
        }

    def _generate_scene(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Default scene generation implementation"""
        # This would normally call an LLM
        scene_summary = params["scene_summary"]
        style_directives = params.get("style_directives", [])
        pov = params.get("pov", "third-person limited")

        return {
            "success": True,
            "content": f"# {scene_summary}\n\nGenerated scene content in {pov} perspective.\nStyle: {', '.join(style_directives)}"
        }

    def _check_consistency(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Default consistency check implementation"""
        text = params["text"]
        previous_content = params.get("previous_content", "")

        issues = []

        # Simple placeholder checks
        if "blue eyes" in text.lower() and "brown eyes" in previous_content.lower():
            issues.append("Character eye color description conflict detected")
        if "2023" in text and "2024" in previous_content.lower():
            issues.append("Timeline inconsistency detected")

        return {
            "success": True,
            "issues": issues,
            "count": len(issues)
        }

    def _refine_style(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Default style refinement implementation"""
        text = params["text"]
        style_directives = params["style_directives"]
        pov = params.get("pov", "third-person limited")

        return {
            "success": True,
            "refined_text": f"[STYLE REFINE] {text}\n\nAdjusted to match style directives: {', '.join(style_directives)}"
        }