import json
import os
from typing import Dict, Any, List, Optional


class StateStore:
    """Stores and manages task state for breakpoint resumption"""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.state_file = os.path.join(output_dir, "state.json")
        self.state: Dict[str, Any] = {}
        self._load_state()

    def _load_state(self):
        """Load existing state from file"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    self.state = json.load(f)
            except:
                self.state = {}

    def _save_state(self):
        """Save current state to file"""
        os.makedirs(self.output_dir, exist_ok=True)
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)

    async def initialize(self):
        """Initialize state store"""
        if "steps" not in self.state:
            self.state["steps"] = []
        if "extracted_data" not in self.state:
            self.state["extracted_data"] = {}
        if "current_step" not in self.state:
            self.state["current_step"] = 0
        self._save_state()

    async def save_step(self, step: int, data: Dict[str, Any]):
        """Save state for a specific step"""
        if "steps" not in self.state:
            self.state["steps"] = []

        # Find or create step entry
        step_entry = next((s for s in self.state["steps"] if s["step"] == step), None)
        if not step_entry:
            step_entry = {"step": step, "data": {}}
            self.state["steps"].append(step_entry)

        step_entry["data"] = data
        self.state["current_step"] = step
        self._save_state()

    async def get_step(self, step: int) -> Optional[Dict[str, Any]]:
        """Get state for a specific step"""
        if "steps" not in self.state:
            return None

        return next((s["data"] for s in self.state["steps"] if s["step"] == step), None)

    async def get_last_completed_step(self) -> int:
        """Get the last completed step"""
        if "steps" not in self.state or not self.state["steps"]:
            return 0

        return max(s["step"] for s in self.state["steps"])

    async def save_extracted_data(self, key: str, data: Any):
        """Save extracted data"""
        if "extracted_data" not in self.state:
            self.state["extracted_data"] = {}
        self.state["extracted_data"][key] = data
        self._save_state()

    async def get_extracted_data(self) -> Dict[str, Any]:
        """Get all extracted data"""
        return self.state.get("extracted_data", {})

    async def clear_state(self):
        """Clear all state"""
        self.state = {}
        self._save_state()