#!/usr/bin/env python3
"""Setup script for data analysis agent harness"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="data-analysis-agent",
    version="1.0.0",
    author="Data Analysis Team",
    author_email="team@example.com",
    description="A comprehensive stateful data analysis agent harness",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://example.com/data-analysis-agent",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Information Analysis",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.11",
    install_requires=[
        "pandas>=2.0.0",
        "numpy>=1.24.0",
        "matplotlib>=3.7.0",
        "seaborn>=0.12.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "data-analyst = harness.cli:main",
        ],
    },
    keywords=[
        "data-analysis",
        "data-science",
        "analytics",
        "agent",
        "automation",
        "sales-analysis",
    ],
)
