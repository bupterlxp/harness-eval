from setuptools import setup, find_packages

setup(
    name="code-intelligence-harness",
    version="0.1.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "python-dotenv>=1.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "harness = harness.__main__:main",
        ],
    },
    author="Claude Code",
    description="A general-purpose code intelligence agent for software engineering tasks",
    long_description=open('README.md').read() if os.path.exists('README.md') else '',
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Quality Assurance",
        "Topic :: Software Development :: Testing",
        "Topic :: Software Development :: Debuggers",
    ],
    python_requires=">=3.11",
)