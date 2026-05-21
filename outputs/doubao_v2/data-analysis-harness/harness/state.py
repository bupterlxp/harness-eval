"""
State Store component - persists analysis state and supports rollback
"""

import os
import json
import shutil
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

# Import ExecutionState locally to avoid circular import
from .execution import ExecutionState


def convert_keys_to_strings(data):
    """Convert all dictionary keys to strings recursively"""
    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            key_str = str(k)
            new_dict[key_str] = convert_keys_to_strings(v)
        return new_dict
    elif isinstance(data, list):
        return [convert_keys_to_strings(item) for item in data]
    else:
        return data


def json_serializer(obj):
    """Custom JSON serializer that handles pandas objects and datetime"""
    try:
        from pandas import Timestamp, Series, DataFrame
        if isinstance(obj, (Timestamp, datetime)):
            return str(obj)
        elif isinstance(obj, (Series, DataFrame)):
            return convert_keys_to_strings(obj.to_dict())
        elif hasattr(obj, '__dict__'):
            # Handle other objects by converting to dict
            return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
        else:
            return str(obj)
    except ImportError:
        # If pandas isn't available, just convert to string
        return str(obj)


class StateStore:
    """Stores and manages execution state snapshots"""

    def __init__(self, base_dir: str = "./state"):
        self.base_dir = base_dir
        self.snapshots_dir = os.path.join(base_dir, "snapshots")
        self._init_directories()

    def _init_directories(self) -> None:
        """Initialize the state directories"""
        os.makedirs(self.snapshots_dir, exist_ok=True)

    def save_snapshot(self, state: ExecutionState) -> str:
        """Save a snapshot of the current execution state"""
        # Create a sanitized version of all data
        snapshot_data = {
            "step": state.step,
            "completed": state.completed,
            "failed": state.failed,
            "error_message": state.error_message,
            "data": convert_keys_to_strings(state.data),
            "context": convert_keys_to_strings(state.context),
            "insights": state.insights,
            "charts": state.charts,
            "trajectory": convert_keys_to_strings(state.trajectory),
            "timestamp": datetime.now().isoformat()
        }

        # Save to file
        snapshot_path = os.path.join(self.snapshots_dir, f"step_{state.step:04d}.json")
        with open(snapshot_path, 'w') as f:
            json.dump(snapshot_data, f, indent=2, default=json_serializer)

        # Also keep an index of all snapshots
        index_path = os.path.join(self.base_dir, "snapshots_index.json")
        index = self._load_snapshot_index()
        index[state.step] = {
            "path": snapshot_path,
            "timestamp": snapshot_data["timestamp"],
            "step": state.step
        }
        with open(index_path, 'w') as f:
            json.dump(index, f, indent=2)

        return snapshot_path

    def load_snapshot(self, step: int) -> ExecutionState:
        """Load a saved state snapshot by step number"""
        index = self._load_snapshot_index()
        if step not in index:
            raise ValueError(f"No snapshot found for step {step}")

        snapshot_path = index[step]["path"]
        with open(snapshot_path, 'r') as f:
            snapshot_data = json.load(f)

        state = ExecutionState()
        state.step = snapshot_data["step"]
        state.completed = snapshot_data["completed"]
        state.failed = snapshot_data["failed"]
        state.error_message = snapshot_data["error_message"]
        state.data = snapshot_data["data"]
        state.context = snapshot_data["context"]
        state.insights = snapshot_data["insights"]
        state.charts = snapshot_data["charts"]
        state.trajectory = snapshot_data["trajectory"]

        return state

    def get_snapshot_history(self) -> List[Dict[str, Any]]:
        """Get the history of all saved snapshots"""
        index = self._load_snapshot_index()
        return sorted(index.values(), key=lambda x: x["step"])

    def clear_snapshots(self) -> None:
        """Clear all saved snapshots"""
        if os.path.exists(self.snapshots_dir):
            shutil.rmtree(self.snapshots_dir)
        os.makedirs(self.snapshots_dir, exist_ok=True)

        index_path = os.path.join(self.base_dir, "snapshots_index.json")
        if os.path.exists(index_path):
            os.remove(index_path)

    def rollback_to_step(self, step: int) -> Dict[str, Any]:
        """Rollback to a specific step and clear all subsequent snapshots"""
        state = self.load_snapshot(step)
        index = self._load_snapshot_index()

        # Remove all snapshots after the target step
        for s in list(index.keys()):
            if s > step:
                os.remove(index[s]["path"])
                del index[s]

        # Update index
        index_path = os.path.join(self.base_dir, "snapshots_index.json")
        with open(index_path, 'w') as f:
            json.dump(index, f, indent=2)

        return {
            "state": state,
            "removed_snapshots": [s for s in index.keys() if s > step]
        }

    def _load_snapshot_index(self) -> Dict[int, Dict[str, Any]]:
        """Load the snapshot index file"""
        index_path = os.path.join(self.base_dir, "snapshots_index.json")
        if not os.path.exists(index_path):
            return {}

        with open(index_path, 'r') as f:
            try:
                index = json.load(f)
                # Convert string keys back to integers
                return {int(k): v for k, v in index.items()}
            except json.JSONDecodeError:
                return {}

    def get_latest_snapshot(self) -> Optional[ExecutionState]:
        """Get the latest saved snapshot"""
        index = self._load_snapshot_index()
        if not index:
            return None

        latest_step = max(index.keys())
        return self.load_snapshot(latest_step)