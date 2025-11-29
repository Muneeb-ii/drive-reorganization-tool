"""
Plan execution for the HDD Folder Restructure Tool.

Applies validated plans to the filesystem.
"""

import os
import shutil
from datetime import datetime
from pathlib import Path


def apply_plan(
    root: Path, 
    plan: dict, 
    dry_run: bool = True,
    allow_cross_device: bool = False
) -> dict:
    """
    Apply (or simulate) the restructuring plan.
    
    Args:
        root: The root directory path.
        plan: The validated restructuring plan.
        dry_run: If True, simulate only (no filesystem changes).
        allow_cross_device: If True, allow moves across different devices.
        
    Returns:
        A report dict with details of what was done (or would be done).
    """
    root = root.resolve()
    if not root.exists():
        raise RuntimeError(f"Root directory not found: {root}\nIs the drive connected?")
        
    root_device = os.stat(root).st_dev
    created_folders: list[str] = []
    executed_moves: list[dict] = []
    
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"\n[{mode}] Starting plan execution...")
    
    # Step 1: Create folders from folders_to_create
    for folder_rel in plan.get("folders_to_create", []):
        folder_rel = folder_rel.replace("\\", "/").strip("/")
        folder_path = root / folder_rel
        
        if not folder_path.exists():
            if dry_run:
                print(f"  [WOULD CREATE] {folder_rel}/")
            else:
                folder_path.mkdir(parents=True, exist_ok=True)
                print(f"  [CREATED] {folder_rel}/")
            created_folders.append(folder_rel)
    
    # Step 2: Process moves
    for move in plan.get("moves", []):
        old_rel = move["old_rel"]
        new_rel = move["new_rel"]
        reason = move.get("reason", "")
        
        src_path = root / old_rel
        dst_path = root / new_rel
        
        # Ensure destination parent exists
        dst_parent = dst_path.parent
        if not dst_parent.exists():
            dst_parent_rel = str(dst_parent.relative_to(root)).replace(os.sep, "/")
            if dry_run:
                print(f"  [WOULD CREATE] {dst_parent_rel}/")
            else:
                dst_parent.mkdir(parents=True, exist_ok=True)
                print(f"  [CREATED] {dst_parent_rel}/")
            if dst_parent_rel not in created_folders:
                created_folders.append(dst_parent_rel)
        
        # Perform the move
        if dry_run:
            print(f"  [WOULD MOVE] {old_rel} -> {new_rel}")
        else:
            # Check for existing file at destination
            if dst_path.exists():
                print(f"  [WARN] Destination exists, skipping: {new_rel}")
                continue
            
            # Check if source still exists
            if not src_path.exists():
                print(f"  [WARN] Source no longer exists, skipping: {old_rel}")
                continue

            # Guard against cross-device moves (would become copy+delete)
            if not allow_cross_device:
                src_device = os.stat(src_path).st_dev
                dst_device = os.stat(dst_parent).st_dev
                if src_device != root_device or dst_device != root_device:
                    print(f"  [ERROR] Cross-device move blocked: {old_rel}")
                    print("          Use --allow-cross-device to permit this")
                    continue
            
            try:
                shutil.move(str(src_path), str(dst_path))
                print(f"  [MOVED] {old_rel} -> {new_rel}")
            except Exception as e:
                print(f"  [ERROR] Failed to move {old_rel}: {e}")
                continue
        
        executed_moves.append({
            "old_rel": old_rel,
            "new_rel": new_rel,
            "reason": reason
        })
    
    # Step 3: Cleanup empty directories
    cleaned_folders = []
    if not dry_run:
        print("\n[APPLY] Cleaning up empty directories...")
        cleaned_folders = cleanup_empty_dirs(root)
        print(f"  [CLEANUP] Removed {len(cleaned_folders)} empty folders")
    
    # Build report
    report = {
        "root": str(root),
        "dry_run": dry_run,
        "executed_at": datetime.now().isoformat(timespec='seconds'),
        "created_folders": created_folders,
        "moves": executed_moves,
        "cleaned_folders": cleaned_folders,
        "summary": {
            "total_folders_created": len(created_folders),
            "total_moves": len(executed_moves),
            "total_folders_removed": len(cleaned_folders)
        }
    }
    
    print(f"\n[{mode}] Complete: {len(created_folders)} folders created, {len(executed_moves)} moves, {len(cleaned_folders)} folders removed")
    
    return report


from .utils import is_known_bundle_folder, is_macos_bundle

def cleanup_empty_dirs(root: Path) -> list[str]:
    """
    Recursively remove empty directories, starting from the bottom up.
    Skips directories that are inside known bundles (e.g. .dspproj, VIDEO_TS).
    
    Args:
        root: The root directory to clean.
        
    Returns:
        List of removed folder paths (relative to root).
    """
    removed = []
    
    # Walk bottom-up
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        # Skip the root itself
        if os.path.samefile(dirpath, root):
            continue
            
        # Check if we are inside a bundle
        # We check relative path segments
        try:
            rel_path = Path(dirpath).relative_to(root)
            parts = rel_path.parts
            
            # If any part of the path is a bundle, protect it and its children
            # Note: We iterate through all parts. If 'MyBundle.dspproj' is in the path,
            # then 'MyBundle.dspproj/Contents' is inside it.
            is_protected = False
            for part in parts:
                if is_known_bundle_folder(part) or is_macos_bundle(part):
                    is_protected = True
                    break
            
            if is_protected:
                continue
                
        except ValueError:
            # Should not happen if walking from root
            continue
            
        try:
            # Try to remove the directory
            # os.rmdir only works if the directory is empty
            os.rmdir(dirpath)
            
            # If successful, record it
            rel_path_str = str(rel_path)
            removed.append(rel_path_str)
            
        except OSError:
            # Directory not empty or other error, skip
            pass
            
    return removed

