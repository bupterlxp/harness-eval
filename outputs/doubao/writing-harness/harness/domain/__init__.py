#!/usr/bin/env python3
"""Domain-specific tools and prompts for short story generation"""

from .tools import (
    GenerateNarratorProfileTool, GeneratePlotOutlineTool, GenerateSceneOutlineTool,
    DraftSceneTool, CheckConsistencyTool, ReviseStyleTool, AssembleFinalManuscriptTool,
    CompareToSampleTool
)
from .prompts import (
    get_narrator_prompt, get_plot_outline_prompt, get_scene_outline_prompt,
    get_draft_scene_prompt, get_consistency_check_prompt, get_style_revision_prompt,
    get_assemble_title_prompt, get_diff_comparison_prompt, parse_task_spec_input
)

__all__ = [
    "GenerateNarratorProfileTool", "GeneratePlotOutlineTool", "GenerateSceneOutlineTool",
    "DraftSceneTool", "CheckConsistencyTool", "ReviseStyleTool", "AssembleFinalManuscriptTool",
    "CompareToSampleTool",
    "get_narrator_prompt", "get_plot_outline_prompt", "get_scene_outline_prompt",
    "get_draft_scene_prompt", "get_consistency_check_prompt", "get_style_revision_prompt",
    "get_assemble_title_prompt", "get_diff_comparison_prompt", "parse_task_spec_input"
]