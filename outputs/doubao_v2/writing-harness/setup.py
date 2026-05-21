from setuptools import setup, find_packages

setup(
    name="creative-writing-harness",
    version="0.1.0",
    packages=find_packages(),
    include_package_data=True,
    description="A generic creative writing harness for AI-assisted writing",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Anthropic Claude",
    url="https://example.com/",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Topic :: Text Processing :: Linguistic",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    python_requires=">=3.11",
    install_requires=[
        "openai>=1.0.0",
    ],
    entry_points={
        "console_scripts": [
            "harness = harness.__main__:main",
        ],
    },
)