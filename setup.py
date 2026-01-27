#!/usr/bin/env python3
"""
Setup script for pyiouring package.
"""

import os
import sys
import subprocess
from pathlib import Path
from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext
from setuptools.command.build_py import build_py


class BuildNative(build_ext):
    """Build the native library before building the extension."""
    
    def run(self):
        # Build the native library
        self.build_native_lib()
        # Copy the library to the package directory
        self.copy_library()
        super().run()
    
    def build_native_lib(self):
        """Build liburingwrap.so using Makefile."""
        project_root = Path(__file__).parent
        build_dir = project_root / "build"
        build_dir.mkdir(exist_ok=True)
        
        # Check if liburing submodule exists
        liburing_dir = project_root / "third_party" / "liburing"
        if not liburing_dir.exists() or not (liburing_dir / ".git").exists():
            print("Initializing liburing submodule...")
            subprocess.run(
                ["git", "submodule", "update", "--init", "--recursive"],
                cwd=project_root,
                check=True
            )
        
        # Build liburing if needed
        liburing_a = liburing_dir / "src" / "liburing.a"
        if not liburing_a.exists():
            print("Building liburing...")
            subprocess.run(["make"], cwd=liburing_dir, check=True)
        
        # Build liburingwrap.so
        print("Building liburingwrap.so...")
        subprocess.run(["make"], cwd=project_root, check=True)
    
    def copy_library(self):
        """Copy the built library to the package directory."""
        project_root = Path(__file__).parent
        src_lib = project_root / "build" / "liburingwrap.so"
        dst_dir = project_root / "pyiouring" / "lib"
        dst_dir.mkdir(exist_ok=True)
        dst_lib = dst_dir / "liburingwrap.so"
        
        if src_lib.exists():
            import shutil
            shutil.copy2(src_lib, dst_lib)
            print(f"Copied {src_lib} to {dst_lib}")
        else:
            raise RuntimeError(f"Library not found: {src_lib}")


class BuildPyWithNative(build_py):
    """Build Python package after native library is built."""
    
    def run(self):
        # Ensure native library is built first
        if not self.dry_run:
            build_ext_cmd = self.get_finalized_command('build_ext')
            build_ext_cmd.run()
        super().run()


setup(
    name="pyiouring",
    version="0.1.0",
    description="Python bindings for io_uring with dynamic buffer size adjustment",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Your Name",
    author_email="your.email@example.com",
    url="https://github.com/kangtegong/adaptive_buffering",
    packages=["pyiouring"],
    package_data={
        "pyiouring": ["lib/liburingwrap.so"],
    },
    include_package_data=True,
    python_requires=">=3.6",
    install_requires=[],
    cmdclass={
        "build_ext": BuildNative,
        "build_py": BuildPyWithNative,
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: System :: Hardware",
        "Topic :: System :: Operating System Kernels :: Linux",
    ],
    zip_safe=False,
)

