# Phase 1: Understanding & Planning

## 1. Sample Story Summary
I've read Edgar Allan Poe's *The Tell-Tale Heart*. This is a classic psychological thriller short story about an unreliable narrator who commits murder and is eventually driven to confess by the sound of the victim's heartbeat they believe they hear.

Key features:
- First-person unreliable narrator who insists they are sane
- Seven nights of delayed preparation before the murder
- Central auditory metaphor (heartbeat sound growing louder)
- Style with repetitive phrases, exclamation marks, and direct address to the reader
- Structure: Setup → 7 nights of surveillance → 8th night murder → Disguised body → Police visit → Confession

## 2. Core Requirements
The harness needs to:
- Accept task specifications (genre, length, perspective, tension, constraints, style)
- Follow a strict 8-step generation process as outlined in the trajectory
- Produce stories that match the structural, stylistic, and thematic patterns of the sample
- Provide CLI interaction with all the specified commands
- Track and persist state through the generation process
- Generate detailed evaluation trajectories for quality assurance

## 3. Architectural Components (from 6-tuple H = (E, T, C, S, L, V))

### E: Execution Loop (State Machine)
Need states for:
- Parsing task specification
- Generating narrator profile
- Creating plot outline
- Building scene-level大纲
- Drafting individual scenes
- Running consistency checks
- Revising style
- Assembling final manuscript

### T: Tool Registry
Required tools:
- Task parser (extract specs from input)
- Narrator voice generator
- Plot outline generator
- Scene outline generator
- Scene drafter
- Consistency checker (imagery, timeline, constraints)
- Style reviser
- Final assembler
- Diff comparator (against sample)

### C: Context Manager
Need to manage:
- Narrator voice samples
- Established imagery table
- Current scene history
- Overall plot outline
- Style anchor points
- Task specification storage

### S: State Store
Need:
- SQLite persistence
- Snapshot/restore functionality
- Session tracking with UUIDs
- Recovery from crashes

### L: Lifecycle Hooks
Need hook points for:
- Pre/tool call validation
- Approval for dangerous operations
- Pre/post generation events
- Logging/auditing

### V: Evaluation Interface
Need to generate:
- JSONL trajectory with all steps
- Intermediate state snapshots
- Detailed metrics for comparison against sample

## 4. Domain Failure Analysis
- **E missing**: Generation will lack structure, potentially loop indefinitely or fail to complete the narrative arc
- **T missing**: Without specific tools, the generator won't produce consistent imagery, style, or follow the required plot beats
- **C missing**: Context will become polluted, leading to inconsistent narrator voice, broken imagery chains, or excessive token usage
- **S missing**: Any interruption will lose all progress made so far
- **L missing**: No way to safely handle dangerous operations (API calls, file overwrites) or audit what's happening
- **V missing**: Can't objectively measure quality against the sample story or track generation progress

## 5. Tool清单 (Required Tools)
| Tool Name | IO Schema | Danger Level |
|-----------|-----------|--------------|
| parse_task_spec | Input: task string → Output: structured TaskSpec | safe |
| generate_narrator_profile | Input: TaskSpec → Output: NarratorProfile | needs_approval |
| generate_plot_outline | Input: TaskSpec, NarratorProfile → Output: PlotOutline | safe |
| generate_scene_outline | Input: PlotOutline → Output: List[Scene] | safe |
| draft_scene | Input: Scene, ContextManager → Output: SceneText | needs_approval |
| check_consistency | Input: SceneText, ContextManager → Output: ConsistencyReport | safe |
| revise_style | Input: SceneText, TaskSpec → Output: RevisedSceneText | needs_approval |
| assemble_final_manuscript | Input: List[SceneText] → Output: FullStory | safe |
| compare_to_sample | Input: FullStory → Output: DiffReport | safe |

## 6. Todo List

```python
from todo import TodoList, TodoItem

todos = TodoList([
    TodoItem(content="Create project structure and __init__.py", status="pending", activeForm="Creating project structure"),
    TodoItem(content="Implement Pydantic schemas (schemas.py)", status="pending", activeForm="Implementing Pydantic schemas"),
    TodoItem(content="Implement StateStore with SQLite (state.py)", status="pending", activeForm="Implementing StateStore"),
    TodoItem(content="Implement ToolRegistry and base Tool classes (tools.py)", status="pending", activeForm="Implementing ToolRegistry"),
    TodoItem(content="Implement ContextManager with compression/retrieval (context.py)", status="pending", activeForm="Implementing ContextManager"),
    TodoItem(content="Implement HookManager with approval hooks (lifecycle.py)", status="pending", activeForm="Implementing HookManager"),
    TodoItem(content="Implement TrajectoryRecorder (evaluation.py)", status="pending", activeForm="Implementing TrajectoryRecorder"),
    TodoItem(content="Implement ExecutionLoop state machine (execution.py)", status="pending", activeForm="Implementing ExecutionLoop"),
    TodoItem(content="Implement core Harness class (core.py)", status="pending", activeForm="Implementing core Harness class"),
    TodoItem(content="Implement CLI with all required commands (cli.py)", status="pending", activeForm="Implementing CLI"),
    TodoItem(content="Implement domain-specific tools (domain/tools.py)", status="pending", activeForm="Implementing domain tools"),
    TodoItem(content="Implement domain prompt templates (domain/prompts.py)", status="pending", activeForm="Implementing domain prompts"),
    TodoItem(content="Create test suite for all components", status="pending", activeForm="Creating test suite"),
    TodoItem(content="Run end-to-end test with sample task", status="pending", activeForm="Running end-to-end test"),
    TodoItem(content="Generate completeness report and sample diff", status="pending", activeForm="Generating final reports"),
])
```