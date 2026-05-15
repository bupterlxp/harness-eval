import os
from typing import Optional, Dict, Any
from uuid import UUID
from .state import StateStore
from .context import ContextManager
from .tools import ToolRegistry
from .lifecycle import HookManager
from .evaluation import TrajectoryRecorder
from .execution import ExecutionLoop
from .schemas import TaskSpec, SessionInfo


class Harness:
    """Main harness class that aggregates all six components"""

    def __init__(self, db_path: str = "harness_state.db", output_dir: str = "trajectories"):
        self.state_store = StateStore(db_path)
        self.context_manager = ContextManager()
        self.tool_registry = ToolRegistry()
        self.hook_manager = HookManager()
        self.trajectory_recorder = TrajectoryRecorder(output_dir)
        self.current_session: Optional[SessionInfo] = None
        self.current_execution_loop: Optional[ExecutionLoop] = None

        # Initialize default hooks
        self._setup_default_hooks()

    def _setup_default_hooks(self):
        """Setup default hook handlers"""
        from .lifecycle import LoggingHookHandler
        import logging

        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger("harness")
        self.hook_manager.register_handler(LoggingHookHandler(logger))

    def create_session(self, task_spec: Optional[TaskSpec] = None) -> SessionInfo:
        """Create a new session"""
        session_info = self.state_store.create_session(task_spec.dict() if task_spec else None)
        self.current_session = session_info

        # Create execution loop
        self.current_execution_loop = ExecutionLoop(
            state_store=self.state_store,
            context_manager=self.context_manager,
            tool_registry=self.tool_registry,
            hook_manager=self.hook_manager,
            trajectory_recorder=self.trajectory_recorder,
            session_id=session_info.session_id,
            task_spec=task_spec
        )

        return session_info

    def load_session(self, session_id: UUID) -> Optional[SessionInfo]:
        """Load an existing session"""
        session_info = self.state_store.get_session(session_id)
        if not session_info:
            return None

        self.current_session = session_info

        # Recreate execution loop
        task_spec = TaskSpec(**session_info.task_spec) if session_info.task_spec else None
        self.current_execution_loop = ExecutionLoop(
            state_store=self.state_store,
            context_manager=self.context_manager,
            tool_registry=self.tool_registry,
            hook_manager=self.hook_manager,
            trajectory_recorder=self.trajectory_recorder,
            session_id=session_info.session_id,
            task_spec=task_spec
        )

        return session_info

    def register_tool(self, tool) -> None:
        """Register a tool with the registry"""
        self.tool_registry.register_tool(tool)

    def run_step(self) -> Dict[str, Any]:
        """Run one step of the current execution loop"""
        if not self.current_execution_loop:
            return {"error": "No active session"}

        result = self.current_execution_loop.step()

        # Update current session state
        if self.current_session:
            self.current_session.current_state = self.current_execution_loop.current_state
            self.state_store.update_session(self.current_session)

        return {
            "completed": result.completed,
            "next_state": result.next_state.value if result.next_state else None,
            "error": result.error,
            "result_data": result.result_data,
            "current_state": self.current_execution_loop.current_state.value
        }

    def run_to_completion(self, max_steps: int = 100) -> Dict[str, Any]:
        """Run the current session to completion"""
        if not self.current_execution_loop:
            return {"error": "No active session"}

        return self.current_execution_loop.run_to_completion(max_steps)

    def get_current_state(self) -> Optional[str]:
        """Get current state of execution loop"""
        if self.current_execution_loop:
            return self.current_execution_loop.current_state.value
        return None

    def save_manuscript(self, manuscript: str, output_path: str) -> None:
        """Save the final manuscript to file"""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(manuscript)

    def compare_to_sample(self, manuscript: str, sample_path: str = "../samples/the_tell_tale_heart.txt") -> Dict[str, Any]:
        """Compare generated manuscript to the sample story"""
        if not os.path.exists(sample_path):
            return {"error": f"Sample file not found at {sample_path}"}

        with open(sample_path, "r", encoding="utf-8") as f:
            sample_text = f.read()

        # Simple diff implementation - in real implementation, use proper NLP comparison
        sample_words = len(sample_text.split())
        actual_words = len(manuscript.split())

        return {
            "sample_word_count": sample_words,
            "actual_word_count": actual_words,
            "word_count_difference": abs(actual_words - sample_words),
            "sample_path": sample_path,
            "comparison_notes": "Basic word count comparison - implement full NLP comparison for production"
        }

    def close(self) -> None:
        """Clean up resources"""
        self.state_store.close()
        self.trajectory_recorder.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()