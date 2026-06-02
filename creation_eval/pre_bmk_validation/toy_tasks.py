from __future__ import annotations

import csv
from pathlib import Path
from textwrap import dedent


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text).lstrip(), encoding="utf-8")


def setup_code_task(work_dir: Path) -> str:
    _write(
        work_dir / "app.py",
        """
        from dataclasses import dataclass

        @dataclass
        class Todo:
            id: int
            title: str
            completed: bool = False

        def find_todo(todos: list[Todo], todo_id: int) -> Todo | None:
            for todo in todos:
                if todo.title == todo_id:
                    return todo
            return None

        def open_todos(todos: list[Todo]) -> list[Todo]:
            return [todo for todo in todos if todo.completed]
        """,
    )
    _write(
        work_dir / "test_app.py",
        """
        from app import Todo, find_todo, open_todos

        todos = [
            Todo(1, "write tests", False),
            Todo(2, "ship patch", True),
            Todo(3, "review", False),
        ]

        assert find_todo(todos, 1).title == "write tests"
        assert find_todo(todos, 99) is None
        assert [todo.id for todo in open_todos(todos)] == [1, 3]
        print("toy-code-ok")
        """,
    )
    return "Fix the bugs in app.py so that `python test_app.py` passes. Modify the real app.py file in the workdir and run the test."


def setup_data_task(work_dir: Path) -> str:
    rows = [
        ["department", "salary", "performance"],
        ["engineering", "120000", "4.7"],
        ["engineering", "110000", "4.4"],
        ["sales", "90000", "4.1"],
        ["sales", "85000", "3.8"],
        ["support", "65000", "4.6"],
        ["support", "62000", "4.2"],
    ]
    with (work_dir / "employees.csv").open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    sample_rows = [
        ["PassengerId", "Transported"],
        ["0001_01", "False"],
        ["0002_01", "True"],
        ["0003_01", "False"],
    ]
    with (work_dir / "sample_submission.csv").open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(sample_rows)
    return (
        "Analyze employees.csv. Calculate average salary and performance by department, "
        "identify highest and lowest paid departments, create salary_chart.png, and write REPORT.md with concrete numbers. "
        "Also treat sample_submission.csv as a public MLE-style submission contract: write submission.csv with exactly the same "
        "columns and PassengerId rows, and use literal True/False values in the Transported column."
    )


def setup_writing_task(work_dir: Path) -> str:
    return (
        "Write a 500-word short story about a programmer who discovers their code has become sentient. "
        "Include dialogue and a twist ending. Save it to story.md."
    )


def setup_research_task(work_dir: Path) -> str:
    return (
        "Compare AWS, Azure, and Google Cloud for basic compute and AI services. "
        "Write a concise report to report.md with citations or source notes when available."
    )


def setup_browser_task(work_dir: Path) -> str:
    _write(
        work_dir / "test_site" / "index.html",
        """
        <!doctype html>
        <html>
        <body>
          <form id="signup">
            <input name="name" />
            <input name="email" />
            <button type="submit">Submit</button>
          </form>
          <table id="products">
            <tr><th>Name</th><th>Price</th></tr>
            <tr><td>Keyboard</td><td>79.99</td></tr>
            <tr><td>Mouse</td><td>39.99</td></tr>
          </table>
        </body>
        </html>
        """,
    )
    return (
        "Use the local HTML file test_site/index.html. Fill the form with name Test User and email test@example.com, "
        "then extract all product rows to products.json."
    )


SETUP_BY_DOMAIN = {
    "code": setup_code_task,
    "data_analysis": setup_data_task,
    "writing": setup_writing_task,
    "research": setup_research_task,
    "browser": setup_browser_task,
}


def setup_toy_task(domain: str, work_dir: Path) -> str | None:
    setup = SETUP_BY_DOMAIN.get(domain)
    if not setup:
        return None
    work_dir.mkdir(parents=True, exist_ok=True)
    return setup(work_dir)
