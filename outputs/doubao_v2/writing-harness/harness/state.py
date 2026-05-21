"""State Store component - persists and manages writing state"""

import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class SceneState:
    """Represents the state of a single scene"""
    id: int
    summary: str
    content: str
    word_count: int
    consistency_issues: List[str] = None
    revision_history: List[Dict[str, Any]] = None
    created_at: str = None
    updated_at: str = None

    def __post_init__(self):
        if self.consistency_issues is None:
            self.consistency_issues = []
        if self.revision_history is None:
            self.revision_history = []
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat() + "Z"
        if self.updated_at is None:
            self.updated_at = self.created_at


@dataclass
class ManuscriptState:
    """Represents the overall manuscript state"""
    scenes: Dict[int, SceneState] = None
    total_words: int = 0
    last_updated: str = None
    outline: Dict[str, Any] = None

    def __post_init__(self):
        if self.scenes is None:
            self.scenes = {}
        if self.last_updated is None:
            self.last_updated = datetime.utcnow().isoformat() + "Z"
        if self.outline is None:
            self.outline = {"beats": [], "scenes": []}


class StateStore:
    """Persists and manages writing state with scene-level snapshot and rollback"""

    def __init__(self, base_dir: str = "./output/"):
        self.base_dir = Path(base_dir)
        self.scenes_dir = self.base_dir / "scenes"
        self.manuscript_state_path = self.base_dir / "manuscript_state.json"
        self._init_directories()

    def _init_directories(self) -> None:
        """Initialize required directories"""
        self.scenes_dir.mkdir(parents=True, exist_ok=True)

    def save_scene(self, scene_state: SceneState) -> None:
        """Save a single scene to persistent storage"""
        # Create scene directory
        scene_dir = self.scenes_dir / f"scene_{scene_state.id}"
        scene_dir.mkdir(exist_ok=True)

        # Save scene content
        scene_file = scene_dir / "scene.json"
        with open(scene_file, "w") as f:
            json.dump(asdict(scene_state), f, indent=2, ensure_ascii=False)

        # Also save raw content
        content_file = scene_dir / "content.txt"
        with open(content_file, "w") as f:
            f.write(scene_state.content)

        # Update manuscript state
        self._update_manuscript_state(scene_state)

    def load_scene(self, scene_id: int) -> Optional[SceneState]:
        """Load a single scene from persistent storage"""
        scene_dir = self.scenes_dir / f"scene_{scene_id}"
        scene_file = scene_dir / "scene.json"

        if not scene_file.exists():
            return None

        with open(scene_file, "r") as f:
            scene_dict = json.load(f)

        return SceneState(**scene_dict)

    def delete_scene(self, scene_id: int) -> bool:
        """Delete a scene and its state"""
        scene_dir = self.scenes_dir / f"scene_{scene_id}"

        if not scene_dir.exists():
            return False

        shutil.rmtree(scene_dir)
        self._update_manuscript_state()
        return True

    def get_all_scenes(self) -> Dict[int, SceneState]:
        """Get all saved scenes"""
        scenes = {}

        for scene_dir in self.scenes_dir.iterdir():
            if scene_dir.is_dir() and scene_dir.name.startswith("scene_"):
                try:
                    scene_id = int(scene_dir.name.split("_")[1])
                    scene = self.load_scene(scene_id)
                    if scene:
                        scenes[scene_id] = scene
                except (IndexError, ValueError):
                    continue

        return scenes

    def save_manuscript_state(self, manuscript_state: ManuscriptState) -> None:
        """Save the overall manuscript state"""
        manuscript_state.last_updated = datetime.utcnow().isoformat() + "Z"

        with open(self.manuscript_state_path, "w") as f:
            json.dump(asdict(manuscript_state), f, indent=2, ensure_ascii=False)

    def load_manuscript_state(self) -> ManuscriptState:
        """Load the overall manuscript state"""
        if not self.manuscript_state_path.exists():
            return ManuscriptState()

        with open(self.manuscript_state_path, "r") as f:
            state_dict = json.load(f)

        # Convert scenes dict back to SceneState objects
        if "scenes" in state_dict:
            scenes_dict = state_dict["scenes"]
            state_dict["scenes"] = {}
            for scene_id_str, scene_data in scenes_dict.items():
                try:
                    scene_id = int(scene_id_str)
                    state_dict["scenes"][scene_id] = SceneState(**scene_data)
                except ValueError:
                    continue

        return ManuscriptState(**state_dict)

    def _update_manuscript_state(self, updated_scene: Optional[SceneState] = None) -> None:
        """Update the manuscript state with current scenes"""
        manuscript_state = self.load_manuscript_state()

        # Refresh all scenes
        all_scenes = self.get_all_scenes()
        manuscript_state.scenes = all_scenes

        # Recalculate total words
        manuscript_state.total_words = sum(s.word_count for s in all_scenes.values())
        manuscript_state.last_updated = datetime.utcnow().isoformat() + "Z"

        self.save_manuscript_state(manuscript_state)

    def rollback_to_scene(self, scene_id: int) -> ManuscriptState:
        """Rollback entire manuscript state to a specific scene"""
        # Load all scenes up to the specified one
        scenes_to_keep = {}
        total_words = 0

        for current_id in range(1, scene_id + 1):
            scene = self.load_scene(current_id)
            if scene:
                scenes_to_keep[current_id] = scene
                total_words += scene.word_count

        # Delete scenes after the specified one
        for scene_dir in self.scenes_dir.iterdir():
            if scene_dir.is_dir() and scene_dir.name.startswith("scene_"):
                try:
                    current_id = int(scene_dir.name.split("_")[1])
                    if current_id > scene_id:
                        shutil.rmtree(scene_dir)
                except (IndexError, ValueError):
                    continue

        # Update manuscript state
        manuscript_state = ManuscriptState()
        manuscript_state.scenes = scenes_to_keep
        manuscript_state.total_words = total_words

        self.save_manuscript_state(manuscript_state)
        return manuscript_state

    def get_scene_snapshot(self, scene_id: int) -> Dict[str, Any]:
        """Get a snapshot of the entire state at a specific scene"""
        scene = self.load_scene(scene_id)
        if not scene:
            return {}

        all_scenes = self.get_all_scenes()
        previous_scenes = {id: s for id, s in all_scenes.items() if id < scene_id}

        return {
            "current_scene": asdict(scene),
            "previous_scenes": {id: asdict(s) for id, s in previous_scenes.items()},
            "total_words_up_to_now": sum(s.word_count for s in previous_scenes.values()) + scene.word_count
        }

    def list_state_files(self) -> List[str]:
        """List all state files"""
        files = []

        # Add manuscript state file
        if self.manuscript_state_path.exists():
            files.append(str(self.manuscript_state_path))

        # Add scene files
        for scene_dir in self.scenes_dir.iterdir():
            if scene_dir.is_dir() and scene_dir.name.startswith("scene_"):
                for file in scene_dir.iterdir():
                    if file.is_file():
                        files.append(str(file))

        return files