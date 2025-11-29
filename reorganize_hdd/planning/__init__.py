"""
Planning module for the HDD Folder Restructure Tool.

Provides:
- Direct planning: LLM outputs explicit moves
- Rule-based planning: LLM outputs rules, Python applies them
- Plan validation
"""

from .validator import validate_plan
from .direct import call_llm_for_plan, call_llm_for_folder
from .rules import (
    OrganizationRule,
    MatchCriteria,
    generate_moves_from_rules,
    parse_rules_from_llm,
    call_llm_for_rules,
)

__all__ = [
    "validate_plan",
    "call_llm_for_plan",
    "call_llm_for_folder",
    "OrganizationRule",
    "MatchCriteria",
    "generate_moves_from_rules",
    "parse_rules_from_llm",
    "call_llm_for_rules",
]

