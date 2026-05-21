from typing import Dict, Any, Optional

class TaskSpec:
    """Task specification for the browser automation harness"""
    target_url: str
    task_description: str
    credentials: Optional[Dict[str, str]]
    output_dir: str
    max_steps: int

    def __init__(self,
                 target_url: str,
                 task_description: str,
                 output_dir: str,
                 credentials: Optional[Dict[str, str]] = None,
                 max_steps: int = 50):
        self.target_url = target_url
        self.task_description = task_description
        self.credentials = credentials
        self.output_dir = output_dir
        self.max_steps = max_steps

class Result:
    """Result structure for the browser automation harness"""
    status: str  # "success" | "partial" | "failed"
    extracted_data: Dict[str, Any]
    screenshots: list[str]
    downloads: list[str]
    errors: list[Dict[str, Any]]
    trajectory: str

    def __init__(self):
        self.status = "failed"
        self.extracted_data = {}
        self.screenshots = []
        self.downloads = []
        self.errors = []
        self.trajectory = ""
