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
            # Strict check: Both src and dst (parent) must be on root_device
            src_dev = os.stat(src).st_dev
            
            # For dst, check parent if it exists, otherwise assume it will be created on root_device
            # (since we are creating it under root)
            dst_parent = dst.parent
            if dst_parent.exists():
                dst_dev = os.stat(dst_parent).st_dev
                if dst_dev != root_device:
                    res["error"] = f"Destination parent on different device ({dst_dev} != {root_device})"
                    return res
            
            if src_dev != root_device:
                 res["error"] = f"Source on different device ({src_dev} != {root_device})"
                 return res

        # Defensive: Ensure parent exists
        if not dst.parent.exists():
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                res["error"] = f"Failed to create parent dir: {e}"
                return res
        
        try:
            shutil.move(str(src), str(dst))
        except FileExistsError:
            res["error"] = "Destination exists (race condition)"
            return res
            
        res["status"] = "moved"
        return res
        
    except Exception as e:
        res["error"] = str(e)
        return res


def apply_plan(
    root: Path, 
    plan: dict | Path, 
    dry_run: bool = True,
    allow_cross_device: bool = False
) -> dict:
    """
    Apply (or simulate) the restructuring plan.
    
    Args:
        root: Root directory.
        plan: Plan dict OR Path to plan.jsonl file.
        dry_run: If True, simulate moves.
        allow_cross_device: If True, allow moves across devices.
    """
    from .utils import load_jsonl, save_jsonl
    
    root = root.resolve()
    if not root.exists():
        raise RuntimeError(f"Root directory not found: {root}\nIs the drive connected?")
        
    root_device = os.stat(root).st_dev
    created_folders: list[str] = []
    executed_moves_count = 0
    failed_moves_count = 0
    cleaned_folders_count = 0
    
    # Load plan metadata/header
    folders_to_create = []
    moves_source = []
    
    if isinstance(plan, dict):
        folders_to_create = plan.get("folders_to_create", [])
        moves_source = plan.get("moves", [])
        total_moves = len(moves_source)
    else:
        # Streaming mode
        print(f"[INFO] Streaming plan from {plan}...")
        plan_gen = load_jsonl(plan)
        try:
            header = next(plan_gen)
            if header.get("type") in ["plan_header", "undo_header"]:
                folders_to_create = header.get("folders_to_create", [])
                moves_source = plan_gen
            else:
                plan_gen = load_jsonl(plan)
                moves_source = plan_gen
        except StopIteration:
            pass
        total_moves = None
    
    def valid_moves_filter(gen):
        for item in gen:
            if "old_rel" in item and "new_rel" in item:
                # Normalize paths immediately
                item["old_rel"] = item["old_rel"].replace("\\", "/").strip("/")
                item["new_rel"] = item["new_rel"].replace("\\", "/").strip("/")
                yield item
                
    moves_source = valid_moves_filter(moves_source)
    
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"\n[{mode}] Starting plan execution...")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    undo_filename = f"undo_plan_{timestamp}.jsonl"
    undo_file = Path(undo_filename)
    
    counter = 1
    while undo_file.exists():
        undo_file = Path(f"undo_plan_{timestamp}_{counter}.jsonl")
        counter += 1
        
    undo_file_handle = None
    
    if not dry_run:
        undo_file_handle = open(undo_file, 'w', encoding='utf-8')
        undo_header = {
            "root": str(root),
            "created_at": datetime.now().isoformat(),
            "type": "undo_header",
            "folders_to_create": []
        }
        undo_file_handle.write(json.dumps(undo_header, ensure_ascii=False) + '\n')
        print(f"[SAFETY] Undo plan streaming to '{undo_file}'")

    try:
        unique_folders = sorted(list(set(folders_to_create)))
        
        print(f"[INFO] Verifying/Creating {len(unique_folders)} folders...")
        for folder_rel in unique_folders:
            folder_rel = folder_rel.replace("\\", "/").strip("/")
            if not folder_rel: continue
            
            folder_path = root / folder_rel
            
            if not folder_path.exists():
                if dry_run:
                    pass
                else:
                    folder_path.mkdir(parents=True, exist_ok=True)
                created_folders.append(folder_rel)
                
        print(f"[INFO] Processing moves...")
        
        if dry_run:
            count = 0
            for move in moves_source:
                count += 1
                if count <= 10:
                    print(f"  [WOULD MOVE] {move['old_rel']} -> {move['new_rel']}")
            if count > 10:
                print(f"  ... and {count-10} more")
            executed_moves_count = count
        else:
            BATCH_SIZE = 1000
            batch = []
            
            with ThreadPoolExecutor(max_workers=8) as executor:
                with tqdm(total=total_moves, unit="file") as pbar:
                    def process_batch(current_batch):
                        nonlocal executed_moves_count, failed_moves_count
                        
                        # Ensure parent directories exist for this batch
                        # We do this sequentially before submitting threads to avoid race conditions 
                        # (though mkdir exist_ok=True is usually safe, this is cleaner)
                        for m in current_batch:
                            # Normalize path separators
                            new_rel_norm = m["new_rel"].replace("\\", "/")
                            dst_path = root / new_rel_norm
                            
                            if not dry_run:
                                try:
                                    dst_path.parent.mkdir(parents=True, exist_ok=True)
                                except OSError:
                                    pass

                        futures = {
                            executor.submit(
                                _move_file, 
                                root / m["old_rel"], 
                                root / m["new_rel"], 
                                m["old_rel"], 
                                m["new_rel"], 
                                root_device, 
                                allow_cross_device
                            ): m for m in current_batch
                        }
                        
                        for future in as_completed(futures):
                            res = future.result()
                            if res["status"] == "moved":
                                executed_moves_count += 1
                                # Write to undo stream
                                if undo_file_handle:
                                    undo_move = {
                                        "old_rel": res["new_rel"],
                                        "new_rel": res["old_rel"],
                                        "reason": "Undo move"
                                    }
                                    undo_file_handle.write(json.dumps(undo_move, ensure_ascii=False) + '\n')
                            else:
                                failed_moves_count += 1
                                tqdm.write(f"[ERROR] {res['error']}: {res['old_rel']}")
                            pbar.update(1)
                    
                    for move in moves_source:
                        batch.append(move)
                        if len(batch) >= BATCH_SIZE:
                            process_batch(batch)
                            batch = []
                    
                    if batch:
                        process_batch(batch)
        
        # --- Step 3: Cleanup ---
        if not dry_run:
            print("\n[APPLY] Cleaning up empty directories...")
            # Pass created_folders to protect them from cleanup
            # We convert to set for faster lookup
            keep_set = set(created_folders)
            cleaned_folders = cleanup_empty_dirs(root, keep_folders=keep_set)
            cleaned_folders_count = len(cleaned_folders)
            print(f"  [CLEANUP] Removed {cleaned_folders_count} empty folders")
        
        # Build report
        report = {
            "root": str(root),
            "dry_run": dry_run,
            "executed_at": datetime.now().isoformat(timespec='seconds'),
            "created_folders_count": len(created_folders),
            "executed_moves_count": executed_moves_count,
            "failed_moves_count": failed_moves_count,
            "cleaned_folders_count": cleaned_folders_count
        }
        
        print(f"\n[{mode}] Complete: {executed_moves_count} moved, {failed_moves_count} failed, {cleaned_folders_count} cleaned")
        
        return report

    finally:
        if undo_file_handle:
            undo_file_handle.close()


from .utils import is_known_bundle_folder, is_macos_bundle

def cleanup_empty_dirs(root: Path, keep_folders: set[str] = None) -> list[str]:
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
            
        # Check if this folder should be kept (e.g. newly created)
        try:
            rel_path = Path(dirpath).relative_to(root)
            rel_path_str = str(rel_path).replace("\\", "/")
            if keep_folders and rel_path_str in keep_folders:
                continue
        except ValueError:
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

