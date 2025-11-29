"""
Direct planning mode for the HDD Folder Restructure Tool.

In direct mode, the LLM outputs explicit file moves.
"""

from ..llm import call_llm, parse_llm_json, build_llm_prompt, build_folder_prompt, DEFAULT_MODEL


def call_llm_for_plan(metadata: dict, model_name: str = DEFAULT_MODEL) -> dict:
    """
    Call the LLM to generate a restructuring plan for the entire directory.
    
    Args:
        metadata: Full metadata dict from build_metadata().
        model_name: Short model name (flash, flash-lite, pro).
        
    Returns:
        Plan dict with folders_to_create and moves.
    """
    prompt = build_llm_prompt(metadata)
    
    try:
        response_text = call_llm(prompt, model_name)
        plan = parse_llm_json(response_text)
        
        # Ensure required fields exist
        if "folders_to_create" not in plan:
            plan["folders_to_create"] = []
        if "moves" not in plan:
            plan["moves"] = []
        
        return plan
        
    except Exception as e:
        raise RuntimeError(f"LLM call failed: {e}")


def call_llm_for_folder(
    folder_metadata: dict, 
    all_folders: list[str],
    model_name: str = DEFAULT_MODEL
) -> dict:
    """
    Call the LLM to generate a plan for a single folder.
    
    Used in interactive and automatic modes for folder-by-folder processing.
    
    Args:
        folder_metadata: Metadata dict for a single folder.
        all_folders: List of all top-level folder names.
        model_name: Short model name (flash, flash-lite, pro).
        
    Returns:
        Plan dict with folders_to_create and moves.
    """
    prompt = build_folder_prompt(folder_metadata, all_folders)
    
    try:
        response_text = call_llm(prompt, model_name)
        plan = parse_llm_json(response_text)
        
        # Ensure required fields exist
        if "folders_to_create" not in plan:
            plan["folders_to_create"] = []
        if "moves" not in plan:
            plan["moves"] = []
        
        return plan
        
    except Exception as e:
        raise RuntimeError(f"LLM call failed: {e}")

