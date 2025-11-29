"""
LLM integration module for the HDD Folder Restructure Tool.

Provides:
- Gemini API client
- Prompt builders for direct and rule-based modes
- Model configurations
"""

from .client import call_llm, configure_gemini, parse_llm_json
from .models import GEMINI_MODELS, DEFAULT_MODEL
from .prompts import (
    build_llm_prompt,
    build_folder_prompt,
    build_rules_prompt,
)

__all__ = [
    "call_llm",
    "configure_gemini",
    "parse_llm_json",
    "GEMINI_MODELS",
    "DEFAULT_MODEL",
    "build_llm_prompt",
    "build_folder_prompt",
    "build_rules_prompt",
]

