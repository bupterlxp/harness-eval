"""
domain/prompts.py - Writing-specific prompt templates

Templates for narrator voice, scene drafting, style revision, and other
writing-specific LLM interactions.
"""

NARRATOR_VOICE_TEMPLATE = """You are crafting the voice for a first-person unreliable narrator in a {genre} story.

The narrator's characteristics:
- POV: {pov}
- Core tension: {core_tension}
- Obsession object: {obsession_object}

Generate a 50-100 word voice sample that establishes:
1. The narrator's distinctive speech patterns (fragmented? formal? breathless?)
2. Their relationship with the reader (confiding? defensive? pleading?)
3. Their mental state (anxious? triumphant? paranoid?)
4. Their attitude toward their obsession

Style markers to include:
- Dash usage: {dash_density}
- Exclamation frequency: {exclamation_density}
- Reader address: {reader_address_frequency}
- Repetition style: {repetition_style}
- Dominant sensory mode: {dominant_sensory}

The voice sample should feel like the opening of a confession - the narrator establishing their credibility while inadvertently revealing their instability.

Output only the voice sample, no explanation."""

PLOT_OUTLINE_TEMPLATE = """Create a seven-beat plot outline for a {genre} short story.

VOICE ANCHOR (maintain this tone in all plot descriptions):
{voice_sample}

STORY PARAMETERS:
- Core tension: {core_tension}
- Obsession object: {obsession_object}
- Temporal structure: {temporal_structure}
- Delay period: {delay_period}
- Climax trigger: {climax_trigger}
- Exposure signal type: {exposure_signal}
- Ending: {ending_type}
- Target length: {word_count_min}-{word_count_max} words

Generate exactly 7 beats with these proportions:
1. OBSESSION ESTABLISHMENT (~10%): Introduce narrator, obsession object, establish voice
2. DELAY/STALKING PERIOD (~25%): Build tension through repeated approach-and-wait
3. TRIGGER EVENT (~5%): What breaks the pattern and forces action
4. CLIMAX/ACT (~15%): The main event (murder, confrontation, etc.)
5. CONCEALMENT (~15%): How narrator hides evidence, believes they've succeeded
6. EXTERNAL PRESSURE (~15%): Outside force (visitors, police, etc.) tests the narrator
7. BREAKDOWN/CONFESSION (~15%): Sensory signal grows unbearable, narrator cracks

For each beat, specify:
- Beat name
- Description (2-3 sentences)
- Target word ratio
- Key imagery to establish or reference
- Emotional arc (what feeling should dominate)

Output as JSON matching this structure:
{{
  "beats": [...],
  "obsession_object": "...",
  "trigger_event": "...",
  "concealment_method": "...",
  "exposure_signal": "...",
  "confession_moment": "..."
}}"""

SCENE_OUTLINE_TEMPLATE = """Expand this seven-beat plot into specific scenes.

PLOT OUTLINE:
{plot_outline}

TARGET: {total_scenes} scenes, {word_count_min}-{word_count_max} words total

For each scene, specify:
- scene_id (0-indexed)
- beat_number (1-7)
- title (short, evocative)
- time_marker (when this occurs)
- location
- key_events (list of 2-4 events)
- imagery_to_establish (new images introduced)
- imagery_to_reference (callbacks to earlier images)
- target_word_count
- emotional_beat (one word: dread, triumph, paranoia, etc.)
- style_notes (specific style instructions for this scene)

SCENE DISTRIBUTION GUIDELINES:
- Beat 1 (obsession): 1-2 scenes
- Beat 2 (delay): 2-3 scenes (can compress multiple nights)
- Beat 3 (trigger): 1 scene
- Beat 4 (climax): 1-2 scenes
- Beat 5 (concealment): 1 scene
- Beat 6 (external pressure): 1-2 scenes
- Beat 7 (breakdown): 1-2 scenes

Output as JSON: {{"scenes": [...]}}"""

SCENE_DRAFT_TEMPLATE = """Draft scene {scene_id} of this short story.

NARRATOR VOICE (maintain exactly):
{voice_sample}

SCENE SPECIFICATION:
- Title: {title}
- Beat: {beat_number} ({beat_name})
- Time: {time_marker}
- Location: {location}
- Key events: {key_events}
- Emotional beat: {emotional_beat}
- Target words: {target_word_count}

IMAGERY TO ESTABLISH (introduce these):
{imagery_to_establish}

IMAGERY TO REFERENCE (callback to these):
{imagery_to_reference}

STYLE REQUIREMENTS:
- Dash density: {dash_density}
- Exclamation density: {exclamation_density}
- Reader address: {reader_address_frequency}
- Repetition: {repetition_style}
- Sensory focus: {dominant_sensory}
- Scene-specific notes: {style_notes}

PREVIOUS SCENES (for continuity):
{previous_scenes}

ESTABLISHED IMAGERY TABLE:
{imagery_table}

Write the scene now. Output only the narrative prose, no headers or meta-commentary.
Maintain the narrator's voice throughout. Use the specified imagery.
Target approximately {target_word_count} words."""

CONSISTENCY_CHECK_TEMPLATE = """Check these scenes for consistency issues.

TASK SPECIFICATION:
{task_spec}

IMAGERY TABLE:
{imagery_table}

SCENES:
{scenes}

Check for:
1. IMAGERY DRIFT: Does the obsession object stay consistent? Are introduced images referenced correctly?
2. TIMELINE ERRORS: Does the temporal sequence make sense? Any anachronisms?
3. VOICE SHIFT: Does the narrator's voice remain consistent? Any jarring changes in register?
4. REFERENCE MISSING: Are established images abandoned? Any dangling references?

For each issue found, report:
- issue_type: imagery_drift | timeline_error | voice_shift | reference_missing
- severity: critical | warning | suggestion
- scene_id: which scene
- description: what's wrong
- suggested_fix: how to fix it

Output as JSON: {{"passed": bool, "issues": [...], "imagery_coverage": {{}}, "timeline_valid": bool, "voice_coherence_score": float}}"""

STYLE_REVISION_TEMPLATE = """Revise these scenes for style consistency.

TARGET STYLE:
- Dash density: {dash_density} (aim for em-dashes between clauses, interruptions)
- Exclamation density: {exclamation_density} (build toward ending)
- Reader address: {reader_address_frequency} (direct "you" statements)
- Repetition: {repetition_style} (words repeated for emphasis, especially in climax)
- Sensory mode: {dominant_sensory} (foreground this sense)
- Sentence rhythm: {sentence_rhythm}

SCENES TO REVISE:
{scenes}

For each scene:
1. Adjust punctuation density to match targets
2. Ensure reader address appears at appropriate moments
3. Add/enhance repetition especially in high-tension moments
4. Foreground the dominant sensory mode
5. Vary sentence length for rhythm
6. Preserve all plot content and imagery

Output the revised scenes as JSON: {{"revised_scenes": ["scene 1 text", "scene 2 text", ...]}}"""

FINAL_ASSEMBLY_TEMPLATE = """Assemble these scenes into a final, polished story.

TASK SPECIFICATION:
{task_spec}

SCENES:
{scenes}

ASSEMBLY TASKS:
1. Ensure smooth transitions between scenes
2. Add any necessary connecting tissue
3. Check opening hook and closing impact
4. Verify the story works as a unified whole
5. Final polish for rhythm and flow

Do not change the content significantly - this is assembly, not rewriting.
Target word count: {word_count_min}-{word_count_max}

Output the complete story as continuous prose."""

COMPARISON_TEMPLATE = """Compare the generated story against this reference sample.

REFERENCE SAMPLE:
{sample_text}

GENERATED STORY:
{generated_text}

Analyze on three dimensions:

1. STRUCTURE:
- Does generated have equivalent seven-beat structure?
- Are beat proportions similar?
- Is pacing comparable?

2. STYLE:
- Dash/exclamation density comparison
- Reader address frequency
- Repetition patterns
- Sentence rhythm

3. IMAGERY:
- Does generated build equivalent imagery chain?
- Is the obsession object as consistent?
- Is the exposure signal as effective?

For each dimension, report:
- aspect: what you're comparing
- sample_value: value in reference
- actual_value: value in generated
- aligned: true/false
- gap_description: what's different
- component_attribution: E/T/C/S/L/V if misaligned

Output as JSON matching ComparisonReport schema."""

PROMPTS = {
    "narrator_voice": NARRATOR_VOICE_TEMPLATE,
    "plot_outline": PLOT_OUTLINE_TEMPLATE,
    "scene_outline": SCENE_OUTLINE_TEMPLATE,
    "scene_draft": SCENE_DRAFT_TEMPLATE,
    "consistency_check": CONSISTENCY_CHECK_TEMPLATE,
    "style_revision": STYLE_REVISION_TEMPLATE,
    "final_assembly": FINAL_ASSEMBLY_TEMPLATE,
    "comparison": COMPARISON_TEMPLATE,
}
