"""Lifecycle Hooks module for creative writing boundary control.

Provides hooks for:
- Pre-generation: Inject style anchors before scene generation
- Post-generation: Check consistency after scene generation
- Timeout handling: Save current draft on interrupt
"""

import signal
from dataclasses import dataclass
from typing import Any, Callable
from pathlib import Path

from harness.context import ContextManager, StyleAnchor
from harness.evaluation import TrajectoryRecorder


@dataclass
class HookResult:
    """Result from a lifecycle hook."""
    success: bool
    data: dict[str, Any]
    error: str = ""


class LifecycleHooks:
    """Manages lifecycle hooks for the creative writing process."""

    def __init__(
        self,
        context_manager: ContextManager,
        trajectory_recorder: TrajectoryRecorder,
    ):
        self._context_manager = context_manager
        self._trajectory_recorder = trajectory_recorder
        self._timeout_handler: Callable[[], None] | None = None
        self._original_sigalrm: Any = None
        self._pre_scene_hooks: list[Callable[[int, str, str], HookResult]] = []
        self._post_scene_hooks: list[Callable[[int, str], HookResult]] = []

    def register_pre_scene_hook(
        self,
        hook: Callable[[int, str, str], HookResult],
    ) -> None:
        """Register a hook to run before scene generation."""
        self._pre_scene_hooks.append(hook)

    def register_post_scene_hook(
        self,
        hook: Callable[[int, str], HookResult],
    ) -> None:
        """Register a hook to run after scene generation."""
        self._post_scene_hooks.append(hook)

    def before_scene_generation(
        self,
        scene_id: int,
        scene_summary: str,
        prior_content: str,
    ) -> HookResult:
        """Hook called before generating a scene.

        Primary responsibility: Inject style anchor and context.
        """
        context_injection = self._context_manager.build_scene_context(
            scene_id=scene_id,
            scene_summary=scene_summary,
            prior_content=prior_content,
        )

        self._trajectory_recorder.record(
            phase="generating",
            action="pre_scene_hook",
            scene_id=scene_id,
            metadata={
                "style_anchor_injected": self._context_manager.style_anchor is not None,
                "context_length": len(context_injection),
            },
        )

        result_data = {
            "context_injection": context_injection,
            "style_anchor_injected": True,
        }

        for hook in self._pre_scene_hooks:
            hook_result = hook(scene_id, scene_summary, prior_content)
            if not hook_result.success:
                return HookResult(
                    success=False,
                    data=result_data,
                    error=hook_result.error,
                )
            result_data.update(hook_result.data)

        return HookResult(success=True, data=result_data)

    def after_scene_generation(
        self,
        scene_id: int,
        scene_content: str,
    ) -> HookResult:
        """Hook called after generating a scene.

        Primary responsibility: Trigger consistency check.
        """
        result_data = {
            "scene_id": scene_id,
            "word_count": len(scene_content.split()),
            "needs_consistency_check": True,
        }

        for hook in self._post_scene_hooks:
            hook_result = hook(scene_id, scene_content)
            if not hook_result.success:
                return HookResult(
                    success=False,
                    data=result_data,
                    error=hook_result.error,
                )
            result_data.update(hook_result.data)

        return HookResult(success=True, data=result_data)

    def on_consistency_check_complete(
        self,
        scene_id: int,
        is_consistent: bool,
        issues: list[str],
        severity: str,
        entity_updates: list[dict[str, Any]],
    ) -> HookResult:
        """Hook called after consistency check completes.

        Updates context manager with new entities discovered.
        """
        for update in entity_updates:
            self._context_manager.update_entity_attribute(
                name=update.get("entity", ""),
                attribute=update.get("attribute", ""),
                value=update.get("value", ""),
                scene_id=scene_id,
            )

        self._trajectory_recorder.record_consistency_check(
            scene_id=scene_id,
            is_consistent=is_consistent,
            issues=issues,
            severity=severity,
        )

        return HookResult(
            success=True,
            data={
                "entities_updated": len(entity_updates),
                "requires_revision": not is_consistent and severity in ["major", "minor"],
            },
        )

    def on_revision_start(
        self,
        scene_id: int,
        revision_type: str,
        revision_number: int,
        issues: list[str],
    ) -> HookResult:
        """Hook called before starting a revision."""
        context_injection = ""
        if self._context_manager.style_anchor:
            context_injection = self._context_manager.style_anchor.to_prompt_injection()

        self._trajectory_recorder.record(
            phase="revising",
            action="revision_start",
            scene_id=scene_id,
            metadata={
                "revision_type": revision_type,
                "revision_number": revision_number,
                "issues_to_fix": issues,
            },
        )

        return HookResult(
            success=True,
            data={
                "context_injection": context_injection,
                "style_anchor_injected": bool(context_injection),
            },
        )

    def on_timeout(
        self,
        save_callback: Callable[[], None],
    ) -> None:
        """Set up timeout handler to save current draft."""

        def timeout_handler(signum: int, frame: Any) -> None:
            self._trajectory_recorder.record(
                phase="interrupted",
                action="timeout",
                metadata={"signal": signum},
            )
            save_callback()
            raise TimeoutError("Writing task timed out - draft saved")

        self._timeout_handler = timeout_callback_wrapper(save_callback)
        self._original_sigalrm = signal.signal(signal.SIGALRM, timeout_handler)

    def set_timeout(self, seconds: int) -> None:
        """Set the timeout alarm."""
        signal.alarm(seconds)

    def clear_timeout(self) -> None:
        """Clear the timeout alarm and restore signal handler."""
        signal.alarm(0)
        if self._original_sigalrm is not None:
            signal.signal(signal.SIGALRM, self._original_sigalrm)
            self._original_sigalrm = None

    def on_phase_transition(
        self,
        from_phase: str,
        to_phase: str,
        total_word_count: int = 0,
    ) -> HookResult:
        """Hook called on phase transitions."""
        self._trajectory_recorder.record_phase_transition(
            from_phase=from_phase,
            to_phase=to_phase,
            total_word_count=total_word_count,
        )
        return HookResult(success=True, data={"from": from_phase, "to": to_phase})

    def on_error(
        self,
        phase: str,
        error: str,
        scene_id: int | None = None,
        save_callback: Callable[[], None] | None = None,
    ) -> HookResult:
        """Hook called on errors."""
        self._trajectory_recorder.record_error(
            phase=phase,
            error=error,
            scene_id=scene_id,
        )

        if save_callback:
            save_callback()

        return HookResult(
            success=True,
            data={"error_logged": True, "draft_saved": save_callback is not None},
        )

    def on_completion(
        self,
        status: str,
        total_word_count: int,
        num_scenes: int,
        consistency_issues: list[str],
    ) -> HookResult:
        """Hook called on writing completion."""
        self._trajectory_recorder.record_completion(
            status=status,
            total_word_count=total_word_count,
            num_scenes=num_scenes,
            consistency_issues=consistency_issues,
        )

        return HookResult(
            success=True,
            data={
                "status": status,
                "total_word_count": total_word_count,
                "num_scenes": num_scenes,
            },
        )

    def inject_style_anchor(
        self,
        pov: str,
        genre: str,
        style_directives: list[str],
    ) -> StyleAnchor:
        """Create and inject a style anchor into context manager."""
        anchor = self._context_manager.create_style_anchor(
            pov=pov,
            genre=genre,
            style_directives=style_directives,
        )

        self._trajectory_recorder.record_style_anchor_set(anchor.to_dict())

        return anchor

    def on_rollback(
        self,
        scene_id: int,
        reason: str,
        total_word_count: int = 0,
    ) -> HookResult:
        """Hook called when rolling back a scene."""
        self._trajectory_recorder.record_rollback(
            scene_id=scene_id,
            reason=reason,
            total_word_count=total_word_count,
        )
        return HookResult(
            success=True,
            data={"scene_id": scene_id, "reason": reason},
        )


def timeout_callback_wrapper(
    save_callback: Callable[[], None],
) -> Callable[[], None]:
    """Wrapper for timeout callback."""
    def wrapper() -> None:
        save_callback()
    return wrapper
