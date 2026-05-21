"""Context Manager (C) - Manages LLM context window with summarization."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContentChunk:
    """A chunk of content with metadata."""
    content: str
    source: str
    chunk_type: str
    importance: float = 1.0
    token_estimate: int = 0

    def __post_init__(self) -> None:
        self.token_estimate = self._estimate_tokens(self.content)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return len(text) // 4


@dataclass
class FileSummary:
    """Summary of a file's content."""
    path: str
    language: str
    line_count: int
    functions: list[str]
    classes: list[str]
    imports: list[str]
    key_sections: list[dict[str, Any]]
    content_hash: str


class ContextManager:
    """Manages context window with intelligent summarization."""

    PROMPT_TEMPLATES: dict[str, str] = {
        "understand": """You are a code analysis assistant. Analyze the following task and repository structure.

TASK TYPE: {task_type}
TASK DESCRIPTION:
{task_description}

REPOSITORY STRUCTURE:
{repo_structure}

CONSTRAINTS:
{constraints}

Analyze this task and respond with a JSON object:
```json
{{
    "summary": "Brief summary of what needs to be done",
    "search_queries": ["keyword1", "function_name", "pattern to search"],
    "target_files": ["likely/file/paths.py"],
    "approach": "High-level approach to solving this"
}}
```""",

        "plan": """You are a code modification planner. Create a detailed plan for the following task.

TASK: {task_description}
TYPE: {task_type}

UNDERSTANDING:
{understanding}

RELEVANT FILES:
{file_summaries}

CONSTRAINTS:
{constraints}

{previous_errors}

Create a modification plan as JSON:
```json
{{
    "steps": [
        {{"file": "path/to/file.py", "instruction": "Specific change to make", "reason": "Why this change"}}
    ]
}}
```""",

        "edit": """You are a code editor. Make the following modification.

TASK: {task_description}

FILE: {file_path}
CURRENT CONTENT:
```
{current_content}
```

INSTRUCTION: {edit_instruction}

CONSTRAINTS:
{constraints}

Provide the complete modified file content:
```python
# Your modified code here
```""",

        "summarize": """Summarize the following code file, extracting key information:

FILE: {file_path}
CONTENT:
```
{content}
```

Provide a structured summary including:
1. Main purpose
2. Key functions/classes
3. Dependencies
4. Important logic sections""",
    }

    def __init__(
        self,
        max_context_tokens: int = 8000,
        max_file_tokens: int = 2000,
        summary_cache_size: int = 100,
    ) -> None:
        self.max_context_tokens = max_context_tokens
        self.max_file_tokens = max_file_tokens
        self._summary_cache: dict[str, FileSummary] = {}
        self._summary_cache_size = summary_cache_size
        self._chunks: list[ContentChunk] = []

    def build_prompt(self, template_name: str, **kwargs: Any) -> str:
        """Build a prompt from template with context management."""
        template = self.PROMPT_TEMPLATES.get(template_name, "{task_description}")

        formatted_kwargs = {}
        for key, value in kwargs.items():
            if isinstance(value, dict):
                formatted_kwargs[key] = self._format_dict(value)
            elif isinstance(value, list):
                formatted_kwargs[key] = self._format_list(value)
            elif value is None:
                formatted_kwargs[key] = ""
            else:
                formatted_kwargs[key] = str(value)

        try:
            prompt = template.format(**formatted_kwargs)
        except KeyError as e:
            prompt = template
            for k, v in formatted_kwargs.items():
                prompt = prompt.replace("{" + k + "}", v)

        token_estimate = self._estimate_tokens(prompt)
        if token_estimate > self.max_context_tokens:
            prompt = self._compress_prompt(prompt, self.max_context_tokens)

        return prompt

    def summarize_file(self, file_path: str, content: str) -> FileSummary:
        """Create or retrieve a summary of a file."""
        content_hash = hashlib.md5(content.encode()).hexdigest()

        if file_path in self._summary_cache:
            cached = self._summary_cache[file_path]
            if cached.content_hash == content_hash:
                return cached

        summary = self._create_file_summary(file_path, content, content_hash)

        if len(self._summary_cache) >= self._summary_cache_size:
            oldest = next(iter(self._summary_cache))
            del self._summary_cache[oldest]

        self._summary_cache[file_path] = summary
        return summary

    def truncate_content(self, content: str, max_tokens: int | None = None) -> str:
        """Truncate content to fit within token limit."""
        max_tokens = max_tokens or self.max_file_tokens
        token_estimate = self._estimate_tokens(content)

        if token_estimate <= max_tokens:
            return content

        lines = content.split("\n")
        total_lines = len(lines)

        head_lines = int(total_lines * 0.4)
        tail_lines = int(total_lines * 0.2)

        head = lines[:head_lines]
        tail = lines[-tail_lines:] if tail_lines > 0 else []

        truncated = "\n".join(head)
        truncated += f"\n\n... [{total_lines - head_lines - tail_lines} lines truncated] ...\n\n"
        truncated += "\n".join(tail)

        return truncated

    def add_chunk(self, content: str, source: str, chunk_type: str, importance: float = 1.0) -> None:
        """Add a content chunk to the context."""
        chunk = ContentChunk(
            content=content,
            source=source,
            chunk_type=chunk_type,
            importance=importance,
        )
        self._chunks.append(chunk)
        self._trim_chunks()

    def get_context(self) -> str:
        """Get current context as formatted string."""
        sorted_chunks = sorted(self._chunks, key=lambda c: -c.importance)
        parts: list[str] = []
        total_tokens = 0

        for chunk in sorted_chunks:
            if total_tokens + chunk.token_estimate > self.max_context_tokens:
                break
            parts.append(f"[{chunk.chunk_type}:{chunk.source}]\n{chunk.content}")
            total_tokens += chunk.token_estimate

        return "\n\n".join(parts)

    def clear_context(self) -> None:
        """Clear all context chunks."""
        self._chunks.clear()

    def _create_file_summary(self, file_path: str, content: str, content_hash: str) -> FileSummary:
        """Create a summary of file content without calling LLM."""
        lines = content.split("\n")
        language = self._detect_language(file_path)

        functions: list[str] = []
        classes: list[str] = []
        imports: list[str] = []
        key_sections: list[dict[str, Any]] = []

        if language == "python":
            for i, line in enumerate(lines):
                if re.match(r'^import\s+|^from\s+\w+\s+import', line):
                    imports.append(line.strip())
                elif match := re.match(r'^class\s+(\w+)', line):
                    classes.append(match.group(1))
                    key_sections.append({"type": "class", "name": match.group(1), "line": i + 1})
                elif match := re.match(r'^(?:async\s+)?def\s+(\w+)', line):
                    functions.append(match.group(1))
                    key_sections.append({"type": "function", "name": match.group(1), "line": i + 1})

        elif language in ("javascript", "typescript"):
            for i, line in enumerate(lines):
                if re.match(r'^import\s+|^const\s+\w+\s*=\s*require', line):
                    imports.append(line.strip()[:100])
                elif match := re.match(r'^class\s+(\w+)', line):
                    classes.append(match.group(1))
                elif match := re.match(r'^(?:async\s+)?function\s+(\w+)', line):
                    functions.append(match.group(1))
                elif match := re.match(r'^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(', line):
                    functions.append(match.group(1))

        return FileSummary(
            path=file_path,
            language=language,
            line_count=len(lines),
            functions=functions[:20],
            classes=classes[:10],
            imports=imports[:15],
            key_sections=key_sections[:30],
            content_hash=content_hash,
        )

    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension."""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".rb": "ruby",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
        }
        for ext, lang in ext_map.items():
            if file_path.endswith(ext):
                return lang
        return "unknown"

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        return len(text) // 4

    def _compress_prompt(self, prompt: str, max_tokens: int) -> str:
        """Compress prompt to fit within token limit."""
        current_tokens = self._estimate_tokens(prompt)
        if current_tokens <= max_tokens:
            return prompt

        code_blocks = re.findall(r'```[\s\S]*?```', prompt)
        for block in code_blocks:
            if len(block) > 1000:
                lines = block.split("\n")
                if len(lines) > 20:
                    compressed = "\n".join(lines[:10]) + "\n... [truncated] ...\n" + "\n".join(lines[-5:])
                    prompt = prompt.replace(block, compressed)

        sections = prompt.split("\n\n")
        if len(sections) > 5:
            kept = sections[:3] + ["... [middle sections compressed] ..."] + sections[-2:]
            prompt = "\n\n".join(kept)

        return prompt

    def _trim_chunks(self) -> None:
        """Trim chunks to fit within context limit."""
        total_tokens = sum(c.token_estimate for c in self._chunks)

        while total_tokens > self.max_context_tokens and self._chunks:
            min_importance = min(self._chunks, key=lambda c: c.importance)
            self._chunks.remove(min_importance)
            total_tokens -= min_importance.token_estimate

    def _format_dict(self, d: dict[str, Any], indent: int = 0) -> str:
        """Format dictionary for prompt."""
        lines: list[str] = []
        prefix = "  " * indent
        for key, value in d.items():
            if isinstance(value, dict):
                lines.append(f"{prefix}{key}:")
                lines.append(self._format_dict(value, indent + 1))
            elif isinstance(value, list):
                lines.append(f"{prefix}{key}: {self._format_list(value)}")
            else:
                lines.append(f"{prefix}{key}: {value}")
        return "\n".join(lines)

    def _format_list(self, lst: list[Any]) -> str:
        """Format list for prompt."""
        if not lst:
            return "[]"
        if len(lst) <= 5:
            return ", ".join(str(x) for x in lst)
        return ", ".join(str(x) for x in lst[:5]) + f" ... ({len(lst)} total)"
