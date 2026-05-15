"""
Core Browser Agent Harness - Aggregates all six components:
H = (E, T, C, S, L, V)

Where:
- E: Execution Loop (double state machine)
- T: Tool Registry
- C: Context Manager
- S: State Store
- L: Lifecycle Hooks
- V: Evaluation Interface
"""

from typing import Dict, Optional

from .execution import ExecutionEngine
from .tools import BrowserTools
from .context import ContextManager
from .lifecycle import LifecycleHooks
from .evaluation import EvaluationRecorder
from .schemas import Config


class BrowserAgentHarness:
    """
    Complete browser agent harness that aggregates all six core components:
    H = (E, T, C, S, L, V)
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = Config(**(config or {}))

        # Initialize all six core components
        self._tool_registry = BrowserTools(self.config.__dict__)
        self._context_manager = ContextManager(self.config.__dict__)
        self._state_store = self._context_manager  # State store is integrated with context manager
        self._lifecycle_hooks = LifecycleHooks(
            self._tool_registry,
            self._context_manager,
            self.config.__dict__
        )
        self._evaluation_interface = EvaluationRecorder()
        self._execution_loop = ExecutionEngine(self.config.__dict__)

        # Wire up components
        self._execution_loop.tools = self._tool_registry
        self._execution_loop.context = self._context_manager
        self._execution_loop.lifecycle = self._lifecycle_hooks
        self._execution_loop.evaluator = self._evaluation_interface

    @property
    def execution_loop(self):
        """Get execution loop component (E)"""
        return self._execution_loop

    @property
    def tool_registry(self):
        """Get tool registry component (T)"""
        return self._tool_registry

    @property
    def context_manager(self):
        """Get context manager component (C)"""
        return self._context_manager

    @property
    def state_store(self):
        """Get state store component (S)"""
        return self._state_store

    @property
    def lifecycle_hooks(self):
        """Get lifecycle hooks component (L)"""
        return self._lifecycle_hooks

    @property
    def evaluation_interface(self):
        """Get evaluation interface component (V)"""
        return self._evaluation_interface

    def run_scenario(self, scenario_data: Dict) -> Dict:
        """Run a complete task scenario"""
        return self._execution_loop.run_task_sequence(scenario_data.get("scenario", {}).get("steps", []))

    def start(self):
        """Start the agent harness"""
        print("Starting Browser Agent Harness...")
        self._tool_registry.launch_browser()

    def stop(self):
        """Stop the agent harness"""
        print("Stopping Browser Agent Harness...")
        self._tool_registry.close_browser()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()