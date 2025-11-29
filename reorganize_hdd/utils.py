"""
Utility functions for the HDD Folder Restructure Tool.

Includes:
- JSON save/load helpers
- macOS bundle detection
- UI helpers
"""

import json
import os
import sys
from pathlib import Path
from typing import Generator, Any
from rich.console import Console
from rich.table import Table
from rich.tree import Tree
from rich.panel import Panel

# Global console instance
console = Console()

def print_header(title: str, subtitle: str = ""):
    """Print a styled header."""
    console.print(Panel(f"[bold blue]{title}[/bold blue]\n[italic]{subtitle}[/italic]", expand=False))

def print_plan_table(plan: dict):
    """Print a summary table of the plan."""
    moves = plan.get("moves", [])
    folders = plan.get("folders_to_create", [])
    
    table = Table(title="Plan Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="magenta")
    
    table.add_row("Moves", str(len(moves)))
    table.add_row("New Folders", str(len(folders)))
    
    console.print(table)
    
    if moves:
        tree = Tree("[bold green]Sample Moves[/bold green]")
        for move in moves[:10]:
            tree.add(f"[yellow]{move['old_rel']}[/yellow] -> [blue]{move['new_rel']}[/blue]")
        if len(moves) > 10:
            tree.add(f"[italic]... and {len(moves)-10} more[/italic]")
        console.print(tree)

def print_error(msg: str):
    console.print(f"[bold red]ERROR:[/bold red] {msg}")

def print_warning(msg: str):
    console.print(f"[bold yellow]WARNING:[/bold yellow] {msg}")

def print_success(msg: str):
    console.print(f"[bold green]SUCCESS:[/bold green] {msg}")


# -----------------------------------------------------------------------------
# macOS Bundle Extensions
# -----------------------------------------------------------------------------

MACOS_BUNDLE_EXTENSIONS = {
    # Application bundles
    ".app", ".bundle", ".plugin", ".kext", ".prefpane",
    ".qlgenerator", ".mdimporter", ".xpc", ".appex",
    # Apple Pro Apps project bundles
    ".dvdproj",          # iDVD
    ".imovieproject",    # iMovie (old format)
    ".fcpproject",       # Final Cut Pro X
    ".fcpbundle",        # Final Cut Pro X bundle
    ".fcp",              # Final Cut Pro 7
    ".dspproj",          # DVD Studio Pro
    ".prproj",           # Adobe Premiere Pro (treat as bundle)
    # Photo libraries
    ".photoslibrary",    # Photos app
    ".aplibrary",        # Aperture
}

# Known folder names that should be treated as bundles (atomic units)
BUNDLE_FOLDERS = {
    'VIDEO_TS', 'AUDIO_TS', 'HVDVD_TS', 'BDMV', 'CERTIFICATE',
    'DCIM', 'PRIVATE', 'AVCHD', 'MP_ROOT', 'Capture Scratch', 'Render Files',
    'Waveform Cache Files', 'Thumbnail Cache Files', 'Final Cut Pro Documents'
}


def is_known_bundle_folder(name: str) -> bool:
    """Check if a folder name is a known bundle type."""
    return name in BUNDLE_FOLDERS


def is_macos_bundle(path_segment: str) -> bool:
    """
    Check if a single path segment (folder name) looks like a macOS application bundle.
    
    Args:
        path_segment: A single folder or file name.
        
    Returns:
        True if it ends with a known bundle extension.
    """
    path_lower = path_segment.lower()
    return any(path_lower.endswith(ext) for ext in MACOS_BUNDLE_EXTENSIONS)


def path_contains_bundle(rel_path: str) -> bool:
    """
    Check if any part of a relative path is inside a macOS bundle.
    
    Args:
        rel_path: A relative path like "folder/project.dvdproj/Contents/file.txt"
        
    Returns:
        True if any path component is a bundle.
    """
    parts = rel_path.replace("\\", "/").split("/")
    for part in parts[:-1]:  # Don't check the filename itself
        if is_macos_bundle(part):
            return True
    return False


def save_json(data: Any, path: Path) -> None:
    """
    Save data to a JSON file with pretty formatting.
    
    Args:
        data: The data to serialize.
        path: The output file path.
    """
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[INFO] Saved: {path}")


def save_json_stream(
    item_generator, 
    path: Path, 
    root_path: str, 
    generated_at: str
) -> None:
    """
    Save a generator of items to a JSON file in a streaming fashion.
    Structure: {"root": ..., "generated_at": ..., "files": [ ... ]}
    
    Args:
        item_generator: Generator yielding dicts (files).
        path: Output file path.
        root_path: Value for 'root' key.
        generated_at: Value for 'generated_at' key.
    """
    with open(path, 'w', encoding='utf-8') as f:
        # Write header
        header = {
            "root": root_path,
            "generated_at": generated_at,
            "files": []
        }
        # Dump header but remove the closing brackets to append items
        # This is a bit hacky but avoids manual JSON construction of the header
        json_str = json.dumps(header, indent=2, ensure_ascii=False)
        # Remove the last closing bracket and the 'files' empty list closing
        # json_str ends with: ... "files": []\n}
        # We want to stop before the [
        
        # Safer manual approach:
        f.write('{\n')
        f.write(f'  "root": "{root_path}",\n')
        f.write(f'  "generated_at": "{generated_at}",\n')
        f.write('  "files": [\n')
        
        first = True
        for item in item_generator:
            if not first:
                f.write(',\n')
            
            # Dump item with indentation
            item_str = json.dumps(item, ensure_ascii=False)
            f.write(f'    {item_str}')
            first = False
            
        # Write footer
        f.write('\n  ]\n}')
    
    print(f"[INFO] Saved: {path}")


def load_json(path: Path) -> Any:
    """
    Load data from a JSON file.
    
    Args:
        path: The input file path.
        
    Returns:
        The deserialized data.
    """
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_metadata_files_stream(path: Path):
    """
    Yield file dicts from a metadata.json file without loading the whole file.
    Assumes the file was written by save_json_stream with one item per line.
    
    Args:
        path: Path to metadata.json
        
    Yields:
        File metadata dicts.
    """
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            
            # Skip empty lines
            if not line:
                continue
                
            # Skip header lines
            if line == '{':
                continue
            if line.startswith('"root":') or line.startswith('"generated_at":'):
                continue
            if line.startswith('"files": ['):
                continue
                
            # Skip footer lines
            if line == ']' or line == '}':
                continue
            if line == '],': 
                continue
                
            # Remove trailing comma if present
            if line.endswith(','):
                line = line[:-1]
                
            try:
                data = json.loads(line)
                # Ensure it's a file dict (has rel_path)
                if isinstance(data, dict) and "rel_path" in data:
                    yield data
            except json.JSONDecodeError:
                continue



