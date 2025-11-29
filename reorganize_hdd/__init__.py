"""
HDD Folder Restructure Tool
===========================

A command-line tool that uses Google Gemini LLM to propose and optionally apply
a cleaner folder structure for an existing directory.
"""

__version__ = "2.0.0"

from .scanner import scan_directory, build_metadata, build_metadata_summary
from .executor import apply_plan
from .utils import (
    save_json, 
    load_json, 
    is_macos_bundle, 
    path_contains_bundle,
    MACOS_BUNDLE_EXTENSIONS
)

__all__ = [
    "scan_directory",
    "build_metadata",
    "build_metadata_summary",
    "apply_plan",
    "save_json",
    "load_json",
    "is_macos_bundle",
    "path_contains_bundle",
    "MACOS_BUNDLE_EXTENSIONS",
]

