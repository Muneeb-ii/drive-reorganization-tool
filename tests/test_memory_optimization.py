import json
import tempfile
from pathlib import Path
from reorganize_hdd.scanner import scan_and_summarize
from reorganize_hdd.utils import load_metadata_files_stream

def test_scan_and_summarize_streaming():
    """Verify that scan_and_summarize writes valid JSON and returns correct summary."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        root = tmp_path / "scan_root"
        root.mkdir()
        
        # Create some dummy files
        (root / "folder1").mkdir()
        (root / "folder1" / "file1.txt").write_text("content")
        (root / "folder1" / "file2.jpg").write_text("content")
        (root / "folder2").mkdir()
        (root / "folder2" / "file3.mp4").write_text("content")
        
        output_json = tmp_path / "metadata.json"
        
        # Run streaming scan
        summary = scan_and_summarize(root, output_json, sample_size=2)
        
        # Verify summary
        assert summary["total_files"] == 3
        assert summary["extension_histogram"][".txt"] == 1
        assert summary["extension_histogram"][".jpg"] == 1
        assert summary["extension_histogram"][".mp4"] == 1
        
        # Verify JSON file content
        assert output_json.exists()
        with open(output_json, 'r') as f:
            data = json.load(f)
            assert Path(data["root"]).resolve() == root.resolve()
            assert len(data["files"]) == 3
            
        # Verify streaming loader
        loaded_files = list(load_metadata_files_stream(output_json))
        assert len(loaded_files) == 3
        paths = {f["rel_path"] for f in loaded_files}
        assert "folder1/file1.txt" in paths
        assert "folder1/file2.jpg" in paths
        assert "folder2/file3.mp4" in paths

def test_folder_sampling_limit():
    """Verify that we don't store samples for too many folders."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        root = tmp_path / "scan_root"
        root.mkdir()
        
        # Create 600 folders
        for i in range(600):
            (root / f"folder_{i}").mkdir()
            (root / f"folder_{i}" / "file.txt").write_text("content")
            
        output_json = tmp_path / "metadata.json"
        
        # Run scan
        summary = scan_and_summarize(root, output_json)
        
        # Verify limit
        assert len(summary["folders"]) <= 500
        # But total files should still be correct
        assert summary["total_files"] == 600

if __name__ == "__main__":
    test_scan_and_summarize_streaming()
    test_folder_sampling_limit()
    print("Test passed!")
