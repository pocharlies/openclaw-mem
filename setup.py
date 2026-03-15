from setuptools import setup, find_packages

setup(
    name="openclaw-mem",
    version="0.1.0",
    description="Persistent memory plugin for OpenClaw — SQLite + FTS5 searchable memory across sessions",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="pocharlies",
    url="https://github.com/pocharlies/openclaw-mem",
    license="MIT",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "mcp>=1.0.0",
        "httpx>=0.27.0",
    ],
    entry_points={
        "console_scripts": [
            "openclaw-mem-import=openclaw_mem.importer:main",
            "openclaw-mem-sync=openclaw_mem.synthesizer:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries",
    ],
)
