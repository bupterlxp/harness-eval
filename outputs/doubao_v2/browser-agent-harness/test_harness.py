#!/usr/bin/env python3
"""Simple test script to verify the harness works"""
import asyncio
import json
import os
import tempfile
from harness.execution import ExecutionLoop
from harness import TaskSpec
from playwright.async_api import async_playwright


async def test_simple_extraction():
    """Test simple page extraction"""
    with tempfile.TemporaryDirectory() as tmpdir:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            try:
                task_spec = TaskSpec(
                    target_url="https://example.com",
                    task_description="Extract the main heading and paragraph from the page",
                    output_dir=tmpdir
                )

                executor = ExecutionLoop(task_spec)
                await executor.initialize(context)

                # Override _is_task_complete to just run for 2 steps
                original_complete = executor._is_task_complete
                executor._is_task_complete = lambda page: executor.current_step >= 2

                result = await executor.run()

                print(f"Test completed with status: {result.status}")
                print(f"Extracted data: {json.dumps(result.extracted_data, indent=2)}")
                print(f"Screenshots: {len(result.screenshots)}")
                print(f"Errors: {len(result.errors)}")

                # Check results
                assert result.status == "partial" or result.status == "success"
                assert len(result.extracted_data) > 0

                print("\n✓ Test passed!")

            finally:
                await context.close()
                await browser.close()


async def test_error_handling():
    """Test error handling and recovery"""
    with tempfile.TemporaryDirectory() as tmpdir:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            try:
                task_spec = TaskSpec(
                    target_url="https://example.com/invalid-page-1234",
                    task_description="Try to navigate to an invalid page",
                    output_dir=tmpdir,
                    max_steps=3
                )

                executor = ExecutionLoop(task_spec)
                await executor.initialize(context)

                result = await executor.run()

                print(f"\nError handling test completed with status: {result.status}")
                print(f"Errors encountered: {len(result.errors)}")
                print(f"Screenshots captured: {len(result.screenshots)}")

                assert result.status == "failed" or result.status == "partial"
                assert len(result.errors) > 0

                print("\n✓ Error handling test passed!")

            finally:
                await context.close()
                await browser.close()


if __name__ == "__main__":
    print("Running browser harness tests...\n")

    # Run simple extraction test
    print("1. Testing simple page extraction...")
    asyncio.run(test_simple_extraction())

    print("\n" + "="*50 + "\n")

    # Run error handling test
    print("2. Testing error handling...")
    asyncio.run(test_error_handling())

    print("\n✅ All tests completed!")