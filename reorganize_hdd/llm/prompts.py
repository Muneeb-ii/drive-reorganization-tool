"""
Prompt builders for LLM-based organization planning.

Provides prompts for:
- Direct mode: LLM outputs explicit file moves
- Rules mode: LLM outputs organization rules
"""

import json


def build_llm_prompt(metadata: dict) -> str:
    """
    Build a prompt for direct mode (LLM outputs explicit moves).
    
    Args:
        metadata: Full metadata dict from build_metadata().
        
    Returns:
        Prompt string for the LLM.
    """
    files = metadata.get("files", [])
    
    # Truncate if too many files (to avoid token limits)
    max_files = 500
    truncated = len(files) > max_files
    if truncated:
        files = files[:max_files]
    
    files_json = json.dumps(files, indent=2)
    
    truncation_note = ""
    if truncated:
        truncation_note = f"""
NOTE: The file list has been truncated to {max_files} files. 
Focus on the most impactful organizational changes for these files.
"""
    
    return f"""You are an expert file organization assistant. Analyze the following directory structure 
and propose a cleaner, more logical organization.

## Current Directory: {metadata.get('root', 'Unknown')}

## Files:
{files_json}
{truncation_note}

## Guidelines

1. **Be CONSERVATIVE**: Only propose moves that significantly improve organization.
2. **Preserve project structures**: Do NOT reorganize files inside .app, .dvdproj, .iMovieProject, .fcpproject, or similar application bundles.
3. **Use EXACT paths**: The "old_rel" must match exactly what's in the file list above.
4. **Do NOT rename files**: Only move them to different folders.
5. **Group by type/project**: Similar files should be grouped together.
6. **Return empty plan if already organized**: If the structure is reasonable, return empty arrays.

## Rules

- Do NOT propose moves where old_rel equals new_rel (no-op moves).
- Do NOT propose moves for files inside application bundles (.app, .dvdproj, etc.).
- Do NOT rename files - only move them to different directories.

## Output Format

Return ONLY a valid JSON object:

{{
  "folders_to_create": ["NewFolder/Subfolder"],
  "moves": [
    {{
      "old_rel": "exact/path/from/file/list.ext",
      "new_rel": "NewLocation/file.ext",
      "reason": "Brief reason"
    }}
  ]
}}

**NOTE**: The "old_rel" must be the EXACT "rel_path" value from the file list above. Copy it character-for-character.

If no changes are needed, return:
{{"folders_to_create": [], "moves": []}}
"""


def build_folder_prompt(folder_metadata: dict, all_folders: list[str]) -> str:
    """
    Build a prompt for organizing a single folder.
    
    Args:
        folder_metadata: Metadata dict for a single folder.
        all_folders: List of all top-level folder names (for context).
        
    Returns:
        Prompt string for the LLM.
    """
    files = folder_metadata.get("files", [])
    folder_name = folder_metadata.get("folder", "(root)")
    
    # Truncate if too many files
    max_files = 500
    truncated = len(files) > max_files
    if truncated:
        files = files[:max_files]
    
    files_json = json.dumps(files, indent=2)
    folders_list = "\n".join(f"  - {f}" for f in all_folders if f != folder_name)
    
    truncation_note = ""
    if truncated:
        truncation_note = f"\nNOTE: File list truncated to {max_files}. Focus on high-impact changes."
    
    return f"""You are an expert file organization assistant. Analyze files from the folder "{folder_name}" 
and propose how to better organize them.

## Current Folder: {folder_name}

## Other Existing Folders (for context - you can move files TO these):
{folders_list}

## Files in this folder:
{files_json}
{truncation_note}

## Guidelines

1. **Be CONSERVATIVE**: Only propose ESSENTIAL, high-value moves.
2. **Preserve project structures**: Do NOT touch files inside .app, .dvdproj, .iMovieProject, etc.
3. **Use EXACT paths**: Copy "rel_path" exactly for "old_rel".
4. **Prefer existing folders**: Move to existing folders rather than creating new ones.
5. **If well-organized**: Return empty plan.

## Output Format

Return ONLY valid JSON:

{{
  "folders_to_create": [],
  "moves": [
    {{
      "old_rel": "exact/path.ext",
      "new_rel": "NewLocation/path.ext", 
      "reason": "Brief reason"
    }}
  ]
}}

**CRITICAL**: "old_rel" must EXACTLY match "rel_path" from the file list.
"""


def build_rules_prompt(summary: dict) -> str:
    """
    Build a prompt for rule-based mode (LLM outputs organization rules).
    
    Instead of explicit moves, the LLM designs rules that Python applies locally.
    This scales better for huge directories.
    
    Args:
        summary: Metadata summary from build_metadata_summary().
        
    Returns:
        Prompt string for the LLM.
    """
    # Format the summary for the prompt
    ext_histogram = summary.get("extension_histogram", {})
    year_distribution = summary.get("year_distribution", {})
    folders = summary.get("folders", [])
    clusters = summary.get("clusters", [])
    
    # Top extensions
    top_extensions = list(ext_histogram.items())[:20]
    ext_lines = "\n".join(f"    {ext}: {count} files" for ext, count in top_extensions)
    
    # Year distribution
    year_lines = "\n".join(f"    {year}: {count} files" for year, count in year_distribution.items())
    
    # Folder summaries (abbreviated)
    folder_lines = []
    for f in folders[:30]:  # Limit to 30 folders
        folder_lines.append(f"  - {f['name']}: {f['file_count']} files, {f['total_size_bytes'] // (1024*1024):.1f}MB")
        # Show top 3 extensions for this folder
        top_exts = list(f.get('extensions', {}).items())[:3]
        if top_exts:
            ext_str = ", ".join(f"{e}:{c}" for e, c in top_exts)
            folder_lines.append(f"    Extensions: {ext_str}")
    
    folders_text = "\n".join(folder_lines)
    
    # Clusters (potential events)
    cluster_lines = []
    for i, c in enumerate(clusters[:20]): # Limit to 20 clusters
        c_type = c.get("type", "unknown").upper()
        name_hint = c.get("name_hint", "Unnamed")
        count = c.get("count", 0)
        d_start = c.get("date_start", "N/A")
        d_end = c.get("date_end", "N/A")
        samples = ", ".join(c.get("sample_files", [])[:3])
        
        cluster_lines.append(f"  - Cluster {i+1} [{c_type}]: {count} files. Hint: '{name_hint}'")
        cluster_lines.append(f"    Range: {d_start} to {d_end}")
        cluster_lines.append(f"    Samples: {samples}")
        
    clusters_text = "\n".join(cluster_lines) if cluster_lines else "No obvious clusters found."
    
    return f"""You are an expert file organization consultant. Based on the following directory summary,
design a set of RULES for organizing files. DO NOT list individual files - instead, define
patterns and templates that can be applied programmatically.

## Directory Summary

Root: {summary.get('root', 'Unknown')}
Total Files: {summary.get('total_files', 0)}
Total Size: {summary.get('total_size_bytes', 0) // (1024*1024*1024):.2f} GB

## File Types (by extension):
{ext_lines}

## File Dates (by year):
{year_lines}

## Existing Folders:
{folders_text}

## Detected File Clusters (Potential Events):
{clusters_text}

## Your Task

Design organization rules using this JSON schema:

{{
  "rules": [
    {{
      "name": "Human-readable rule name",
      "event_name": "Christmas",                 // Short event name for folder (e.g., "Christmas", "Wedding", "Vacation")
      "match": {{
        "ext_in": [".jpg", ".jpeg", ".png"],     // Optional: file extensions to match
        "ext_not_in": [".tmp"],                  // Optional: extensions to exclude
        "parent_name_contains_any": ["DCIM"],    // Optional: parent folder patterns
        "path_contains_any": ["Camera"],          // Optional: path substring patterns
        "date_start": "2023-12-24T00:00:00",      // Optional: match files after this date
        "date_end": "2023-12-26T23:59:59"         // Optional: match files before this date
      }},
      "target_template": "{{year}} - {{event_name}}/{{type}}/",  // Where to move matching files
      "priority": 10                             // Higher = checked first
    }}
  ]
}}

## Template Variables

Use these in target_template:
- {{year}} - Year from file modification date (e.g., "2023")
- {{month}} - Month name (e.g., "January")
- {{ext}} - File extension without dot (e.g., "jpg")
- {{type}} - Category (Photos, Videos, Documents, Misc)
- {{parent}} - Immediate parent folder name
- {{original_name}} - Original filename with extension

## Guidelines

1. **Be CONSERVATIVE**: Only create rules for clear, beneficial reorganization.
2. **Preserve projects**: Do NOT match files inside application bundles (.app, .dvdproj, etc.).
3. **Group by Event**: Use the "Detected Clusters" to create specific rules for events. Set `event_name` to a short, descriptive name (e.g., "Christmas", "Wedding", "Hawaii Trip").
4. **Structure**: Use `{{year}} - {{event_name}}/{{type}}/` in target_template. The `event_name` field will be substituted.
5. **Bundles**: If you see files with extension `/` (which represent folders like VIDEO_TS), keep them intact. Map them to `{{year}} - {{event_name}}/Misc/{{original_name}}`.
6. **Misc**: Create a catch-all rule for files that don't fit events. Set `event_name` to "Misc" or leave empty.
7. **Priority matters**: Specific event rules should have HIGH priority (e.g., 50). General rules (e.g., "All Photos") should have LOWER priority (e.g., 10).

## Output

Return ONLY valid JSON with your rules. If the directory is already well-organized, return:
{{"rules": []}}
"""

