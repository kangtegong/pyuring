#!/usr/bin/env python3
"""
Setup script for pyuring package.
"""

import subprocess
from pathlib import Path
from setuptools import setup
from setuptools.dist import Distribution
from setuptools.command.build_ext import build_ext
from setuptools.command.build_py import build_py


class BinaryDistribution(Distribution):
    """Mark wheel as non-pure (contains native shared library)."""

    def has_ext_modules(self):
        return True


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

        # Build liburingwrap.so.
        # This supports two paths:
        # 1) vendored third_party/liburing exists
        # 2) system liburing-dev/liburing-devel is installed
        print("Building liburingwrap.so...")
        try:
            subprocess.run(["make"], cwd=project_root, check=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                "Failed to build native library.\n"
                "Install system liburing headers (liburing-dev/liburing-devel), "
                "or initialize vendored liburing with:\n"
                "  git submodule update --init --recursive"
            ) from exc

    def copy_library(self):
        """Copy the built library to the package directory."""
        project_root = Path(__file__).parent
        src_lib = project_root / "build" / "liburingwrap.so"
        if not src_lib.exists():
            raise RuntimeError(f"Library not found: {src_lib}")
        import shutil

        dst_dir = project_root / "pyuring" / "lib"
        dst_dir.mkdir(exist_ok=True)
        dst_lib = dst_dir / "liburingwrap.so"
        shutil.copy2(src_lib, dst_lib)
        print(f"Copied {src_lib} to {dst_lib}")


class BuildPyWithNative(build_py):
    """Build Python package after native library is built."""

    def run(self):
        # Ensure native library is built first
        if not self.dry_run:
            build_ext_cmd = self.get_finalized_command('build_ext')
            build_ext_cmd.run()
        super().run()


setup(
    name="pyuring",
    version="0.1.0",
    description="Python bindings for io_uring with dynamic buffer size adjustment",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Kang Minchul",
    author_email="tegongkang@gmail.com",
    url="https://github.com/kangtegong/pyuring",
    license="MIT",
    project_urls={
        "Source": "https://github.com/kangtegong/pyuring",
        "Documentation": "https://github.com/kangtegong/pyuring/blob/main/README.md",
    },
    packages=["pyuring", "pyuring.lib"],
    package_data={
        "pyuring": ["lib/liburingwrap.so"],
    },
    include_package_data=True,
    python_requires=">=3.8",
    install_requires=[],
    cmdclass={
        "build_ext": BuildNative,
        "build_py": BuildPyWithNative,
    },
    distclass=BinaryDistribution,
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
