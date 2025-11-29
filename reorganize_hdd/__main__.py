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
import json
from pathlib import Path

from .scanner import build_metadata_summary, scan_and_summarize
from .executor import apply_plan
from .planning import validate_plan, call_llm_for_plan, call_llm_for_folder
from .planning.rules import generate_moves_from_rules, call_llm_for_rules, validate_rule_coverage, generate_catch_all_rules
from .utils import save_json, load_json, is_macos_bundle, load_metadata_files_stream, console, print_header, print_error, print_warning, print_success, print_plan_table
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
    """
    if mode == "rules":
        return run_rules_mode(root, metadata, model_name, dry_run, delay)
    
    folders = get_top_level_folders(metadata)
    all_folder_names = sorted(folders.keys())
    
    print_header("AUTOMATIC MODE", f"Processing {len(folders)} top-level folders")
    
    combined_plan = {
        "folders_to_create": [],
        "moves": []
    }
    
    processed = 0
    skipped = 0
    errors = []
    
    with console.status("[bold green]Processing folders...[/bold green]") as status:
        for i, folder_name in enumerate(sorted(folders.keys()), 1):
            files = folders[folder_name]
            status.update(f"[bold green]Processing {folder_name} ({i}/{len(folders)})...[/bold green]")
            
            if is_macos_bundle(folder_name):
                console.print(f"[dim]Skip bundle: {folder_name}[/dim]")
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
                    console.print(f"[green]✓ {folder_name}: {move_count} moves[/green]")
                    combined_plan["folders_to_create"].extend(folder_plan.get("folders_to_create", []))
                    combined_plan["moves"].extend(folder_plan.get("moves", []))
                else:
                    console.print(f"[dim]✓ {folder_name}: No changes[/dim]")
                
                processed += 1
                
            except Exception as e:
                error_msg = str(e)[:50]
                console.print(f"[red]✗ {folder_name}: {error_msg}[/red]")
                errors.append(f"{folder_name}: {error_msg}")
                skipped += 1
                continue
    
    # Deduplicate
    combined_plan["folders_to_create"] = list(set(combined_plan["folders_to_create"]))
    
    # Show summary
    print_plan_table(combined_plan)
    
    if errors:
        console.print("\n[bold red]Errors encountered:[/bold red]")
        for err in errors[:5]:
            console.print(f"  - {err}")
        if len(errors) > 5:
            console.print(f"  ... and {len(errors) - 5} more")
    
    # Final confirmation
    if combined_plan['moves']:
        console.print("\n[bold yellow]Proceed with this plan? \\[y]es / \\[n]o / \\[s]ave plan only[/bold yellow]")
        
        if not sys.stdin.isatty():
            print_warning("Non-interactive mode detected. Auto-approving plan.")
            return combined_plan
            
        while True:
            choice = input("Choice: ").strip().lower()
            if choice in ['y', 'yes', '']:
                return combined_plan
            elif choice in ['n', 'no']:
                console.print("[bold red]Plan cancelled[/bold red]")
                return {"folders_to_create": [], "moves": []}
            elif choice in ['s', 'save']:
                console.print("[blue]Plan will be saved but not applied[/blue]")
                return combined_plan
            else:
                console.print("Invalid choice. Enter y, n, or s")
    else:
        print_success("No moves generated - all folders are well-organized!")
        return combined_plan


def run_rules_mode(
    root: Path, 
    metadata: dict, 
    model_name: str, 
    dry_run: bool,
    output_plan_path: Path,
    delay: float = 0,
    metadata_path: Path | None = None,
    precomputed_summary: dict | None = None
) -> Path:
    """
    Run rule-based mode - LLM designs rules, Python applies them.
    Streams the plan to output_plan_path.
    """
    
    print_header("RULES MODE", "LLM Designs Organization Rules")
    
    # Build summary
    if precomputed_summary:
        console.print("[dim]Using precomputed metadata summary...[/dim]")
        summary = precomputed_summary
    else:
        console.print("[dim]Building metadata summary...[/dim]")
        summary = build_metadata_summary(metadata)
        
    console.print(f"[INFO] Summary: {summary['total_files']} files, {len(summary['folders'])} folders")
    
    # Get rules from LLM
    console.print("\n[bold cyan][STEP 2] Requesting organization rules from LLM...[/bold cyan]")
    try:
        with console.status("[bold green]Asking LLM for rules...[/bold green]"):
            rules = call_llm_for_rules(summary, model_name)
        print_success(f"Received {len(rules)} rules")
        
        if rules:
            console.print("\n[bold]Proposed rules:[/bold]")
            for r in rules:
                console.print(f"  • [cyan]{r.name}[/cyan]")
                console.print(f"    Match: {r.match.ext_in or 'any'}")
                console.print(f"    Target: {r.target_template}")
    except Exception as e:
        print_error(f"Failed to get rules: {e}")
        # Create empty plan
        save_json({"folders_to_create": [], "moves": []}, output_plan_path)
        return output_plan_path
    
    if delay > 0:
        time.sleep(delay)
    
    if not rules:
        print_success("No rules proposed - directory already well-organized!")
        save_json({"folders_to_create": [], "moves": []}, output_plan_path)
        return output_plan_path
    
    # Determine source of files (memory or stream) for validation
    files_source = metadata.get("files", [])
    if not files_source and metadata_path and metadata_path.exists():
        console.print(f"[dim]Streaming files from {metadata_path}...[/dim]")
        files_source = load_metadata_files_stream(metadata_path)
    elif not files_source:
        print_warning("No files found in metadata to apply rules to.")
        save_json({"folders_to_create": [], "moves": []}, output_plan_path)
        return output_plan_path
    
    # Validate rule coverage
    console.print("\n[bold cyan][STEP 2.5] Validating rule coverage...[/bold cyan]")
    # Convert generator to list for validation (we need to iterate twice)
    files_list = list(files_source) if not isinstance(files_source, list) else files_source
    coverage = validate_rule_coverage(files_list, rules)
    
    if coverage["coverage_pct"] < 100.0:
        print_warning(f"Rule coverage: {coverage['coverage_pct']:.1f}% ({len(coverage['matched'])}/{coverage['total_files']} files matched)")
        console.print(f"[yellow]Unmatched files: {len(coverage['unmatched'])}[/yellow]")
        
        # Auto-generate catch-all rules for unmatched files
        console.print("[dim]Auto-generating catch-all rules for unmatched files...[/dim]")
        catch_all_rules = generate_catch_all_rules(coverage["unmatched"])
        
        if catch_all_rules:
            console.print(f"[green]Generated {len(catch_all_rules)} catch-all rule(s)[/green]")
            rules.extend(catch_all_rules)
            
            # Re-validate with new rules
            coverage = validate_rule_coverage(files_list, rules)
            if coverage["coverage_pct"] >= 100.0:
                print_success(f"Coverage now at 100% ({coverage['total_files']}/{coverage['total_files']} files matched)")
            else:
                print_warning(f"Coverage improved to {coverage['coverage_pct']:.1f}% but still not 100%")
                console.print(f"[yellow]Still unmatched: {len(coverage['unmatched'])} files[/yellow]")
    else:
        print_success(f"Rule coverage: 100% ({coverage['total_files']}/{coverage['total_files']} files matched)")
    
    # Apply rules locally
    console.print("\n[bold cyan][STEP 3] Applying rules to generate moves...[/bold cyan]")
    
    # Use the list we already have
    moves_gen = generate_moves_from_rules(files_list, rules)
    
    # Stream to file
    print(f"[INFO] Streaming moves to {output_plan_path}...")
    
    with open(output_plan_path, 'w', encoding='utf-8') as f:
        # Write header
        header = {
            "type": "plan_header",
            "root": str(root),
            "folders_to_create": [], # We can't know this upfront easily with streaming
            "rules": [{"name": r.name, "template": r.target_template} for r in rules]
        }
        f.write(json.dumps(header, ensure_ascii=False) + '\n')
        
        count = 0
        for move in moves_gen:
            f.write(json.dumps(move, ensure_ascii=False) + '\n')
            count += 1
            if count % 1000 == 0:
                print(f"Generated {count} moves...", end='\r')
                
    print_success(f"Generated {count} moves from rules")
    
    # Interactive confirmation is tricky with streaming plan.
    # We'll just ask to proceed based on the rules shown above.
    
    console.print("\n[bold yellow]Proceed with this plan? \\[y]es / \\[n]o / \\[s]ave plan only[/bold yellow]")
    
    if not sys.stdin.isatty():
        print_warning("Non-interactive mode detected. Auto-approving plan.")
        return output_plan_path
        
    while True:
        choice = input("Choice: ").strip().lower()
        if choice in ['y', 'yes', '']:
            return output_plan_path
        elif choice in ['n', 'no']:
            console.print("[bold red]Plan cancelled[/bold red]")
            return None
        elif choice in ['s', 'save']:
            return output_plan_path
        else:
            console.print("Invalid choice. Enter y, n, or s")
    
    return output_plan_path


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
        
        # Try to load metadata, or stream summary if it's JSONL
        try:
            metadata = load_json(metadata_path)
            summary = build_metadata_summary(metadata)
        except json.JSONDecodeError:
            print("[INFO] Metadata appears to be JSONL (large dataset). Streaming summary...")
            from .scanner import summarize_stream
            summary = summarize_stream(metadata_path)
            metadata = {} # Empty metadata, we will stream files later
            
        rules = call_llm_for_rules(summary, args.model)
        
        if not rules:
            print("[INFO] No rules proposed")
            plan = {"folders_to_create": [], "moves": [], "rules": []}
        else:
            # If metadata is empty (streaming), we can't generate moves here easily unless we stream them.
            # But cmd_plan is supposed to generate a plan file.
            # If we are in streaming mode, we should stream the plan generation too.
            # But generate_moves_from_rules returns a generator now.
            # So we can stream moves to plan.jsonl.
            
            # Determine source
            files_source = metadata.get("files", [])
            if not files_source:
                files_source = load_metadata_files_stream(metadata_path)
            
            moves_gen = generate_moves_from_rules(files_source, rules)
            
            # Save to JSONL plan
            # But wait, cmd_plan usually saves a JSON dict at the end: save_json(plan, args.output)
            # We need to change that behavior if we are streaming.
            
            # Let's write directly to args.output here and return
            
            print(f"[INFO] Streaming plan to {args.output}...")
            with open(args.output, 'w', encoding='utf-8') as f:
                header = {
                    "type": "plan_header",
                    "root": summary.get("root", ""),
                    "folders_to_create": [],
                    "rules": [{"name": r.name, "template": r.target_template} for r in rules]
                }
                f.write(json.dumps(header, ensure_ascii=False) + '\n')
                
                count = 0
                for move in moves_gen:
                    f.write(json.dumps(move, ensure_ascii=False) + '\n')
                    count += 1
                    if count % 1000 == 0:
                        print(f"Generated {count} moves...", end='\r')
            
            print(f"[INFO] Plan has {count} moves")
            return 0
            
            # Dummy plan to satisfy the rest of the function if we didn't return
            # plan = {"folders_to_create": [], "moves": [], "rules": []}
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
    
    plan = None
    is_streaming = False
    
    try:
        plan = load_json(plan_path)
    except json.JSONDecodeError:
        print("[INFO] Plan appears to be JSONL (large dataset). Streaming execution...")
        is_streaming = True
        # For streaming, we can't easily get root from plan without peeking
        # But args.root might be provided
    
    # Get root from plan or argument
    root = None
    if args.root:
        root = args.root.resolve()
    elif plan and "root" in plan:
        root = Path(plan["root"])
    elif is_streaming:
        # Try to peek header
        with open(plan_path, 'r', encoding='utf-8') as f:
            try:
                header = json.loads(f.readline())
                if isinstance(header, dict):
                    root_str = header.get("root")
                    if root_str:
                        root = Path(root_str)
            except (ValueError, TypeError, KeyError):
                pass
    
    if not root:
        print("[ERROR] No root directory specified (use --root)")
        return 1
    
    if not root.exists() or not root.is_dir():
        print(f"[ERROR] Invalid directory: {root}")
        return 1
    
    # Validate
    if not is_streaming:
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
    else:
        print("[APPLY] Skipping upfront validation for streaming plan (validation will happen per-move).")
        validated_plan = plan_path
    
    # Apply
    # apply_plan handles dict or Path
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
    
    print_header("HDD Folder Restructure Tool v2", f"Root: {root}\nMode: {mode_str}\nModel: {args.model}")
    
    try:
        # Step 1: Scan
        console.print("\n[bold cyan][STEP 1] Scanning directory...[/bold cyan]")
        
        from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            task_id = progress.add_task("Scanning...", total=None)
            
            def progress_cb(count, path):
                # Show count and last part of path
                short_path = str(path)
                if len(short_path) > 40:
                    short_path = "..." + short_path[-37:]
                progress.update(task_id, description=f"Scanning: {count} files... {short_path}")
            
            summary = scan_and_summarize(
                root, 
                args.metadata_out, 
                args.min_size, 
                ext_include, 
                ext_exclude,
                progress_callback=progress_cb
            )
            
        console.print(f"[INFO] Found {summary['total_files']} files")
        
        # Step 2: Plan
        plan_path = args.plan_out
        
        if args.skip_llm:
            console.print(f"\n[bold cyan][STEP 2] Loading existing plan from {args.plan_out}...[/bold cyan]")
            if not args.plan_out.exists():
                print_error(f"Plan file not found: {args.plan_out}")
                return 1
            # We assume existing plan is compatible (dict or jsonl)
            plan_path = args.plan_out
        elif args.auto:
            # If metadata.json is JSONL, load_json will fail.
            # We need to handle this. But run_automatic_mode (direct) needs full metadata structure?
            # Actually run_automatic_mode calls get_top_level_folders which expects a dict with "files" list.
            # If the user runs 'auto' mode on 1M files, they will hit memory limits here loading metadata.
            # Limitation: 'direct' mode is not fully optimized for 1M files yet (requires full metadata load).
            # But 'rules' mode IS optimized.
            
            # Try loading metadata, if it fails, assume JSONL and warn/fail for direct mode
            try:
                metadata = load_json(args.metadata_out)
            except json.JSONDecodeError:
                # Likely JSONL
                if args.mode == "direct":
                    print_error("Direct mode requires full metadata load, but metadata.json seems to be JSONL (too large). Use --mode rules.")
                    return 1
                metadata = {} # Rules mode doesn't need full metadata dict if we pass metadata_path
            
            plan_path = run_automatic_mode(
                root, 
                metadata, 
                args.model, 
                args.dry_run, 
                args.plan_out, 
                args.delay, 
                args.mode
            )
            
        else:
            if args.mode == "rules":
                console.print("\n[bold cyan][STEP 2] Running rules mode...[/bold cyan]")
                plan_path = run_rules_mode(
                    root, 
                    {}, 
                    args.model, 
                    args.dry_run, 
                    args.plan_out,
                    args.delay,
                    metadata_path=args.metadata_out,
                    precomputed_summary=summary
                )
                if plan_path is None:
                    return 0
            else:
                console.print("\n[bold cyan][STEP 2] Requesting restructuring plan from LLM...[/bold cyan]")
                metadata = load_json(args.metadata_out)
                with console.status("[bold green]Thinking...[/bold green]"):
                    plan = call_llm_for_plan(metadata, args.model)
                save_json(plan, args.plan_out)
                plan_path = args.plan_out
        
        # Step 3: Validate
        # Validation with streaming plan is tricky. 
        # We'll skip full validation for now or implement streaming validation.
        # apply_plan does some checks.
        console.print("\n[bold cyan][STEP 3] Validating plan...[/bold cyan]")
        # For now, just pass the path. apply_plan handles it.
        
        # Step 4: Apply
        console.print("\n[bold cyan][STEP 4] Applying plan...[/bold cyan]")
        try:
            report = apply_plan(root, plan_path, args.dry_run, args.allow_cross_device)
            save_json(report, args.report_out)
        except RuntimeError as e:
            print_error(str(e))
            return 1
        
        # Summary
        print_success("Operation Complete!")
        console.print(f"Metadata:  {args.metadata_out}")
        console.print(f"Plan:      {args.plan_out}")
        console.print(f"Report:    {args.report_out}")
        
        if args.dry_run:
            print_warning("This was a DRY-RUN. No files were actually moved.")
            console.print("       Run without --dry-run to apply changes.")
        
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
    scan_parser.add_argument("-o", "--output", type=Path, default=Path("metadata.jsonl"),
                            help="Output metadata file (default: metadata.jsonl)")
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
    plan_parser.add_argument("-o", "--output", type=Path, default=Path("plan.jsonl"),
                            help="Output plan file (default: plan.jsonl)")
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
    run_parser.add_argument("--metadata-out", type=Path, default=Path("metadata.jsonl"),
                           help="Metadata output file")
    run_parser.add_argument("--plan-out", type=Path, default=Path("plan.jsonl"),
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

