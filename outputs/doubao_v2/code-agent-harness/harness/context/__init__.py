"""
Context Manager component - manages LLM context window with summarization/compression
"""

import os
import json
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from abc import ABC, abstractmethod


@dataclass
class ContextItem:
    """Represents an item in the context window"""
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    size: int = 0

    def __post_init__(self):
        if self.size == 0:
            self.size = len(self.content.encode('utf-8'))


class ContextCompressor(ABC):
    """Abstract base class for context compression strategies"""

    @abstractmethod
    def compress(self, items: List[ContextItem], target_size: int) -> List[ContextItem]:
        """Compress context items to fit within target size"""
        pass


class SimpleContextCompressor(ContextCompressor):
    """Simple context compressor that removes least recently used items"""

    def compress(self, items: List[ContextItem], target_size: int) -> List[ContextItem]:
        total_size = sum(item.size for item in items)
        if total_size <= target_size:
            return items

        # Sort by importance/recency (simplified)
        sorted_items = sorted(items, key=lambda x: x.metadata.get('timestamp', 0), reverse=True)

        compressed = []
        current_size = 0

        for item in sorted_items:
            if current_size + item.size <= target_size:
                compressed.append(item)
                current_size += item.size
            else:
                # Truncate the item if needed
                remaining = target_size - current_size
                if remaining > 0:
                    truncated_content = item.content[:remaining] + "... [truncated]"
                    compressed.append(ContextItem(truncated_content, item.metadata, remaining))
                break

        return compressed


class ContextManager:
    """
    Manages LLM context window with automatic summarization and compression
    Prevents context overflow by keeping only relevant information
    """

    def __init__(
        self,
        max_context_size: int = 128000,  # Default to Claude 3 Sonnet context size
        compressor: Optional[ContextCompressor] = None
    ):
        self.max_context_size = max_context_size
        self.compressor = compressor or SimpleContextCompressor()
        self.context_items: List[ContextItem] = []
        self.item_cache: Dict[str, ContextItem] = {}
        self.total_size = 0

    def add_item(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Add an item to the context window"""
        if metadata is None:
            metadata = {}

        # Create unique ID for caching
        item_hash = hashlib.md5(f"{content}{json.dumps(metadata)}".encode()).hexdigest()

        if item_hash in self.item_cache:
            return item_hash

        item = ContextItem(content, metadata)
        self.context_items.append(item)
        self.item_cache[item_hash] = item
        self.total_size += item.size

        # Auto-compress if over max size
        self._enforce_size_limit()

        return item_hash

    def add_file_context(self, file_path: str, content: Optional[str] = None) -> str:
        """Add file content to context window"""
        if content is None:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")
            with open(file_path, 'r') as f:
                content = f.read()

        metadata = {
            "type": "file",
            "path": file_path,
            "size": len(content),
            "timestamp": os.path.getmtime(file_path)
        }

        return self.add_item(content, metadata)

    def add_code_snippet(self, code: str, language: str = "python", **kwargs) -> str:
        """Add a code snippet to context window"""
        metadata = {
            "type": "code_snippet",
            "language": language,
            **kwargs
        }

        return self.add_item(code, metadata)

    def add_search_results(self, results: List[str], query: str) -> str:
        """Add search results to context window"""
        content = f"Search results for '{query}:\n\n" + '\n'.join(results)
        metadata = {
            "type": "search_results",
            "query": query,
            "count": len(results)
        }

        return self.add_item(content, metadata)

    def get_context(self, prompt: str = "", system_prompt: str = "") -> Tuple[str, Dict[str, int]]:
        """
        Get full context window with prompt and system prompt
        Returns formatted context string and usage stats
        """
        # Calculate available size for context items
        system_size = len(system_prompt.encode('utf-8'))
        prompt_size = len(prompt.encode('utf-8'))
        available_size = self.max_context_size - system_size - prompt_size

        if available_size <= 0:
            raise ValueError("System prompt and input prompt exceed maximum context size")

        # Compress context to fit available size
        compressed_items = self.compressor.compress(self.context_items, available_size)

        # Build context string
        context_parts = []

        if system_prompt:
            context_parts.append(f"<system>{system_prompt}</system>")

        context_parts.append("<context>")
        for item in compressed_items:
            context_parts.append(f"<!-- {item.metadata.get('type', 'unknown')}: {json.dumps(item.metadata)} -->")
            context_parts.append(item.content)
            context_parts.append("<!-- end of item -->")
        context_parts.append("</context>")

        if prompt:
            context_parts.append(f"<input>{prompt}</input>")

        full_context = '\n'.join(context_parts)

        # Calculate stats
        stats = {
            "max_context_size": self.max_context_size,
            "system_prompt_size": system_size,
            "input_prompt_size": prompt_size,
            "available_size": available_size,
            "compressed_size": sum(item.size for item in compressed_items),
            "original_size": self.total_size,
            "items_kept": len(compressed_items),
            "items_total": len(self.context_items)
        }

        return full_context, stats

    def _enforce_size_limit(self):
        """Enforce the maximum context size by compressing or removing items"""
        if self.total_size <= self.max_context_size:
            return

        # Compress context
        compressed_items = self.compressor.compress(self.context_items, self.max_context_size)

        # Update state
        self.context_items = compressed_items
        self.total_size = sum(item.size for item in compressed_items)
        self.item_cache = {}
        for item in self.context_items:
            item_hash = hashlib.md5(f"{item.content}{json.dumps(item.metadata)}".encode()).hexdigest()
            self.item_cache[item_hash] = item

    def clear(self):
        """Clear all context items"""
        self.context_items = []
        self.item_cache = {}
        self.total_size = 0

    def get_stats(self) -> Dict[str, int]:
        """Get context window statistics"""
        return {
            "total_items": len(self.context_items),
            "total_size_bytes": self.total_size,
            "max_size_bytes": self.max_context_size,
            "remaining_bytes": self.max_context_size - self.total_size
        }

    def search_context(self, query: str) -> List[ContextItem]:
        """Search context items for matching content"""
        import re
        results = []
        pattern = re.compile(query, re.IGNORECASE)

        for item in self.context_items:
            if pattern.search(item.content) or pattern.search(json.dumps(item.metadata)):
                results.append(item)

        return results