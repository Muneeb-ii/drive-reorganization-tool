"""
Rule-based planning for the HDD Folder Restructure Tool.

In rule-based mode, the LLM designs organization rules, and Python applies them locally.
This scales much better for huge directories.
"""

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Generator

from ..llm import call_llm, parse_llm_json, build_rules_prompt, DEFAULT_MODEL


@dataclass
class MatchCriteria:
    """
    Criteria for matching files to an organization rule.
    
    All specified criteria must match (AND logic).
    """
    ext_in: list[str] | None = None
    ext_not_in: list[str] | None = None
    parent_name_contains_any: list[str] | None = None
    path_contains_any: list[str] | None = None
    min_size_bytes: int | None = None
    max_size_bytes: int | None = None
    date_start: str | None = None  # ISO 8601 date string
    date_end: str | None = None    # ISO 8601 date string
    
    def matches(self, file_info: dict) -> bool:
        """
        Check if a file matches all specified criteria.
        
        Args:
            file_info: File metadata dict with rel_path, ext, size_bytes, etc.
            
        Returns:
            True if all criteria match.
        """
        ext = file_info.get("ext", "").lower()
        rel_path = file_info.get("rel_path", "")
        size = file_info.get("size_bytes", 0)
        # Prefer date_taken (EXIF) over modified date
        modified = file_info.get("date_taken") or file_info.get("modified", "")
        
        # Get parent folder name
        parts = rel_path.split("/")
        parent_name = parts[-2] if len(parts) > 1 else ""
        
        # Check extension inclusion
        if self.ext_in is not None:
            normalized_exts = [e.lower() if e.startswith('.') else f'.{e.lower()}' 
                             for e in self.ext_in]
            if ext not in normalized_exts:
                return False
        
        # Check extension exclusion
        if self.ext_not_in is not None:
            normalized_exts = [e.lower() if e.startswith('.') else f'.{e.lower()}' 
                             for e in self.ext_not_in]
            if ext in normalized_exts:
                return False
        
        # Check parent name patterns
        if self.parent_name_contains_any is not None:
            parent_lower = parent_name.lower()
            if not any(p.lower() in parent_lower for p in self.parent_name_contains_any):
                return False
        
        # Check path patterns
        if self.path_contains_any is not None:
            path_lower = rel_path.lower()
            if not any(p.lower() in path_lower for p in self.path_contains_any):
                return False
        
        # Check size constraints
        if self.min_size_bytes is not None and size < self.min_size_bytes:
            return False
        if self.max_size_bytes is not None and size > self.max_size_bytes:
            return False
            
        # Check date ranges
        if (self.date_start is not None or self.date_end is not None) and modified:
            try:
                dt = datetime.fromisoformat(modified)
                if self.date_start:
                    dt_start = datetime.fromisoformat(self.date_start)
                    if dt < dt_start:
                        return False
                if self.date_end:
                    dt_end = datetime.fromisoformat(self.date_end)
                    if dt > dt_end:
                        return False
            except (ValueError, TypeError):
                # If date parsing fails, assume no match for date rules
                if self.date_start or self.date_end:
                    return False
        
        return True
    
    @classmethod
    def from_dict(cls, data: dict) -> "MatchCriteria":
        """Create MatchCriteria from a dict (e.g., from LLM JSON)."""
        return cls(
            ext_in=data.get("ext_in"),
            ext_not_in=data.get("ext_not_in"),
            parent_name_contains_any=data.get("parent_name_contains_any"),
            path_contains_any=data.get("path_contains_any"),
            min_size_bytes=data.get("min_size_bytes"),
            max_size_bytes=data.get("max_size_bytes"),
            date_start=data.get("date_start"),
            date_end=data.get("date_end"),
        )


@dataclass
class OrganizationRule:
    """
    A rule for organizing files into a target location.
    
    The target_template supports variables:
    - {year} - Year from file modification date
    - {month} - Month name from modification date
    - {ext} - File extension without dot
    - {type} - Category (Photos, Videos, Documents, Misc)
    - {parent} - Immediate parent folder name
    - {original_name} - Original filename with extension
    - {event_name} - Event name (e.g., "Christmas", "Wedding")
    """
    name: str
    match: MatchCriteria
    target_template: str
    priority: int = 0
    event_name: str = ""  # Optional event name for {event_name} template variable
    
    def render_target(self, file_info: dict) -> str:
        """
        Render the target path for a file using the template.
        
        Args:
            file_info: File metadata dict.
            
        Returns:
            Rendered target path.
        """
        rel_path = file_info.get("rel_path", "")
        ext = file_info.get("ext", "").lstrip(".")
        # Prefer date_taken (EXIF) over modified date
        modified = file_info.get("date_taken") or file_info.get("modified", "")
        
        # Parse filename and parent
        if not rel_path:
            return rel_path
            
        parts = rel_path.split("/")
        original_name = parts[-1]
        if not original_name:
            # Should not happen if rel_path is valid, but safe check
            return rel_path
            
        parent = parts[-2] if len(parts) > 1 else ""
        
        # Parse date info
        year = "Unknown"
        month = "Unknown"
        if modified:
            try:
                dt = datetime.fromisoformat(modified)
                year = str(dt.year)
                month = calendar.month_name[dt.month]
            except (ValueError, TypeError):
                pass
                
        # Determine type
        file_type = "Misc"
        ext_lower = ext.lower()
        if ext_lower in ["jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp", "heic", "raw", "cr2", "nef"]:
            file_type = "Photos"
        elif ext_lower in ["mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v"]:
            file_type = "Videos"
        elif ext_lower in ["pdf", "doc", "docx", "txt", "rtf", "odt", "xls", "xlsx", "ppt", "pptx", "md"]:
            file_type = "Documents"
        
        # Render template
        target = self.target_template
        target = target.replace("{year}", year)
        target = target.replace("{month}", month)
        target = target.replace("{ext}", ext)
        target = target.replace("{type}", file_type)
        target = target.replace("{parent}", parent)
        target = target.replace("{original_name}", original_name)
        target = target.replace("{event_name}", self.event_name or "Misc")
        
        # Ensure path ends with filename
        if not target.endswith(original_name):
            target = target.rstrip("/") + "/" + original_name
            
        # Deduplicate path segments (e.g. "Misc/Misc" -> "Misc")
        # This happens when {event_name} defaults to "Misc" and the template also has "Misc"
        parts = target.split("/")
        deduped_parts = []
        if parts:
            deduped_parts.append(parts[0])
            for i in range(1, len(parts)):
                prev = parts[i-1]
                curr = parts[i]
                
                # Check for exact duplicate
                if curr == prev:
                    continue
                    
                # Check for suffix duplication (e.g. "2023 - Misc" followed by "Misc")
                # We check if the previous part ends with " - {curr}" or " {curr}"
                if prev.endswith(f" - {curr}") or prev.endswith(f" {curr}"):
                    continue
                    
                deduped_parts.append(curr)
            target = "/".join(deduped_parts)
        
        return target
    
    @classmethod
    def from_dict(cls, data: dict) -> "OrganizationRule":
        """Create OrganizationRule from a dict (e.g., from LLM JSON)."""
        match_data = data.get("match", {})
        return cls(
            name=data.get("name", "Unnamed rule"),
            match=MatchCriteria.from_dict(match_data),
            target_template=data.get("target_template", "{parent}/{original_name}"),
            priority=data.get("priority", 0),
            event_name=data.get("event_name", ""),
        )




def generate_moves_from_rules(
    files: Iterable[dict], 
    rules: list[OrganizationRule]
) -> Generator[dict, None, None]:
    """
    Generate a stream of moves by applying rules to files.
    
    Rules are applied in priority order (highest first). The first matching
    rule determines where a file is moved.
    
    Handles destination collisions by appending a counter to the filename.
    
    Args:
        files: Iterable of file metadata dicts.
        rules: List of organization rules.
        
    Yields:
        Move dicts with old_rel, new_rel, and reason.
    """
    seen_destinations = set()
    next_counters = {} # Map of target_path -> next_available_counter
    
    # Sort rules by priority (highest first)
    sorted_rules = sorted(rules, key=lambda r: -r.priority)
    
    for file_info in files:
        old_rel = file_info.get("rel_path", "")
        if not old_rel:
            continue
            
        # Normalize old_rel immediately for consistent comparison
        old_rel = old_rel.replace("\\", "/")
        
        # Find first matching rule
        for rule in sorted_rules:
            if rule.match.matches(file_info):
                new_rel = rule.render_target(file_info)
                # Normalize new_rel immediately
                new_rel = new_rel.replace("\\", "/")
                
                # Skip no-op moves
                if old_rel == new_rel:
                    continue
                
                # Handle collisions
                if new_rel in seen_destinations:
                    # Append counter: path/file.ext -> path/file_1.ext
                    path_obj = Path(new_rel)
                    stem = path_obj.stem
                    suffix = path_obj.suffix
                    parent = str(path_obj.parent)
                    if parent == ".":
                        parent = ""
                    
                    # Optimization: Use cached counter if available
                    # We key by the original target path (new_rel)
                    counter = next_counters.get(new_rel, 1)
                    
                    collision_resolved = False
                    while True:
                        if counter > 100000: # Increased limit since it's fast now
                            # Safety break to prevent infinite loops
                            print(f"[WARNING] Collision limit reached for {new_rel}. Skipping move.")
                            break
                            
                        if parent:
                            candidate = f"{parent}/{stem}_{counter}{suffix}"
                        else:
                            candidate = f"{stem}_{counter}{suffix}"
                        # Normalize slashes
                        candidate = candidate.replace("\\", "/")
                        
                        if candidate not in seen_destinations:
                            # Found a slot!
                            # Update next_counters for this base path so next time we start here
                            next_counters[new_rel] = counter + 1
                            
                            new_rel = candidate
                            collision_resolved = True
                            break
                        counter += 1
                    
                    if not collision_resolved:
                        break # Skip this move
                
                seen_destinations.add(new_rel)
                yield {
                    "old_rel": old_rel,
                    "new_rel": new_rel,
                    "reason": rule.name
                }
                break  # First matching rule wins


def validate_rule_coverage(
    files: Iterable[dict],
    rules: list[OrganizationRule]
) -> dict:
    """
    Validate that all files are matched by at least one rule.
    
    Args:
        files: Iterable of file metadata dicts.
        rules: List of organization rules.
        
    Returns:
        Dict with:
        - "matched": set of rel_paths that matched at least one rule
        - "unmatched": list of file_info dicts that didn't match any rule
        - "coverage_pct": float percentage of files matched (0-100)
        - "total_files": int total number of files checked
    """
    matched_paths = set()
    unmatched_files = []
    total_count = 0
    
    # Sort rules by priority (highest first)
    sorted_rules = sorted(rules, key=lambda r: -r.priority)
    
    for file_info in files:
        total_count += 1
        rel_path = file_info.get("rel_path", "")
        if not rel_path:
            continue
            
        # Normalize path
        rel_path = rel_path.replace("\\", "/")
        
        # Check if any rule matches
        matched = False
        for rule in sorted_rules:
            if rule.match.matches(file_info):
                matched = True
                matched_paths.add(rel_path)
                break
        
        if not matched:
            unmatched_files.append(file_info)
    
    coverage_pct = (len(matched_paths) / total_count * 100) if total_count > 0 else 0.0
    
    return {
        "matched": matched_paths,
        "unmatched": unmatched_files,
        "coverage_pct": coverage_pct,
        "total_files": total_count
    }


def generate_catch_all_rules(unmatched_files: list[dict]) -> list[OrganizationRule]:
    """
    Generate catch-all rules for unmatched files.
    
    Analyzes unmatched files and creates rules to cover them by:
    1. Grouping by extension
    2. Creating rules for each extension group
    3. Adding a final catch-all rule for any remaining files
    
    Args:
        unmatched_files: List of file_info dicts that didn't match any rule.
        
    Returns:
        List of OrganizationRule objects with priority 0 (lowest).
    """
    if not unmatched_files:
        return []
    
    # Group unmatched files by extension
    ext_groups: dict[str, list[dict]] = defaultdict(list)
    no_ext_files = []
    
    for file_info in unmatched_files:
        ext = file_info.get("ext", "").lower()
        if not ext or ext == "/":
            no_ext_files.append(file_info)
        else:
            # Normalize extension (ensure it starts with .)
            if not ext.startswith("."):
                ext = "." + ext
            ext_groups[ext].append(file_info)
    
    catch_all_rules = []
    
    # Create rules for each extension group
    for ext, files in ext_groups.items():
        rule_name = f"Auto-Generated: {ext[1:].upper()} Files"
        catch_all_rules.append(OrganizationRule(
            name=rule_name,
            match=MatchCriteria(ext_in=[ext]),
            target_template="{year} - Misc/{type}/{original_name}",
            priority=0,
            event_name="Misc"
        ))
    
    # Create rule for files with no extension or folder markers
    # Match files where ext is empty, "/", or "(no extension)"
    if no_ext_files:
        # Match files with empty extension or "/" (folder markers)
        # We use ext_not_in with a list of common extensions to match files without extensions
        # But since we can't list all extensions, we'll use a different approach:
        # Match files where ext is empty or "/"
        # Actually, empty MatchCriteria matches everything, so we need to be more specific
        # For now, we'll let the final catch-all handle these, but create a specific rule
        # that matches files with empty or "/" extension by using a custom check
        # Since MatchCriteria doesn't support "ext is empty", we'll create a rule that
        # matches everything and let priority handle it, OR we match by excluding common extensions
        # Actually, the simplest is to match everything and let the final catch-all handle it
        # But we want to be explicit, so let's create a rule that will match these
        # We'll use the fact that empty MatchCriteria matches everything, and this rule
        # will catch files that don't match extension-based rules above
        # Since this is for no-ext files specifically, we can't easily match them with MatchCriteria
        # So we'll just ensure the final catch-all covers them
        pass  # Files without extensions will be caught by final catch-all rule
    
    # Final catch-all rule that matches absolutely everything (empty match criteria)
    # This should match any file that somehow still doesn't match above rules
    catch_all_rules.append(OrganizationRule(
        name="Auto-Generated: Catch-All (Everything Else)",
        match=MatchCriteria(),  # Empty criteria matches everything
        target_template="{year} - Misc/Misc/{original_name}",
        priority=-1,  # Even lower than 0 to ensure it's checked last
        event_name="Misc"
    ))
    
    return catch_all_rules


def parse_rules_from_llm(response_text: str) -> list[OrganizationRule]:
    """
    Parse organization rules from LLM response.
    
    Args:
        response_text: Raw response text from LLM.
        
    Returns:
        List of OrganizationRule objects.
    """
    data = parse_llm_json(response_text)
    rules_data = data.get("rules", [])
    
    return [OrganizationRule.from_dict(r) for r in rules_data]


def call_llm_for_rules(summary: dict, model_name: str = DEFAULT_MODEL) -> list[OrganizationRule]:
    """
    Call the LLM to generate organization rules based on a metadata summary.
    
    Args:
        summary: Metadata summary from build_metadata_summary().
        model_name: Short model name.
        
    Returns:
        List of OrganizationRule objects.
    """
    prompt = build_rules_prompt(summary)
    
    try:
        response_text = call_llm(prompt, model_name)
        return parse_rules_from_llm(response_text)
    except Exception as e:
        raise RuntimeError(f"LLM call failed: {e}")

