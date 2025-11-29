#!/usr/bin/env python3
"""
HDD Folder Restructure Tool - CLI Entry Point
==============================================

Usage:
    python -m reorganize_hdd run /path/to/hdd --auto --delay 4
    python -m reorganize_hdd scan /path/to/hdd -o metadata.json
    python -m reorganize_hdd plan metadata.json --mode rules -o plan.json
    python -m reorganize_hdd apply plan.json --dry-run
"""

import argparse
import sys
import time
from pathlib import Path

from .scanner import build_metadata, build_metadata_summary, scan_and_summarize
from .executor import apply_plan
from .planning import validate_plan, call_llm_for_plan, call_llm_for_folder
from .planning.rules import generate_moves_from_rules, call_llm_for_rules
from .utils import save_json, load_json, is_macos_bundle, load_metadata_files_stream
from .llm import GEMINI_MODELS, DEFAULT_MODEL


def get_top_level_folders(metadata: dict) -> dict[str, list[dict]]:
    """
    Group files by their top-level folder.
    
    Args:
        metadata: Full metadata dict.
        
    Returns:
        Dict mapping folder names to lists of file dicts.
    """
    folders: dict[str, list[dict]] = {}
    
    for f in metadata.get("files", []):
        rel_path = f["rel_path"]
        parts = rel_path.split("/")
        
        if len(parts) > 1:
            top_folder = parts[0]
        else:
            top_folder = "(root files)"
        
        if top_folder not in folders:
            folders[top_folder] = []
        folders[top_folder].append(f)
    
    return folders


def build_folder_metadata(root: str, folder_name: str, files: list[dict]) -> dict:
    """Build a metadata dict for a single folder."""
    return {
        "root": root,
        "folder": folder_name,
        "files": files
    }


def run_automatic_mode(
    root: Path, 
    metadata: dict, 
    model_name: str, 
    dry_run: bool,
    delay: float = 0,
    mode: str = "direct"
) -> dict:
    """
    Run automatic mode - process all folders without prompts.
    
    Args:
        mode: "direct" for explicit moves, "rules" for rule-based.
    """
    if mode == "rules":
        return run_rules_mode(root, metadata, model_name, dry_run, delay)
    
    folders = get_top_level_folders(metadata)
    all_folder_names = sorted(folders.keys())
    
    print(f"\n{'='*60}")
    print("AUTOMATIC MODE - Processing All Folders")
    print(f"{'='*60}")
    print(f"Found {len(folders)} top-level folders")
    print(f"{'='*60}")
    
    combined_plan = {
        "folders_to_create": [],
        "moves": []
    }
    
    processed = 0
    skipped = 0
    errors = []
    
    for i, folder_name in enumerate(sorted(folders.keys()), 1):
        files = folders[folder_name]
        
        print(f"\n[{i}/{len(folders)}] {folder_name} ({len(files)} files)...", end=" ", flush=True)
        
        if is_macos_bundle(folder_name):
            print("SKIP (bundle)")
            skipped += 1
            continue
        
        try:
            folder_metadata = build_folder_metadata(str(root), folder_name, files)
            folder_plan = call_llm_for_folder(folder_metadata, all_folder_names, model_name)
            
            if delay > 0:
                time.sleep(delay)
            
            # Filter no-op moves
            folder_plan['moves'] = [
                m for m in folder_plan.get('moves', [])
                if m.get('old_rel', '').strip() != m.get('new_rel', '').strip()
            ]
            
            move_count = len(folder_plan.get('moves', []))
            if move_count > 0:
                print(f"OK ({move_count} moves)")
                combined_plan["folders_to_create"].extend(folder_plan.get("folders_to_create", []))
                combined_plan["moves"].extend(folder_plan.get("moves", []))
            else:
                print("OK (no changes needed)")
            
            processed += 1
            
        except Exception as e:
            error_msg = str(e)[:50]
            print(f"ERROR ({error_msg})")
            errors.append(f"{folder_name}: {error_msg}")
            skipped += 1
            continue
    
    # Deduplicate
    combined_plan["folders_to_create"] = list(set(combined_plan["folders_to_create"]))
    
    # Show summary
    print(f"\n{'='*60}")
    print("AUTOMATIC MODE COMPLETE - SUMMARY")
    print(f"{'='*60}")
    print(f"Processed:     {processed} folders")
    print(f"Skipped:       {skipped} folders")
    print(f"Errors:        {len(errors)}")
    print(f"New folders:   {len(combined_plan['folders_to_create'])}")
    print(f"Total moves:   {len(combined_plan['moves'])}")
    print(f"{'='*60}")
    
    if errors:
        print("\nErrors encountered:")
        for err in errors[:5]:
            print(f"  - {err}")
        if len(errors) > 5:
            print(f"  ... and {len(errors) - 5} more")
    
    if combined_plan['moves']:
        print("\nSample moves (first 10):")
        for move in combined_plan['moves'][:10]:
            print(f"  • {move['old_rel'][:50]}")
            print(f"    → {move['new_rel'][:50]}")
    
    # Final confirmation
    if combined_plan['moves']:
        print(f"\n{'='*60}")
        print("Proceed with this plan? [y]es / [n]o / [s]ave plan only")
        
        if not sys.stdin.isatty():
            print("[WARN] Non-interactive mode detected. Auto-approving plan.")
            return combined_plan
            
        while True:
            choice = input("Choice: ").strip().lower()
            if choice in ['y', 'yes', '']:
                return combined_plan
            elif choice in ['n', 'no']:
                print("[ABORT] Plan cancelled")
                return {"folders_to_create": [], "moves": []}
            elif choice in ['s', 'save']:
                print("[INFO] Plan will be saved but not applied")
                return combined_plan
            else:
                print("Invalid choice. Enter y, n, or s")
    else:
        print("\n[INFO] No moves generated - all folders are well-organized!")
        return combined_plan


def run_rules_mode(
    root: Path, 
    metadata: dict, 
    model_name: str, 
    dry_run: bool,
    delay: float = 0,
    metadata_path: Path | None = None,
    precomputed_summary: dict | None = None
) -> dict:
    """
    Run rule-based mode - LLM designs rules, Python applies them.
    """
    print(f"\n{'='*60}")
    print("RULES MODE - LLM Designs Organization Rules")
    print(f"{'='*60}")
    
    # Build summary
    if precomputed_summary:
        print("[STEP 1] Using precomputed metadata summary...")
        summary = precomputed_summary
    else:
        print("[STEP 1] Building metadata summary...")
        summary = build_metadata_summary(metadata)
        
    print(f"[INFO] Summary: {summary['total_files']} files, {len(summary['folders'])} folders")
    
    # Get rules from LLM
    print("\n[STEP 2] Requesting organization rules from LLM...")
    try:
        rules = call_llm_for_rules(summary, model_name)
        print(f"[INFO] Received {len(rules)} rules")
        
        if rules:
            print("\nProposed rules:")
            for r in rules:
                print(f"  • {r.name}")
                print(f"    Match: {r.match.ext_in or 'any'}")
                print(f"    Target: {r.target_template}")
    except Exception as e:
        print(f"[ERROR] Failed to get rules: {e}")
        return {"folders_to_create": [], "moves": []}
    
    if delay > 0:
        time.sleep(delay)
    
    if not rules:
        print("\n[INFO] No rules proposed - directory already well-organized!")
        return {"folders_to_create": [], "moves": []}
    
    # Apply rules locally
    print("\n[STEP 3] Applying rules to generate moves...")
    
    # Determine source of files (memory or stream)
    files_source = metadata.get("files", [])
    if not files_source and metadata_path and metadata_path.exists():
        print(f"[INFO] Streaming files from {metadata_path}...")
        files_source = load_metadata_files_stream(metadata_path)
    elif not files_source:
        print("[WARN] No files found in metadata to apply rules to.")
        
    moves = generate_moves_from_rules(files_source, rules)
    print(f"[INFO] Generated {len(moves)} moves from rules")
    
    plan = {
        "folders_to_create": [],
        "moves": moves,
        "rules": [{"name": r.name, "template": r.target_template} for r in rules]
    }
    
    if moves:
        print("\nSample moves (first 10):")
        for move in moves[:10]:
            print(f"  • {move['old_rel'][:50]}")
            print(f"    → {move['new_rel'][:50]}")
        
        print(f"\n{'='*60}")
        print("Proceed with this plan? [y]es / [n]o / [s]ave plan only")
        
        if not sys.stdin.isatty():
            print("[WARN] Non-interactive mode detected. Auto-approving plan.")
            return plan
            
        while True:
            choice = input("Choice: ").strip().lower()
            if choice in ['y', 'yes', '']:
                return plan
            elif choice in ['n', 'no']:
                print("[ABORT] Plan cancelled")
                return {"folders_to_create": [], "moves": []}
            elif choice in ['s', 'save']:
                return plan
            else:
                print("Invalid choice. Enter y, n, or s")
    
    return plan


# =============================================================================
# Subcommands
# =============================================================================

def cmd_scan(args) -> int:
    """Scan command - build metadata from directory."""
    root = args.root.resolve()
    
    if not root.exists() or not root.is_dir():
        print(f"[ERROR] Invalid directory: {root}")
        return 1
    
    # Parse filters
    ext_include = None
    ext_exclude = None
    if args.ext_include:
        ext_include = {e.strip().lower() if e.strip().startswith('.') else f'.{e.strip().lower()}' 
                       for e in args.ext_include.split(',')}
    if args.ext_exclude:
        ext_exclude = {e.strip().lower() if e.strip().startswith('.') else f'.{e.strip().lower()}' 
                       for e in args.ext_exclude.split(',')}
    
    print(f"[SCAN] Scanning {root}...")
    # Use streaming scan
    summary = scan_and_summarize(root, args.output, args.min_size, ext_include, ext_exclude)
    print(f"[INFO] Found {summary['total_files']} files")
    
    # Note: scan_and_summarize already saved the file to args.output
    return 0


def cmd_plan(args) -> int:
    """Plan command - generate plan from metadata."""
    metadata_path = Path(args.metadata)
    
    if not metadata_path.exists():
        print(f"[ERROR] Metadata file not found: {metadata_path}")
        return 1
    
    print(f"[PLAN] Loading metadata from {metadata_path}...")
    # For planning, we might need full metadata depending on mode
    # If rules mode, we can stream. If direct mode, we likely need full load (or refactor direct mode too)
    # Direct mode is not optimized for huge drives anyway, so full load is acceptable there.
    
    if args.mode == "rules":
        print("[PLAN] Using rule-based mode...")
        # We need summary first. If metadata.json is huge, building summary from it takes time.
        # Ideally scan command should have saved summary too, but it didn't.
        # We'll load full metadata for now as legacy behavior, or we could implement stream summarization here too.
        # For simplicity, let's load full metadata here, assuming 'plan' command is run on machines with RAM
        # or that users running 'run' command get the optimization.
        metadata = load_json(metadata_path)
        summary = build_metadata_summary(metadata)
        rules = call_llm_for_rules(summary, args.model)
        
        if not rules:
            print("[INFO] No rules proposed")
            plan = {"folders_to_create": [], "moves": [], "rules": []}
        else:
            files = metadata.get("files", [])
            moves = generate_moves_from_rules(files, rules)
            plan = {
                "folders_to_create": [],
                "moves": moves,
                "rules": [{"name": r.name, "template": r.target_template} for r in rules]
            }
    else:
        print("[PLAN] Using direct mode...")
        metadata = load_json(metadata_path)
        plan = call_llm_for_plan(metadata, args.model)
    
    save_json(plan, args.output)
    print(f"[INFO] Plan has {len(plan.get('moves', []))} moves")
    return 0


def cmd_apply(args) -> int:
    """Apply command - apply plan to filesystem."""
    plan_path = Path(args.plan)
    
    if not plan_path.exists():
        print(f"[ERROR] Plan file not found: {plan_path}")
        return 1
    
    print(f"[APPLY] Loading plan from {plan_path}...")
    plan = load_json(plan_path)
    
    # Get root from plan or argument
    if args.root:
        root = args.root.resolve()
    elif "root" in plan:
        root = Path(plan["root"])
    else:
        print("[ERROR] No root directory specified")
        return 1
    
    if not root.exists() or not root.is_dir():
        print(f"[ERROR] Invalid directory: {root}")
        return 1
    
    # Validate
    print("[APPLY] Validating plan...")
    try:
        valid_moves = validate_plan(root, plan)
        validated_plan = {
            "folders_to_create": plan.get("folders_to_create", []),
            "moves": valid_moves
        }
    except ValueError as e:
        print(f"[ERROR] Validation failed: {e}")
        return 1
    
    # Apply
    report = apply_plan(root, validated_plan, args.dry_run, args.allow_cross_device)
    
    if args.report_out:
        save_json(report, args.report_out)
    
    if args.dry_run:
        print("\n[NOTE] This was a DRY-RUN. No files were actually moved.")
    
    return 0


def cmd_run(args) -> int:
    """Run command - full pipeline (scan → plan → apply)."""
    root = args.root.resolve()
    
    if not root.exists() or not root.is_dir():
        print(f"[ERROR] Invalid directory: {root}")
        return 1
    
    # Parse filters
    ext_include = None
    ext_exclude = None
    if args.ext_include:
        ext_include = {e.strip().lower() if e.strip().startswith('.') else f'.{e.strip().lower()}' 
                       for e in args.ext_include.split(',')}
    if args.ext_exclude:
        ext_exclude = {e.strip().lower() if e.strip().startswith('.') else f'.{e.strip().lower()}' 
                       for e in args.ext_exclude.split(',')}
    
    # Header
    mode_str = f"{args.mode} mode"
    if args.auto:
        mode_str += " (automatic)"
    
    print("=" * 60)
    print("HDD Folder Restructure Tool v2")
    print("=" * 60)
    print(f"Root:     {root}")
    print(f"Dry-run:  {args.dry_run}")
    print(f"Model:    {args.model}")
    print(f"Mode:     {mode_str}")
    if args.delay > 0:
        print(f"Delay:    {args.delay}s between API calls")
    print("=" * 60)
    
    try:
        # Step 1: Scan
        print("\n[STEP 1] Scanning directory...")
        # Use streaming scan and get summary directly
        summary = scan_and_summarize(root, args.metadata_out, args.min_size, ext_include, ext_exclude)
        print(f"[INFO] Found {summary['total_files']} files")
        # Metadata is already saved to args.metadata_out
        
        # Step 2: Plan
        if args.skip_llm:
            print(f"\n[STEP 2] Loading existing plan from {args.plan_out}...")
            if not args.plan_out.exists():
                print(f"[ERROR] Plan file not found: {args.plan_out}")
                return 1
            plan = load_json(args.plan_out)
        elif args.auto:
            # Auto mode likely needs full metadata for direct planning
            # We'll load it here if needed, or refactor auto mode later.
            # For now, let's load it to be safe if user chose auto mode.
            metadata = load_json(args.metadata_out)
            plan = run_automatic_mode(root, metadata, args.model, args.dry_run, args.delay, args.mode)
            save_json(plan, args.plan_out)
            
            if not plan.get("moves"):
                print("\n[INFO] No moves in plan. Nothing to do.")
                return 0
        else:
            if args.mode == "rules":
                print("\n[STEP 2] Running rules mode...")
                # Pass summary and metadata path for streaming
                plan = run_rules_mode(
                    root, 
                    {}, # Empty metadata dict
                    args.model, 
                    args.dry_run, 
                    args.delay,
                    metadata_path=args.metadata_out,
                    precomputed_summary=summary
                )
            else:
                print("\n[STEP 2] Requesting restructuring plan from LLM...")
                # Direct mode needs full metadata
                metadata = load_json(args.metadata_out)
                plan = call_llm_for_plan(metadata, args.model)
            save_json(plan, args.plan_out)
        
        # Step 3: Validate
        print("\n[STEP 3] Validating plan...")
        valid_moves = validate_plan(root, plan)
        validated_plan = {
            "folders_to_create": plan.get("folders_to_create", []),
            "moves": valid_moves
        }
        
        # Step 4: Apply
        print("\n[STEP 4] Applying plan...")
        try:
            report = apply_plan(root, validated_plan, args.dry_run, args.allow_cross_device)
            save_json(report, args.report_out)
        except RuntimeError as e:
            print(f"\n[ERROR] {e}")
            return 1
        
        # Summary
        print("\n" + "=" * 60)
        print("COMPLETE")
        print("=" * 60)
        print(f"Metadata:  {args.metadata_out}")
        print(f"Plan:      {args.plan_out}")
        print(f"Report:    {args.report_out}")
        
        if args.dry_run:
            print("\n[NOTE] This was a DRY-RUN. No files were actually moved.")
            print("       Run without --dry-run to apply changes.")
        
        return 0
        
    except KeyboardInterrupt:
        print("\n[ABORT] Operation cancelled by user")
        return 130
    except Exception as e:
        print(f"\n[ERROR] {e}")
        return 1



# =============================================================================
# Main
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="HDD Folder Restructure Tool - Organize directories with LLM assistance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Common arguments
    model_choices = list(GEMINI_MODELS.keys())
    
    # --- SCAN command ---
    scan_parser = subparsers.add_parser("scan", help="Scan directory and generate metadata")
    scan_parser.add_argument("root", type=Path, help="Directory to scan")
    scan_parser.add_argument("-o", "--output", type=Path, default=Path("metadata.json"),
                            help="Output metadata file (default: metadata.json)")
    scan_parser.add_argument("--min-size", type=int, default=0, metavar="BYTES",
                            help="Only include files larger than N bytes")
    scan_parser.add_argument("--ext-include", type=str, metavar="EXTS",
                            help="Only include specific extensions (comma-separated)")
    scan_parser.add_argument("--ext-exclude", type=str, metavar="EXTS",
                            help="Exclude specific extensions (comma-separated)")
    scan_parser.set_defaults(func=cmd_scan)
    
    # --- PLAN command ---
    plan_parser = subparsers.add_parser("plan", help="Generate plan from metadata")
    plan_parser.add_argument("metadata", type=str, help="Metadata file to use")
    plan_parser.add_argument("-o", "--output", type=Path, default=Path("plan.json"),
                            help="Output plan file (default: plan.json)")
    plan_parser.add_argument("--mode", choices=["direct", "rules"], default="direct",
                            help="Planning mode: direct (explicit moves) or rules (rule-based)")
    plan_parser.add_argument("--model", type=str, default=DEFAULT_MODEL, choices=model_choices,
                            help=f"Gemini model to use (default: {DEFAULT_MODEL})")
    plan_parser.set_defaults(func=cmd_plan)
    
    # --- APPLY command ---
    apply_parser = subparsers.add_parser("apply", help="Apply plan to filesystem")
    apply_parser.add_argument("plan", type=str, help="Plan file to apply")
    apply_parser.add_argument("--root", type=Path, help="Root directory (overrides plan)")
    apply_parser.add_argument("--dry-run", action="store_true",
                             help="Simulate changes without modifying files")
    apply_parser.add_argument("--allow-cross-device", action="store_true",
                             help="Allow moves across different devices")
    apply_parser.add_argument("--report-out", type=Path, default=Path("report.json"),
                             help="Output report file (default: report.json)")
    apply_parser.set_defaults(func=cmd_apply)
    
    # --- RUN command (full pipeline) ---
    run_parser = subparsers.add_parser("run", help="Full pipeline: scan → plan → apply")
    run_parser.add_argument("root", type=Path, help="Root directory to reorganize")
    run_parser.add_argument("--dry-run", action="store_true",
                           help="Simulate changes without modifying files")
    run_parser.add_argument("--auto", "-y", action="store_true",
                           help="Automatic mode: process all folders, confirm once at end")
    run_parser.add_argument("--mode", choices=["direct", "rules"], default="direct",
                           help="Planning mode: direct or rules")
    run_parser.add_argument("--model", type=str, default=DEFAULT_MODEL, choices=model_choices,
                           help=f"Gemini model to use (default: {DEFAULT_MODEL})")
    run_parser.add_argument("--delay", type=float, default=0,
                           help="Delay between API calls (use 4 for free tier)")
    run_parser.add_argument("--skip-llm", action="store_true",
                           help="Skip LLM call, use existing plan file")
    run_parser.add_argument("--allow-cross-device", action="store_true",
                           help="Allow moves across different devices")
    run_parser.add_argument("--min-size", type=int, default=0, metavar="BYTES",
                           help="Only include files larger than N bytes")
    run_parser.add_argument("--ext-include", type=str, metavar="EXTS",
                           help="Only include specific extensions")
    run_parser.add_argument("--ext-exclude", type=str, metavar="EXTS",
                           help="Exclude specific extensions")
    run_parser.add_argument("--metadata-out", type=Path, default=Path("metadata.json"),
                           help="Metadata output file")
    run_parser.add_argument("--plan-out", type=Path, default=Path("plan.json"),
                           help="Plan output file")
    run_parser.add_argument("--report-out", type=Path, default=Path("report.json"),
                           help="Report output file")
    run_parser.set_defaults(func=cmd_run)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return 0
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

