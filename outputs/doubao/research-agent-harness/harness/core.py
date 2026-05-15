from typing import List, Dict, Optional, Any
import asyncio
import os
from .execution import ResearchExecutionLoop
from .schemas import ResearchQuery
from .state import ResearchStateStore
from .context import ResearchContext


class ResearchHarness:
    """Main research harness that coordinates all components"""

    def __init__(self, output_dir: str = "./output"):
        self.output_dir = output_dir
        self.current_task: Optional[ResearchExecutionLoop] = None
        os.makedirs(output_dir, exist_ok=True)

    async def create_research_task(
        self,
        topic: str,
        questions: List[str],
        max_hops: int = 3
    ) -> ResearchExecutionLoop:
        """Create a new research task"""
        self.current_task = ResearchExecutionLoop(
            topic=topic,
            questions=questions,
            max_hops=max_hops,
            output_dir=self.output_dir
        )
        return self.current_task

    async def run_research_task(
        self,
        topic: str,
        questions: List[str],
        max_hops: int = 3
    ) -> str:
        """Create and run a complete research task"""
        task = await self.create_research_task(topic, questions, max_hops)
        return await task.run()

    async def list_available_tools(self) -> List[str]:
        """List all available tools"""
        if not self.current_task:
            return []
        return self.current_task.tools.list_tools()

    def get_current_progress(self) -> Dict[str, Any]:
        """Get current progress of the running task"""
        if not self.current_task:
            return {"status": "no_task_running"}

        return {
            "status": "running",
            "current_state": self.current_task.current_state,
            "loop_count": self.current_task.loop_count,
            "topic": self.current_task.topic,
            "sources_collected": len(self.current_task.state_store.state.all_sources),
            "evidence_collected": len(self.current_task.evidence_store.get_all_evidence()),
            "progress": self.current_task.context.get_overall_progress()
        }

    async def save_state(self, filepath: Optional[str] = None) -> str:
        """Save current research state"""
        if not self.current_task:
            return "No running task"

        if not filepath:
            filepath = os.path.join(self.output_dir, f"research_state_{os.urandom(4).hex()}.json")

        self.current_task.state_store.save(filepath)
        return f"State saved to: {filepath}"

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> 'ResearchHarness':
        """Create harness from configuration"""
        return cls(
            output_dir=config.get("output_dir", "./output")
        )


# Convenience function to run a quick research task
async def run_research(topic: str, questions: List[str], output_dir: str = "./output") -> str:
    """Quick function to run a research task"""
    harness = ResearchHarness(output_dir)
    return await harness.run_research_task(topic, questions)


if __name__ == "__main__":
    # Example usage
    import json

    # Load sample research questions
    with open("../samples/research_questions.json", "r", encoding="utf-8") as f:
        sample_data = json.load(f)
        topic = sample_data["research_task"]["topic"]
        questions = sample_data["research_task"]["questions"]

    print(f"Running sample research task: {topic}")
    asyncio.run(run_research(topic, questions))