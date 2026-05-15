#!/usr/bin/env python3
"""Domain-specific prompt templates for short story generation"""

from typing import Dict, Any, Optional


def get_narrator_prompt(task_spec: Dict[str, Any]) -> str:
    """Get prompt for narrator profile generation"""
    return f"""Based on this story task specification, create a narrator profile:

Task Specification:
{task_spec}

Create a 50-100 word voice sample that captures the narrator's voice, and provide core motivation and speaking style.
Return ONLY valid JSON with no extra text:
{{
    "voice_sample": "<50-100 word sample of narrator's voice>",
    "perspective": "{task_spec.get('perspective', 'first_person')}",
    "unreliable": true,
    "core_motivation": "<core motivation/obsession>",
    "speaking_style": {{
        "sentence_length": "<short/medium/long>",
        "punctuation": "<exclamation/dashes/repetition>",
        "tone": "<tense/paranoid/confident/etc>"
    }}
}}
"""


def get_plot_outline_prompt(task_spec: Dict[str, Any], narrator_profile: Optional[Dict[str, Any]] = None) -> str:
    """Get prompt for plot outline generation"""
    return f"""Based on this story task specification and narrator profile, create a detailed plot outline with the following sections:
- setup_beats
- delay_segment (7 nights of buildup)
- climax
- concealment
- exposure
- confession

Task Specification:
{task_spec}

Narrator Profile:
{narrator_profile if narrator_profile else "Not provided"}

Return ONLY valid JSON with no extra text:
{{
    "title": "<story title>",
    "core_tension": "<central conflict>",
    "setup_beats": [<list of setup beats>],
    "delay_segment": [<list of delay segment beats>],
    "climax": [<list of climax beats>],
    "concealment": [<list of concealment beats>],
    "exposure": [<list of exposure beats>],
    "confession": [<list of confession beats>]
}}
"""


def get_scene_outline_prompt(plot_outline: Dict[str, Any], task_spec: Dict[str, Any]) -> str:
    """Get prompt for scene outline generation"""
    return f"""Based on this plot outline and task specification, create a scene-level outline with 5-10 scenes.

For each scene, provide:
- scene_id: sequential number
- title: short scene title
- pov: point of view
- time_position: when the scene takes place
- key_imagery: list of key imagery for the scene
- beats: list of key plot beats for the scene

Plot Outline:
{plot_outline}

Task Specification:
{task_spec}

Return ONLY valid JSON with no extra text:
{{
    "scenes": [
        {{
            "scene_id": 1,
            "title": "<scene title>",
            "pov": "{task_spec.get('perspective', 'first_person')}",
            "time_position": "<timing>",
            "key_imagery": [<list of imagery terms>],
            "beats": [<list of plot beats>]
        }},
        ...
    ]
}}
"""


def get_draft_scene_prompt(scene: Dict[str, Any], context: str, narrator_voice: str) -> str:
    """Get prompt for scene drafting"""
    return f"""Write a scene based on the following requirements:

Scene Details:
{scene}

{narrator_voice}

Context:
{context}

Write the full scene content in the voice of the narrator. Include the key imagery specified.
Return ONLY the scene text with no extra commentary:
"""


def get_consistency_check_prompt(
    scenes: str,
    established_imagery: Dict[str, Dict[str, Any]],
    task_spec: Dict[str, Any]
) -> str:
    """Get prompt for consistency checking"""
    return f"""Check the following story scenes for consistency:

1. Imagery consistency: Are there any inconsistent or contradictory imagery terms?
2. Timeline consistency: Does the timeline follow the expected progression?
3. Constraint violations: Do any scenes violate the task constraints?

Task Constraints:
{task_spec.get('key_constraints', {})}

Current Established Imagery:
{established_imagery}

Scenes to check:
{scenes}

Return ONLY valid JSON with no extra text:
{{
    "consistent": true/false,
    "issues": [<list of general issues>],
    "imagery_discrepancies": [<list of imagery issues>],
    "timeline_discrepancies": [<list of timeline issues>],
    "constraint_violations": [<list of constraint violations>]
}}
"""


def get_style_revision_prompt(
    scene_content: str,
    narrator_voice: str,
    style_requirements: Dict[str, Any]
) -> str:
    """Get prompt for style revision"""
    return f"""Revise this scene to match the following style requirements:

{narrator_voice}

Style Requirements:
{style_requirements}

Original Scene:
{scene_content}

Return ONLY the revised scene text with no extra commentary:
"""


def get_assemble_title_prompt(manuscript_excerpt: str, task_spec: Dict[str, Any]) -> str:
    """Get prompt for title generation"""
    return f"""Generate a compelling title for this story based on the task specification and content:

Task Specification:
{task_spec}

Content:
{manuscript_excerpt}...

Return ONLY the title with no extra text:
"""


def get_diff_comparison_prompt(actual_story: str, sample_story: str) -> str:
    """Get prompt for story comparison against sample"""
    return f"""Compare these two stories and provide a detailed comparison:

Sample Story (Poe's Tell-Tale Heart):
{sample_story}

Generated Story:
{actual_story}

Compare:
1. Structural elements (plot beats, pacing, time structure)
2. Style features (punctuation, sentence length, direct address)
3. Imagery and symbolism (especially auditory imagery)
4. Character and tone

Return the comparison as a structured markdown table.
"""


def parse_task_spec_input(raw_input: str) -> Dict[str, Any]:
    """Parse raw task input into structured format"""
    # This is a simplified parser - in production would use more robust parsing
    lines = raw_input.strip().split('\n')
    spec = {"raw_input": raw_input}

    current_section = None
    for line in lines:
        line = line.strip()
        if not line:
            continue

        if ':' in line and not line.startswith('-'):
            key, value = line.split(':', 1)
            key = key.strip().lower()
            value = value.strip()

            if '体裁' in key or 'genre' in key:
                spec['genre'] = [g.strip() for g in value.split('/')]
            elif '篇幅' in key or 'length' in key:
                if '–' in value or '-' in value:
                    parts = value.replace('–', '-').split('-')
                    spec['length_words'] = (int(parts[0].strip()), int(parts[1].strip()))
            elif '视角' in key or 'perspective' in key:
                spec['perspective'] = value
            elif '核心张力' in key or 'core_tension' in key:
                spec['core_tension'] = value
            elif '关键约束' in key or 'key_constraints' in key:
                current_section = 'key_constraints'
                spec['key_constraints'] = {}
            elif '风格要求' in key or 'style_requirements' in key:
                current_section = 'style_requirements'
                spec['style_requirements'] = {}
        elif line.startswith('-') and current_section:
            line = line.lstrip('- ').strip()
            if ':' in line:
                key, value = line.split(':', 1)
                spec[current_section][key.strip()] = value.strip()
            else:
                spec[current_section][line] = True

    return spec