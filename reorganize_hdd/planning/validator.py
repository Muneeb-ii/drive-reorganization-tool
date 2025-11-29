"""
Plan validation for the HDD Folder Restructure Tool.

Validates that proposed moves are safe and valid before execution.
"""

from pathlib import Path

from ..utils import path_contains_bundle, is_known_bundle_folder, is_macos_bundle


def validate_plan(root: Path, plan: dict) -> list[dict]:
    """
    Validate the restructuring plan before applying.
    
    Checks for:
    - No-op moves (same source and destination)
    - Duplicate moves
    - File renames (only location changes allowed)
    - Moves inside macOS bundles
    - Moves INTO macOS bundles
    - Non-existent source files
    - Destination collisions
    
    Args:
        root: The root directory path.
        plan: The restructuring plan dict.
        
    Returns:
        A filtered list of valid moves (excluding invalid entries).
        
    Raises:
        ValueError: If there are destination collisions.
    """
    root = root.resolve()
    if not root.exists():
        raise RuntimeError(f"Root directory not found: {root}\nIs the drive connected?")
        
    warnings = []
    collisions = []
    valid_moves = []
    
    # Track destinations to detect collisions
    destinations: dict[str, str] = {}  # new_rel -> old_rel
    
    # Track seen moves to deduplicate
    seen_moves: set[tuple[str, str]] = set()
    
    for move in plan.get("moves", []):
        old_rel = move.get("old_rel", "")
        new_rel = move.get("new_rel", "")
        
        # Normalize paths
        old_rel = old_rel.replace("\\", "/").strip("/")
        new_rel = new_rel.replace("\\", "/").strip("/")
        
        # Skip no-op moves
        if old_rel == new_rel:
            continue  # Silent skip for no-ops
        
        # Skip duplicate moves (same old_rel -> same new_rel)
        move_key = (old_rel, new_rel)
        if move_key in seen_moves:
            continue  # Silent skip for duplicates
        seen_moves.add(move_key)
        
        # Skip file renames (only filename changed, not location)
        old_dir = '/'.join(old_rel.split('/')[:-1])
        new_dir = '/'.join(new_rel.split('/')[:-1])
        old_name = old_rel.split('/')[-1]
        new_name = new_rel.split('/')[-1]
        if old_dir == new_dir and old_name != new_name:
            warnings.append(f"Skipping - rename not allowed: {old_rel} -> {new_name}")
            continue
        
        # Skip moves inside macOS bundles (would break project structure)
        if path_contains_bundle(old_rel):
            warnings.append(f"Skipping - source inside bundle: {old_rel}")
            continue
        
        # Skip moves INTO macOS bundles (would corrupt projects)
        if path_contains_bundle(new_rel):
            warnings.append(f"Skipping - destination inside bundle: {new_rel}")
            continue
        
        # Check source exists (warn but continue)
        src_path = root / old_rel
        if not src_path.exists():
            warnings.append(f"Skipping - file not found: {old_rel}")
            continue

        # Allow files OR bundles (directories that are atomic units)
        is_bundle_dir = src_path.is_dir() and (
            is_known_bundle_folder(src_path.name) or is_macos_bundle(src_path.name)
        )
        
        if not src_path.is_file() and not is_bundle_dir:
            warnings.append(f"Skipping - not a file: {old_rel}")
            continue
        
        # Check for destination collisions (different sources -> same dest)
        if new_rel in destinations:
            existing_source = destinations[new_rel]
            if existing_source != old_rel:  # True collision, not a duplicate
                collisions.append(
                    f"Collision: '{existing_source}' and '{old_rel}' both target '{new_rel}'"
                )
            continue  # Skip either way
        
        destinations[new_rel] = old_rel
        
        # Update move with normalized paths
        valid_moves.append({
            "old_rel": old_rel,
            "new_rel": new_rel,
            "reason": move.get("reason", "No reason provided")
        })
    
    # Show warnings (but don't fail)
    if warnings:
        bundle_warnings = [w for w in warnings if 'bundle' in w]
        other_warnings = [w for w in warnings if 'bundle' not in w]
        
        if bundle_warnings:
            print(f"[INFO] Filtered {len(bundle_warnings)} moves inside app bundles (preserving project structure)")
        if other_warnings:
            print(f"[WARN] Skipped {len(other_warnings)} invalid paths:")
            for w in other_warnings[:5]:
                print(f"       - {w}")
            if len(other_warnings) > 5:
                print(f"       ... and {len(other_warnings) - 5} more")
    
    # Collisions are hard failures
    if collisions:
        error_msg = "Plan has destination collisions:\n" + "\n".join(f"  - {c}" for c in collisions)
        raise ValueError(error_msg)
    
    original_count = len(plan.get('moves', []))
    if valid_moves:
        print(f"[INFO] Plan validated: {len(valid_moves)} valid moves (from {original_count} proposed)")
    else:
        print(f"[INFO] No valid moves remaining after filtering (all {original_count} were filtered out)")
    
    return valid_moves

