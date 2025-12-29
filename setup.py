"""Setup script for PyAOT.

For most uses, pyproject.toml is sufficient. This file
provides additional hooks for manylinux wheel building.
"""

from setuptools import setup, find_packages

if __name__ == "__main__":
    setup(
        packages=find_packages(),
    )
