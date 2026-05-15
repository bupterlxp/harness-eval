#!/usr/bin/env python3
"""Simple verification script for the harness"""

import os
import sys

def check_directory_structure():
    """Check that all required files exist"""
    required_files = [
        "harness/__init__.py",
        "harness/schemas.py",
        "harness/state.py",
        "harness/context.py",
        "harness/tools.py",
        "harness/lifecycle.py",
        "harness/evaluation.py",
        "harness/execution.py",
        "harness/core.py",
        "harness/cli.py",
        "harness/domain/tools.py",
        "harness/domain/prompts.py",
        "samples/the_tell_tale_heart.txt",
        "README.md",
        "example.py"
    ]

    print("📁 Checking directory structure...")
    all_good = True
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"✅ {file_path}")
        else:
            print(f"❌ {file_path} - MISSING")
            all_good = False

    return all_good

def check_imports():
    """Check that modules can be imported"""
    print("\n🔍 Checking module imports...")
    try:
        sys.path.insert(0, '.')
        from harness import Harness
        from harness.schemas import TaskSpec, StoryGenre, Perspective
        from harness.domain.tools import GenerateNarratorProfileTool
        print("✅ Successfully imported harness modules")
        return True
    except Exception as e:
        print(f"❌ Import failed: {str(e)}")
        return False

def check_sample_file():
    """Check that the sample file exists and has content"""
    print("\n📄 Checking sample file...")
    sample_path = "samples/the_tell_tale_heart.txt"
    if os.path.exists(sample_path):
        with open(sample_path, 'r', encoding='utf-8') as f:
            content = f.read()
            word_count = len(content.split())
            print(f"✅ Sample file found: {sample_path}")
            print(f"   Word count: ~{word_count} words")
            return True
    else:
        print(f"❌ Sample file not found at {sample_path}")
        return False

def main():
    """Run verification checks"""
    print("=== Short Story Generation Harness - Verification Script ===\n")

    checks = [
        ("Directory structure", check_directory_structure),
        ("Module imports", check_imports),
        ("Sample file", check_sample_file)
    ]

    passed = 0
    for name, check_func in checks:
        if check_func():
            passed += 1

    print(f"\n📊 Results: {passed}/{len(checks)} checks passed")

    if passed == len(checks):
        print("\n🎉 All checks passed! The harness is ready to use.")
        print("\n🚀 To get started:")
        print("   1. Set up your environment variables:")
        print("      export OPENAI_BASE_URL='http://127.0.0.1:3457/v1'")
        print("      export OPENAI_API_KEY='your-api-key'")
        print("      export MODEL_NAME='gpt-3.5-turbo'")
        print("   2. Run the CLI: python -m harness.cli")
        print("   3. Or run example: python example.py")
    else:
        print("\n⚠️  Some checks failed. Please fix the issues before using the harness.")

if __name__ == "__main__":
    main()