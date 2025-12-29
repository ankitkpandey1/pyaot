"""Setup script for PyAOT.

For most uses, pyproject.toml is sufficient. This file
provides additional hooks for manylinux wheel building
and C extension compilation.
"""

import os
import sys
from setuptools import setup, find_packages, Extension

# Determine if we should build C extensions
BUILD_EXT = os.environ.get('PYAOT_BUILD_EXT', '1') != '0'

# C extension for fast attribute access
ext_modules = []

if BUILD_EXT:
    try:
        # Fast attribute access extension
        fast_attr_ext = Extension(
            'pyaot.shapes._fast_attr',
            sources=['pyaot/shapes/_fast_attr.c'],
            extra_compile_args=['-O3'] if sys.platform != 'win32' else ['/O2'],
            # Use limited API for better version compatibility
            # py_limited_api=True,
            # define_macros=[('Py_LIMITED_API', '0x03090000')],
        )
        ext_modules.append(fast_attr_ext)
    except Exception as e:
        print(f"Warning: Could not configure C extension: {e}")
        print("Building without C extension (pure Python fallback will be used)")


if __name__ == "__main__":
    setup(
        packages=find_packages(),
        ext_modules=ext_modules if ext_modules else None,
    )

