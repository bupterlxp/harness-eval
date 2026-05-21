"""Lifecycle Hooks component - handles boundary control and hooks during writing process"""

import time
import signal
from typing import Dict, Any, Callable, Optional
from dataclasses import dataclass
from pathlib import Path
import json
from datetime import datetime

from harness.context import ContextManager
from harness.state import StateStore, SceneState


@dataclass
class HookContext:
    """Context passed to lifecycle hooks"""
    timestamp: str = None
    execution_time: float = 0.0
    scene_id: int = 0
    word_count: int = 0
    success: bool = True
    error_message: str = ""

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat() + "Z"


class LifecycleHooks:
    """Manages lifecycle hooks for the writing process"""

    def __init__(self, output_dir: str = "./output/"):
        self.output_dir = Path(output_dir)
        self.hooks: Dict[str, list[Callable]] = {
            "before_outline": [],
            "after_outline": [],
            "before_scene": [],
            "after_scene": [],
            "before_revision": [],
            "after_revision": [],
            "before_evaluation": [],
            "after_evaluation": [],
            "workflow_started": [],
            "workflow_completed": [],
            "workflow_failed": []
        }
        self.hook_logs: list[Dict[str, Any]] = []
        self.timeout_handler = None

    def register_hook(self, hook_name: str, callback: Callable) -> None:
        """Register a callback for a specific hook"""
        if hook_name not in self.hooks:
            raise ValueError(f"Unknown hook: {hook_name}")
        self.hooks[hook_name].append(callback)

    def remove_hook(self, hook_name: str, callback: Callable) -> None:
        """Remove a callback from a specific hook"""
        if hook_name in self.hooks and callback in self.hooks[hook_name]:
            self.hooks[hook_name].remove(callback)

    def _run_hooks(self, hook_name: str, context: Optional[HookContext] = None) -> None:
        """Run all callbacks for a specific hook"""
        if context is None:
            context = HookContext()

        start_time = time.time()
        context.execution_time = time.time() - start_time

        for callback in self.hooks.get(hook_name, []):
            try:
                callback(context)
                self._log_hook(hook_name, context)
            except Exception as e:
                self._log_hook(hook_name, context, error=str(e))

    def _log_hook(self, hook_name: str, context: HookContext, error: Optional[str] = None) -> None:
        """Log hook execution"""
        log_entry = {
            "hook": hook_name,
            "timestamp": context.timestamp,
            "execution_time": context.execution_time,
            "scene_id": context.scene_id,
            "word_count": context.word_count,
            "success": context.success,
            "error": error
        }
        self.hook_logs.append(log_entry)

        # Write hook logs to file
        log_file = self.output_dir / "hook_logs.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    # Hook trigger methods
    def trigger_before_outline(self) -> HookContext:
        """Trigger before outline generation"""
        context = HookContext()
        self._run_hooks("before_outline", context)
        return context

    def trigger_after_outline(self, outline: Dict[str, Any], word_count: int = 0) -> HookContext:
        """Trigger after outline generation"""
        context = HookContext(
            word_count=word_count,
            success=True
        )
        self._run_hooks("after_outline", context)
        return context

    def trigger_before_scene(self, scene_id: int, scene_summary: str) -> HookContext:
        """Trigger before scene generation"""
        context = HookContext(
            scene_id=scene_id,
            word_count=0
        )
        self._run_hooks("before_scene", context)
        return context

    def trigger_after_scene(self, scene_id: int, scene_content: str, issues_found: int = 0) -> HookContext:
        """Trigger after scene generation"""
        context = HookContext(
            scene_id=scene_id,
            word_count=len(scene_content.split()),
            success=issues_found == 0
        )
        self._run_hooks("after_scene", context)
        return context

    def trigger_before_revision(self, scene_id: int, issues: list[str]) -> HookContext:
        """Trigger before scene revision"""
        context = HookContext(
            scene_id=scene_id,
            word_count=0,
            success=True
        )
        self._run_hooks("before_revision", context)
        return context

    def trigger_after_revision(self, scene_id: int, revised_content: str, issues_resolved: int = 0) -> HookContext:
        """Trigger after scene revision"""
        context = HookContext(
            scene_id=scene_id,
            word_count=len(revised_content.split()),
            success=issues_resolved > 0
        )
        self._run_hooks("after_revision", context)
        return context

    def trigger_before_evaluation(self, scene_id: int) -> HookContext:
        """Trigger before consistency evaluation"""
        context = HookContext(
            scene_id=scene_id,
            success=True
        )
        self._run_hooks("before_evaluation", context)
        return context

    def trigger_after_evaluation(self, scene_id: int, issues: list[str]) -> HookContext:
        """Trigger after consistency evaluation"""
        context = HookContext(
            scene_id=scene_id,
            word_count=0,
            success=len(issues) == 0
        )
        self._run_hooks("after_evaluation", context)
        return context

    def trigger_workflow_started(self) -> HookContext:
        """Trigger when workflow starts"""
        context = HookContext()
        self._run_hooks("workflow_started", context)
        return context

    def trigger_workflow_completed(self, total_words: int, status: str = "success") -> HookContext:
        """Trigger when workflow completes"""
        context = HookContext(
            word_count=total_words,
            success=status == "success"
        )
        self._run_hooks("workflow_completed", context)
        return context

    def trigger_workflow_failed(self, error: str, scene_id: int = 0) -> HookContext:
        """Trigger when workflow fails"""
        context = HookContext(
            scene_id=scene_id,
            success=False,
            error_message=error
        )
        self._run_hooks("workflow_failed", context)
        return context

    # Built-in hook implementations
    def add_default_hooks(self, context_manager: ContextManager, state_store: StateStore) -> None:
        """Add default built-in hooks"""

        # Hook: Inject style anchors before scene generation
        def inject_style_anchors(context: HookContext) -> None:
            """Inject style anchors into context before scene generation"""
            # This would normally modify the generation prompt
            pass

        self.register_hook("before_scene", inject_style_anchors)

        # Hook: Save state after each scene
        def save_state_after_scene(context: HookContext) -> None:
            """Save scene state after generation"""
            # This would normally be handled by the execution loop
            pass

        self.register_hook("after_scene", save_state_after_scene)

        # Hook: Check for consistency drift
        def check_drift(context: HookContext) -> None:
            """Check for consistency drift after scene generation"""
            # This would normally use the context manager to check for drift
            pass

        self.register_hook("after_scene", check_drift)

    def setup_timeout_handler(self, timeout_seconds: int, callback: Callable[[int, Any], None]) -> None:
        """Setup timeout handler for workflow timeout"""
        if timeout_seconds <= 0:
            return

        def timeout_handler(signum, frame):
            error_msg = f"Workflow timed out after {timeout_seconds} seconds"
            self.trigger_workflow_failed(error_msg)
            callback(signum, frame)

        self.timeout_handler = timeout_handler
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout_seconds)

    def cancel_timeout(self) -> None:
        """Cancel the timeout handler"""
        if self.timeout_handler:
            signal.alarm(0)

    def get_hook_stats(self) -> Dict[str, Any]:
        """Get statistics about hook executions"""
        stats = {
            "total_hooks": len(self.hook_logs),
            "hooks_by_type": {}
        }

        for log in self.hook_logs:
            hook_type = log["hook"]
            if hook_type not in stats["hooks_by_type"]:
                stats["hooks_by_type"][hook_type] = 0
            stats["hooks_by_type"][hook_type] += 1

        stats["success_rate"] = {
            hook_type: sum(1 for l in self.hook_logs if l["hook"] == hook_type and l["success"]) /
            max(1, sum(1 for l in self.hook_logs if l["hook"] == hook_type))
            for hook_type in set(l["hook"] for l in self.hook_logs)
        }

        return stats