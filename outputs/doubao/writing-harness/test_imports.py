#!/usr/bin/env python3
"""Simple test without external dependencies"""

import sys
import os
sys.path.insert(0, '.')

def test_basic_imports():
    """Test basic imports without external dependencies"""
    print("Testing basic imports...")

    try:
        # Test core modules
        from harness.schemas import (
            StoryGenre, Perspective, Scene, PlotOutline,
            TaskSpec, GenerationState
        )
        print("✅ Schemas imported successfully")

        # Test state module
        from harness.state import StateStore
        print("✅ StateStore imported successfully")

        # Test context module
        from harness.context import ContextManager
        print("✅ ContextManager imported successfully")

        # Test tools module
        from harness.tools import ToolRegistry, ToolBase
        print("✅ ToolRegistry imported successfully")

        # Test lifecycle module
        from harness.lifecycle import HookManager, HookEventType
        print("✅ HookManager imported successfully")

        # Test evaluation module
        from harness.evaluation import TrajectoryRecorder
        print("✅ TrajectoryRecorder imported successfully")

        print("\n✅ All core modules imported successfully!")
        return True

    except Exception as e:
        print(f"❌ Import error: {str(e)}")
        return False

if __name__ == "__main__":
    print("=== Basic Module Import Test ===\n")

    if test_basic_imports():
        print("\n🎉 All basic tests passed!")
        print("\n📝 Next steps:")
        print("   - Install required dependencies: pydantic, openai")
        print("   - Set up environment variables for LLM access")
        print("   - Run the CLI: python -m harness.cli")
    else:
        print("\n❌ Some imports failed.")