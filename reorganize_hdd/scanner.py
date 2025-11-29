"""
Directory scanning and metadata collection.

Functions for recursively scanning directories and building file metadata.
"""

import os
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import re
from .utils import BUNDLE_FOLDERS, is_macos_bundle
from PIL import Image, UnidentifiedImageError
from PIL.ExifTags import TAGS

def get_exif_date(filepath: Path) -> str | None:
    """Extract the 'DateTimeOriginal' from an image's EXIF data."""
    try:
        with Image.open(filepath) as img:
            exif = img.getexif()
            if not exif:
                return None
            
            # Look for DateTimeOriginal (36867) or DateTime (306)
            # We iterate to find the tag name because IDs are constant but looking up by name is clearer
            for tag_id in exif:
                tag = TAGS.get(tag_id, tag_id)
                if tag == 'DateTimeOriginal':
                    date_str = exif.get(tag_id)
                    # Format is usually "YYYY:MM:DD HH:MM:SS"
                    # Convert to ISO "YYYY-MM-DDTHH:MM:SS"
                    if date_str and len(date_str) >= 19:
                        return date_str[:10].replace(':', '-') + 'T' + date_str[11:]
                
            # Fallback to DateTime if Original not found
            for tag_id in exif:
                tag = TAGS.get(tag_id, tag_id)
                if tag == 'DateTime':
                    date_str = exif.get(tag_id)
                    if date_str and len(date_str) >= 19:
                        return date_str[:10].replace(':', '-') + 'T' + date_str[11:]
                        
    except (UnidentifiedImageError, OSError, Exception):
        pass
    return None


def scan_directory(
    root: Path,
    min_size: int = 0,
    ext_include: set[str] | None = None,
    ext_exclude: set[str] | None = None
):
    """
    Recursively scan a directory and yield metadata for all files.
    
    Args:
        root: The root directory to scan.
        min_size: Only include files larger than this many bytes.
        ext_include: If set, only include files with these extensions.
        ext_exclude: If set, exclude files with these extensions.
        
    Yields:
        Dicts containing file metadata.
    """
    root = root.resolve()
    skipped_by_filter = 0
    
    # Folders to completely ignore
    IGNORE_FOLDERS = {
        'System Volume Information', '$RECYCLE.BIN', '.fseventsd', '.Spotlight-V100', '.Trashes'
    }
    
    # Simple progress counter
    scanned_count = 0
    
    for dirpath, dirnames, filenames in os.walk(root):
        # 1. Prune ignored folders
        dirnames[:] = [d for d in dirnames if d not in IGNORE_FOLDERS]
        
        # 2. Handle Bundles
        bundles = [d for d in dirnames if d in BUNDLE_FOLDERS or is_macos_bundle(d)]
        
        for bundle_name in bundles:
            bundle_path = Path(dirpath) / bundle_name
            try:
                stat = bundle_path.stat()
                rel_path = bundle_path.relative_to(root)
                rel_path_str = str(rel_path).replace(os.sep, '/')
                
                yield {
                    "rel_path": rel_path_str,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds'),
                    "ext": "/" # Special marker for folders
                }
                scanned_count += 1
                if scanned_count % 5000 == 0:
                    print(f"Scanning: {scanned_count} files...", end='\r')
            except (PermissionError, OSError):
                pass
            
            dirnames.remove(bundle_name)
        
        # 3. Process Files
        for filename in filenames:
            scanned_count += 1
            if scanned_count % 5000 == 0:
                print(f"Scanning: {scanned_count} files...", end='\r')
                
            filepath = Path(dirpath) / filename
            
            if filename.startswith('.'):
                continue
            
            if filepath.is_symlink():
                continue
                
            try:
                stat = filepath.stat()
                ext = filepath.suffix.lower() if filepath.suffix else ''
                
                if ext_include is not None and ext not in ext_include:
                    skipped_by_filter += 1
                    continue
                
                if ext_exclude is not None and ext in ext_exclude:
                    skipped_by_filter += 1
                    continue
                
                if min_size > 0 and stat.st_size < min_size:
                    skipped_by_filter += 1
                    continue
                
                rel_path = filepath.relative_to(root)
                rel_path_str = str(rel_path).replace(os.sep, '/')
                modified = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')
                
                # Try to get EXIF date for images
                date_taken = None
                if ext in {'.jpg', '.jpeg', '.png', '.tiff', '.webp', '.heic'}:
                    date_taken = get_exif_date(filepath)
                
                yield {
                    "rel_path": rel_path_str,
                    "size_bytes": stat.st_size,
                    "modified": modified,
                    "date_taken": date_taken,
                    "ext": ext
                }
            except (PermissionError, OSError) as e:
                # print(f"[WARN] Skipping inaccessible file: {filepath} ({e})")
                continue
    
    print(f"Scanning: {scanned_count} files... Done!")
    
    if skipped_by_filter > 0:
        print(f"[INFO] Skipped {skipped_by_filter} files by filter")


def scan_and_summarize(
    root: Path,
    output_path: Path,
    min_size: int = 0,
    ext_include: set[str] | None = None,
    ext_exclude: set[str] | None = None,
    sample_size: int = 5000
) -> dict:
    """
    Scan directory, stream to JSON file, and build summary in memory.
    Uses reservoir sampling to keep memory usage low.
    
    Args:
        root: Root directory.
        output_path: Path to save metadata.json.
        sample_size: Number of files to keep for LLM analysis.
        
    Returns:
        Summary dict suitable for LLM.
    """
    from .utils import save_json_stream
    
    root = root.resolve()
    generated_at = datetime.now().isoformat(timespec='seconds')
    
    # Stats containers
    total_files = 0
    total_size = 0
    ext_counts: dict[str, int] = defaultdict(int)
    ext_sizes: dict[str, int] = defaultdict(int)
    year_counts: dict[str, int] = defaultdict(int)
    folder_files: dict[str, list[dict]] = defaultdict(list)
    folder_sizes: dict[str, int] = defaultdict(int)
    
    # Reservoir for clustering/sampling
    reservoir = []
    
    def item_processor(generator):
        nonlocal total_files, total_size
        
        for item in generator:
            total_files += 1
            size = item.get("size_bytes", 0)
            total_size += size
            
            # Update stats
            ext = item.get("ext", "")
            ext_key = ext if ext else "(no extension)"
            ext_counts[ext_key] += 1
            ext_sizes[ext_key] += size
            
            modified = item.get("modified", "")
            if modified:
                year = modified[:4]
                year_counts[year] += 1
            
            rel_path = item["rel_path"]
            parts = rel_path.split("/")
            top_folder = parts[0] if len(parts) > 1 else "(root files)"
            folder_sizes[top_folder] += size
            
            # Reservoir sampling for global list
            if len(reservoir) < sample_size:
                reservoir.append(item)
            else:
                j = random.randint(0, total_files - 1)
                if j < sample_size:
                    reservoir[j] = item
            
            # Per-folder sampling (keep up to 30 per folder, max 500 folders)
            # Only add sample if we are already tracking this folder OR we haven't hit the limit
            if top_folder in folder_files or len(folder_files) < 500:
                if len(folder_files[top_folder]) < 30:
                    folder_files[top_folder].append(item)
            
            yield item

    # Run the scan and stream to file
    scanner_gen = scan_directory(root, min_size, ext_include, ext_exclude)
    save_json_stream(item_processor(scanner_gen), output_path, str(root), generated_at)
    
    # Build folder summaries
    folder_summaries = []
    for folder_name in sorted(folder_files.keys()):
        samples = folder_files[folder_name]
        sample_paths = [f["rel_path"] for f in samples]
        
        # Extension breakdown for this folder (approximate based on samples)
        folder_ext_counts: dict[str, int] = defaultdict(int)
        for f in samples:
            ext = f.get("ext", "") or "(no extension)"
            folder_ext_counts[ext] += 1
            
        folder_summaries.append({
            "name": folder_name,
            "file_count": 0, # We don't track exact count per folder to save memory, or we could add another counter
            "total_size_bytes": folder_sizes[folder_name],
            "extensions": dict(sorted(folder_ext_counts.items(), key=lambda x: -x[1])),
            "sample_paths": sample_paths
        })
        
    # Detect clusters on the reservoir sample
    clusters = detect_clusters(reservoir)
    
    return {
        "root": str(root),
        "total_files": total_files,
        "total_size_bytes": total_size,
        "extension_histogram": dict(sorted(ext_counts.items(), key=lambda x: -x[1])),
        "extension_sizes": dict(sorted(ext_sizes.items(), key=lambda x: -x[1])),
        "year_distribution": dict(sorted(year_counts.items())),
        "folders": folder_summaries,
        "clusters": clusters
    }


def detect_clusters(files: list[dict], min_files: int = 10, gap_hours: int = 24) -> list[dict]:
    """
    Detect clusters of files based on name similarity or time proximity.
    
    Args:
        files: List of file metadata dicts.
        min_files: Minimum number of files to form a cluster.
        gap_hours: Max hours between files to be considered same time cluster.
        
    Returns:
        List of cluster dicts:
        {
            "type": "name" | "time",
            "name_hint": "Trip_Photos",
            "count": 50,
            "date_start": "2023-01-01",
            "date_end": "2023-01-02",
            "sample_files": ["Trip_001.jpg", ...]
        }
    """
    clusters = []
    
    # 1. Name Clustering (Stage 1)
    # Group by "stem" (filename without digits/ext)
    name_groups = defaultdict(list)
    ungrouped_files = []
    
    for f in files:
        rel_path = f["rel_path"]
        filename = rel_path.split("/")[-1]
        
        # Remove extension
        stem = filename.rsplit('.', 1)[0] if '.' in filename else filename
        
        # Remove trailing digits/sequences (e.g. IMG_001 -> IMG_)
        stem_clean = re.sub(r'[\d\-_]+$', '', stem)
        
        if len(stem_clean) > 3:  # Only group if stem is meaningful
            name_groups[stem_clean].append(f)
        else:
            ungrouped_files.append(f)
            
    # Process name groups
    for stem, group in name_groups.items():
        if len(group) >= min_files:
            # Found a name cluster
            # Use date_taken if available, else modified
            dates = []
            for f in group:
                d = f.get("date_taken") or f.get("modified")
                if d:
                    dates.append(d)
            dates.sort()
            
            clusters.append({
                "type": "name",
                "name_hint": stem,
                "count": len(group),
                "date_start": dates[0] if dates else None,
                "date_end": dates[-1] if dates else None,
                "sample_files": [f["rel_path"] for f in group[:5]]
            })
        else:
            # Too small, treat as ungrouped
            ungrouped_files.extend(group)
            
    # 2. Time Clustering (Stage 2 - Fallback)
    # Sort remaining files by time
    valid_files = []
    for f in ungrouped_files:
        d = f.get("date_taken") or f.get("modified")
        if d:
            # Store the effective date in the dict temporarily for sorting
            f["_effective_date"] = d
            valid_files.append(f)
            
    valid_files.sort(key=lambda x: x["_effective_date"])
    
    if not valid_files:
        return clusters
        
    current_cluster = [valid_files[0]]
    
    for i in range(1, len(valid_files)):
        prev = valid_files[i-1]
        curr = valid_files[i]
        
        try:
            t1 = datetime.fromisoformat(prev["_effective_date"])
            t2 = datetime.fromisoformat(curr["_effective_date"])
            
            if (t2 - t1) < timedelta(hours=gap_hours):
                current_cluster.append(curr)
            else:
                # Cluster ended
                if len(current_cluster) >= min_files:
                    clusters.append({
                        "type": "time",
                        "name_hint": f"Event_{t1.strftime('%Y-%m-%d')}",
                        "count": len(current_cluster),
                        "date_start": current_cluster[0]["_effective_date"],
                        "date_end": current_cluster[-1]["_effective_date"],
                        "sample_files": [f["rel_path"] for f in current_cluster[:5]]
                    })
                current_cluster = [curr]
        except (ValueError, TypeError):
            continue
            
    # Check last cluster
    if len(current_cluster) >= min_files:
        t1 = datetime.fromisoformat(current_cluster[0]["_effective_date"])
        clusters.append({
            "type": "time",
            "name_hint": f"Event_{t1.strftime('%Y-%m-%d')}",
            "count": len(current_cluster),
            "date_start": current_cluster[0]["_effective_date"],
            "date_end": current_cluster[-1]["_effective_date"],
            "sample_files": [f["rel_path"] for f in current_cluster[:5]]
        })
        
    return clusters


def build_metadata(
    root: Path,
    min_size: int = 0,
    ext_include: set[str] | None = None,
    ext_exclude: set[str] | None = None
) -> dict:
    """
    Legacy wrapper for compatibility.
    WARNING: Loads all files into memory. Use scan_and_summarize for large datasets.
    """
    root = root.resolve()
    files = list(scan_directory(root, min_size, ext_include, ext_exclude))
    
    return {
        "root": str(root),
        "generated_at": datetime.now().isoformat(timespec='seconds'),
        "files": files
    }


def build_metadata_summary(metadata: dict) -> dict:
    """
    Build a compact summary of metadata for LLM consumption.
    
    Instead of sending full file lists, this creates:
    - Extension histogram (count per ext)
    - Date distribution (files per year)
    - Top-level folder list with file counts
    - Sample file paths per folder (30 random samples)
    - Total size per folder
    
    Args:
        metadata: Full metadata dict from build_metadata().
        
    Returns:
        A summary dict suitable for rule-based LLM prompts.
    """
    files = metadata.get("files", [])
    
    # Extension histogram
    ext_counts: dict[str, int] = defaultdict(int)
    ext_sizes: dict[str, int] = defaultdict(int)
    
    # Year distribution
    year_counts: dict[str, int] = defaultdict(int)
    
    # Folder analysis
    folder_files: dict[str, list[dict]] = defaultdict(list)
    folder_sizes: dict[str, int] = defaultdict(int)
    
    for f in files:
        rel_path = f["rel_path"]
        ext = f.get("ext", "")
        size = f.get("size_bytes", 0)
        modified = f.get("modified", "")
        
        # Extension stats
        ext_key = ext if ext else "(no extension)"
        ext_counts[ext_key] += 1
        ext_sizes[ext_key] += size
        
        # Year distribution
        if modified:
            year = modified[:4]  # First 4 chars of ISO date
            year_counts[year] += 1
        
        # Folder stats - get top-level folder
        parts = rel_path.split("/")
        if len(parts) > 1:
            top_folder = parts[0]
        else:
            top_folder = "(root files)"
        
        folder_files[top_folder].append(f)
        folder_sizes[top_folder] += size
    
    # Build folder summaries with samples
    folder_summaries = []
    for folder_name in sorted(folder_files.keys()):
        folder_file_list = folder_files[folder_name]
        
        # Get random sample (up to 30 files)
        sample_size = min(30, len(folder_file_list))
        samples = random.sample(folder_file_list, sample_size)
        sample_paths = [f["rel_path"] for f in samples]
        
        # Extension breakdown for this folder
        folder_ext_counts: dict[str, int] = defaultdict(int)
        for f in folder_file_list:
            ext = f.get("ext", "") or "(no extension)"
            folder_ext_counts[ext] += 1
        
        folder_summaries.append({
            "name": folder_name,
            "file_count": len(folder_file_list),
            "total_size_bytes": folder_sizes[folder_name],
            "extensions": dict(sorted(folder_ext_counts.items(), key=lambda x: -x[1])),
            "sample_paths": sample_paths
        })
    
    # Detect clusters
    clusters = detect_clusters(files)

    return {
        "root": metadata.get("root", ""),
        "total_files": len(files),
        "total_size_bytes": sum(f.get("size_bytes", 0) for f in files),
        "extension_histogram": dict(sorted(ext_counts.items(), key=lambda x: -x[1])),
        "extension_sizes": dict(sorted(ext_sizes.items(), key=lambda x: -x[1])),
        "year_distribution": dict(sorted(year_counts.items())),
        "folders": folder_summaries,
        "clusters": clusters
    }



