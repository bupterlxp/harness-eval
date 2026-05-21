#!/usr/bin/env python3
"""
Test script for the research agent harness
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all modules can be imported"""
    print("Testing module imports...")

    try:
        from harness import execution, tools, context, state, lifecycle, evaluation
        from harness.execution import ExecutionLoop
        from harness.tools import ToolRegistry
        from harness.context import ContextManager
        from harness.state import StateStore
        from harness.lifecycle import LifecycleHooks
        from harness.evaluation import Evaluator

        print("✅ All modules imported successfully")
        return True
    except Exception as e:
        print(f"❌ Import failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def test_tool_registry():
    """Test ToolRegistry functionality"""
    print("\nTesting ToolRegistry...")

    try:
        registry = ToolRegistry()
        tools_list = registry.list_tools()

        print(f"✅ Registered tools: {tools_list}")

        # Test mock search
        search_tool = registry.get_tool("search_web")
        if search_tool:
            results = search_tool("test query", num_results=3)
            print(f"✅ Mock search returned {len(results)} results")

        return True
    except Exception as e:
        print(f"❌ ToolRegistry test failed: {str(e)}")
        return False

def test_context_manager():
    """Test ContextManager functionality"""
    print("\nTesting ContextManager...")

    try:
        cm = ContextManager()

        # Test adding source
        from harness.tools import Source
        source = Source(
            id=1,
            url="https://example.com/test",
            title="Test Source",
            credibility="high",
            source_type=0
        )
        cm.add_source(source)

        # Test adding fact
        fact_id = cm.add_fact("Test fact statement", [1])
        print(f"✅ Added fact with ID: {fact_id}")

        # Test retrieval
        fact = cm.get_fact(fact_id)
        if fact:
            print(f"✅ Retrieved fact: {fact.content}")

        return True
    except Exception as e:
        print(f"❌ ContextManager test failed: {str(e)}")
        return False

def test_lifecycle_hooks():
    """Test LifecycleHooks functionality"""
    print("\nTesting LifecycleHooks...")

    try:
        hooks = LifecycleHooks()

        # Test deduplication
        query = "test query"
        is_new = hooks.pre_search_deduplicate(query)
        print(f"✅ First query check: {is_new}")

        is_duplicate = not hooks.pre_search_deduplicate(query)
        print(f"✅ Duplicate query check: {is_duplicate}")

        # Test source filtering
        test_sources = [
            {"url": "https://example.com/1"},
            {"url": "https://example.com/2"},
            {"url": "https://example.com/1"}  # Duplicate
        ]

        filtered = hooks.pre_search_url_filter(test_sources)
        print(f"✅ Filtered {len(test_sources)} sources to {len(filtered)}")

        return True
    except Exception as e:
        print(f"❌ LifecycleHooks test failed: {str(e)}")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Research Agent Harness - Test Suite")
    print("=" * 60)

    all_passed = True

    # Run tests
    all_passed &= test_imports()
    all_passed &= test_tool_registry()
    all_passed &= test_context_manager()
    all_passed &= test_lifecycle_hooks()

    print("\n" + "=" * 60)
    if all_passed:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()