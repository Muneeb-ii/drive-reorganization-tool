"""
Plan execution for the HDD Folder Restructure Tool.

Applies validated plans to the filesystem.
"""

import os
import shutil
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from tqdm import tqdm
from .utils import save_json


def _move_file(src: Path, dst: Path, old_rel: str, new_rel: str, root_device: int, allow_cross_device: bool) -> dict:
    """Helper to move a single file, safe for threads."""
    res = {"old_rel": old_rel, "new_rel": new_rel, "status": "skipped", "error": None}
    
    try:
        if dst.exists():
            res["error"] = "Destination exists"
            return res
        
        if not src.exists():
            res["error"] = "Source not found"
            return res

        # Cross-device check
        if not allow_cross_device:
            # os.stat can be slow, but necessary for safety
            # Optimization: pass root_device and only check if we suspect a mount point?
            # For now, stick to safety.
            src_dev = os.stat(src).st_dev
            dst_dev = os.stat(dst.parent).st_dev
            if src_dev != root_device or dst_dev != root_device:
                res["error"] = "Cross-device move blocked"
                return res
        
        shutil.move(str(src), str(dst))
        res["status"] = "moved"
        return res
        
    except Exception as e:
        res["error"] = str(e)
        return res


def apply_plan(
    root: Path, 
    plan: dict, 
    dry_run: bool = True,
    allow_cross_device: bool = False
) -> dict:
    """
    Apply (or simulate) the restructuring plan.
    """
    root = root.resolve()
    if not root.exists():
        raise RuntimeError(f"Root directory not found: {root}\nIs the drive connected?")
        
    root_device = os.stat(root).st_dev
    created_folders: list[str] = []
    executed_moves: list[dict] = []
    failed_moves: list[dict] = []
    
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"\n[{mode}] Starting plan execution...")
    
    # --- Step 0: Generate Undo Plan (if not dry run) ---
    if not dry_run:
        undo_moves = []
        for move in plan.get("moves", []):
            undo_moves.append({
                "old_rel": move["new_rel"],
                "new_rel": move["old_rel"],
                "reason": "Undo: " + move.get("reason", "")
            })
        undo_plan = {
            "root": str(root),
            "created_at": datetime.now().isoformat(),
            "type": "undo",
            "moves": undo_moves
        }
        save_json(undo_plan, Path("undo_plan.json"))
        print(f"[SAFETY] Undo plan saved to 'undo_plan.json'")

    # --- Step 1: Create folders ---
    folders_to_create = plan.get("folders_to_create", [])
    # Also add parents of all destinations to be safe
    for move in plan.get("moves", []):
        dst_parent = Path(move["new_rel"]).parent
        if str(dst_parent) != ".":
            folders_to_create.append(str(dst_parent))
            
    folders_to_create = sorted(list(set(folders_to_create)))
    
    print(f"[INFO] Verifying/Creating {len(folders_to_create)} folders...")
    for folder_rel in folders_to_create:
        folder_rel = folder_rel.replace("\\", "/").strip("/")
        if not folder_rel: continue
        
        folder_path = root / folder_rel
        
        if not folder_path.exists():
            if dry_run:
                # print(f"  [WOULD CREATE] {folder_rel}/")
                pass
            else:
                folder_path.mkdir(parents=True, exist_ok=True)
            created_folders.append(folder_rel)
            
    # --- Step 2: Process moves (Parallel) ---
    moves = plan.get("moves", [])
    print(f"[INFO] Processing {len(moves)} moves...")
    
    if dry_run:
        # Sequential print for dry run
        for move in moves[:10]:
            print(f"  [WOULD MOVE] {move['old_rel']} -> {move['new_rel']}")
        if len(moves) > 10:
            print(f"  ... and {len(moves)-10} more")
        executed_moves = moves # Assume all succeed in dry run
    else:
        # Parallel Execution
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {}
            for move in moves:
                src = root / move["old_rel"]
                dst = root / move["new_rel"]
                f = executor.submit(
                    _move_file, 
                    src, dst, 
                    move["old_rel"], move["new_rel"], 
                    root_device, allow_cross_device
                )
                futures[f] = move
            
            # Progress bar
            with tqdm(total=len(moves), unit="file") as pbar:
                for future in as_completed(futures):
                    res = future.result()
                    if res["status"] == "moved":
                        executed_moves.append({
                            "old_rel": res["old_rel"],
                            "new_rel": res["new_rel"]
                        })
                    else:
                        failed_moves.append(res)
                        tqdm.write(f"[ERROR] {res['error']}: {res['old_rel']}")
                    pbar.update(1)
    
    # --- Step 3: Cleanup ---
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
        "failed_moves": failed_moves,
        "cleaned_folders": cleaned_folders,
        "summary": {
            "total_folders_created": len(created_folders),
            "total_moves": len(executed_moves),
            "failed_moves": len(failed_moves),
            "total_folders_removed": len(cleaned_folders)
        }
    }
    
    print(f"\n[{mode}] Complete: {len(executed_moves)} moved, {len(failed_moves)} failed, {len(cleaned_folders)} cleaned")
    
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

