from typing import Optional, List, Dict, Any
from .execution import AnalysisStateMachine
from .state import ExecutionStateManager
from .tools import ToolRegistry
from .lifecycle import LifecycleHooks
from .evaluation import TrajectoryTracker
from .context import AnalysisContext


class DataAnalysisAgent:
    """Main agent class that combines all components"""

    def __init__(
        self,
        analysis_goal: str,
        data_file: str,
        requirements: List[str],
        state_manager: Optional[ExecutionStateManager] = None,
        tool_registry: Optional[ToolRegistry] = None,
        lifecycle_hooks: Optional[LifecycleHooks] = None,
        trajectory_tracker: Optional[TrajectoryTracker] = None
    ):
        self.state_machine = AnalysisStateMachine(
            analysis_goal=analysis_goal,
            data_file=data_file,
            requirements=requirements,
            state_manager=state_manager,
            tool_registry=tool_registry,
            lifecycle_hooks=lifecycle_hooks,
            trajectory_tracker=trajectory_tracker
        )

        self.analysis_context = self.state_machine.analysis_context
        self.current_state = self.state_machine.current_state

    def execute_next_step(self, **kwargs) -> tuple[Any, ValidationResult]:
        """Execute the next analysis step"""
        return self.state_machine.execute_current_step(**kwargs)

    def change_state(self, new_state: str) -> bool:
        """Change the current analysis state"""
        return self.state_machine.change_state(new_state)

    def rollback(self, step_number: int) -> bool:
        """Rollback to a specific step number"""
        return self.state_machine.rollback_to_step(step_number)

    def get_context_summary(self) -> str:
        """Get full context summary"""
        return self.analysis_context.get_full_context_string()

    def save_analysis(self, output_dir: str = "analysis_results") -> Dict[str, str]:
        """Save complete analysis results"""
        import os
        import json
        from datetime import datetime

        os.makedirs(output_dir, exist_ok=True)

        # Save state
        state_file = os.path.join(output_dir, f"analysis_state_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        self.state_machine.state_manager.save_state(state_file)

        # Save trajectory
        trajectory_file = os.path.join(output_dir, "analysis_trajectory.jsonl")
        self.state_machine.trajectory_tracker.save_trajectory(trajectory_file)

        # Save summary
        summary_file = os.path.join(output_dir, "analysis_summary.md")
        self.state_machine.trajectory_tracker.save_summary(summary_file)

        # Save context
        context_file = os.path.join(output_dir, "analysis_context.json")
        with open(context_file, 'w') as f:
            json.dump({
                "analysis_goal": self.analysis_context.intent_context.analysis_goal,
                "data_file": self.analysis_context.intent_context.data_file,
                "requirements": self.analysis_context.intent_context.requirements,
                "completed_modules": self.analysis_context.intent_context.completed_modules,
                "current_focus": self.analysis_context.intent_context.current_focus,
                "total_steps": len(self.analysis_context.analysis_history.steps)
            }, f, indent=2)

        return {
            "state_file": state_file,
            "trajectory_file": trajectory_file,
            "summary_file": summary_file,
            "context_file": context_file
        }

    @classmethod
    def from_saved_state(cls, state_file: str) -> 'DataAnalysisAgent':
        """Load agent from saved state"""
        state_manager = ExecutionStateManager.load_state(state_file)
        agent = cls(
            analysis_goal="",
            data_file="",
            requirements=[],
            state_manager=state_manager
        )
        return agent


class AgentHarness:
    """Main harness for running data analysis agents"""

    @staticmethod
    def create_agent(
        analysis_goal: str,
        data_file: str,
        requirements: List[str],
        **kwargs
    ) -> DataAnalysisAgent:
        """Create a new data analysis agent"""
        return DataAnalysisAgent(
            analysis_goal=analysis_goal,
            data_file=data_file,
            requirements=requirements,
            **kwargs
        )

    @staticmethod
    def run_standard_analysis(
        data_file: str,
        analysis_goal: str = "Sales data analysis",
        requirements: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Run a complete standard analysis"""
        if requirements is None:
            requirements = [
                "Data overview and quality checks",
                "Sales trend analysis",
                "Regional sales comparison",
                "Category performance analysis",
                "Channel sales comparison",
                "Key business insights and recommendations"
            ]

        # Create agent
        agent = DataAnalysisAgent(
            analysis_goal=analysis_goal,
            data_file=data_file,
            requirements=requirements
        )

        # Execute full analysis flow
        results = {}

        try:
            # Load data
            data, validation = agent.execute_next_step(file_path=data_file)
            results["load"] = {"data": data, "validation": validation.__dict__}

            # Quality check
            quality, validation = agent.execute_next_step()
            results["quality_check"] = {"quality": quality, "validation": validation.__dict__}

            # Preprocess
            processed_df, validation = agent.execute_next_step()
            results["preprocess"] = {"dataframe": processed_df, "validation": validation.__dict__}

            # Explore
            stats, validation = agent.execute_next_step()
            results["explore"] = {"stats": stats, "validation": validation.__dict__}

            # Trend analysis
            trend, validation = agent.execute_next_step()
            results["trend"] = {"result": trend, "validation": validation.__dict__}

            # Region analysis
            region, validation = agent.execute_next_step()
            results["region"] = {"result": region, "validation": validation.__dict__}

            # Category analysis
            category, validation = agent.execute_next_step()
            results["category"] = {"result": category, "validation": validation.__dict__}

            # Channel analysis
            channel, validation = agent.execute_next_step()
            results["channel"] = {"result": channel, "validation": validation.__dict__}

            # Final report
            report, validation = agent.execute_next_step()
            results["report"] = {"report": report, "validation": validation.__dict__}

            # Save results
            save_paths = agent.save_analysis()
            results["save_paths"] = save_paths

            results["success"] = True
            results["message"] = "Analysis completed successfully"

        except Exception as e:
            results["success"] = False
            results["error"] = str(e)
            results["message"] = "Analysis failed"

        return results