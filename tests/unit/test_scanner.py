import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock
from reorganize_hdd.scanner import detect_clusters, get_exif_date, scan_directory

class TestScanner(unittest.TestCase):
    def test_name_clustering(self):
        files = []
        # Create 15 files for "Trip_Photos"
        for i in range(15):
            files.append({
                "rel_path": f"DCIM/Trip_Photos_{i:03d}.jpg",
                "modified": "2023-01-01T12:00:00",
                "ext": ".jpg"
            })
        # Add some random files
        files.append({"rel_path": "misc.txt", "modified": "2023-01-01T12:00:00", "ext": ".txt"})
        
        clusters = detect_clusters(files, min_files=10)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["type"], "name")
        self.assertEqual(clusters[0]["name_hint"], "Trip_Photos")
        self.assertEqual(clusters[0]["count"], 15)

    def test_time_clustering(self):
        files = []
        base_time = datetime(2023, 12, 25, 10, 0, 0)
        
        # Create 15 files on Christmas (1 hour apart)
        for i in range(15):
            t = base_time + timedelta(minutes=i*10)
            files.append({
                "rel_path": f"IMG_{i}.jpg",
                "modified": t.isoformat(),
                "ext": ".jpg"
            })
            
        # Create 5 files a week later (should not be in cluster)
        later_time = base_time + timedelta(days=7)
        for i in range(5):
            t = later_time + timedelta(minutes=i*10)
            files.append({
                "rel_path": f"IMG_LATER_{i}.jpg",
                "modified": t.isoformat(),
                "ext": ".jpg"
            })
            
        clusters = detect_clusters(files, min_files=10, gap_hours=24)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["type"], "time")
        self.assertTrue("2023-12-25" in clusters[0]["name_hint"])
        self.assertEqual(clusters[0]["count"], 15)

    def test_scanner_detects_extension_bundles(self):
        """Test that scanner detects bundles by extension (e.g. .fcp, .dspproj)."""
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            
            # Create a fake .fcp bundle (directory)
            fcp_bundle = root / "Project.fcp"
            fcp_bundle.mkdir()
            (fcp_bundle / "Contents").mkdir()
            (fcp_bundle / "Contents" / "Info.plist").touch()
            
            # Create a fake .dspproj bundle
            dsp_bundle = root / "Project.dspproj"
            dsp_bundle.mkdir()
            (dsp_bundle / "Contents").mkdir()
            
            # Create a normal folder
            normal_folder = root / "Normal"
            normal_folder.mkdir()
            (normal_folder / "file.txt").touch()
            
            # Scan
            files = list(scan_directory(root))
            
            # Check results
            rel_paths = [f["rel_path"] for f in files]
            
            # .fcp should be listed as a file (bundle), contents NOT listed
            self.assertIn("Project.fcp", rel_paths)
            self.assertNotIn("Project.fcp/Contents/Info.plist", rel_paths)
            
            # .dspproj should be listed as a file (bundle)
            self.assertIn("Project.dspproj", rel_paths)
            
            # Normal folder contents SHOULD be listed
            self.assertIn("Normal/file.txt", rel_paths)

    @patch("reorganize_hdd.scanner.Image.open")
    def test_exif_extraction(self, mock_open):
        """Test EXIF date extraction."""
        # Mock image object
        mock_img = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_img
        
        # Case 1: Valid EXIF
        # 36867 is DateTimeOriginal
        mock_img.getexif.return_value = {36867: "2023:12:25 10:30:00"}
        
        date = get_exif_date(Path("test.jpg"))
        self.assertEqual(date, "2023-12-25T10:30:00")
        
        # Case 2: No EXIF
        mock_img.getexif.return_value = {}
        date = get_exif_date(Path("test.jpg"))
        self.assertIsNone(date)
        
        # Case 3: Invalid Date Format
        mock_img.getexif.return_value = {36867: "Invalid"}
        date = get_exif_date(Path("test.jpg"))
        self.assertIsNone(date)

    def test_scan_and_summarize_streaming(self):
        """Verify that scan_and_summarize writes valid JSON and returns correct summary."""
        import tempfile
        import json
        from reorganize_hdd.scanner import scan_and_summarize
        from reorganize_hdd.utils import load_metadata_files_stream
        
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
            self.assertEqual(summary["total_files"], 3)
            self.assertEqual(summary["extension_histogram"][".txt"], 1)
            self.assertEqual(summary["extension_histogram"][".jpg"], 1)
            self.assertEqual(summary["extension_histogram"][".mp4"], 1)
            
            # Verify JSON file content
            self.assertTrue(output_json.exists())
            with open(output_json, 'r') as f:
                data = json.load(f)
                self.assertEqual(Path(data["root"]).resolve(), root.resolve())
                self.assertEqual(len(data["files"]), 3)
                
            # Verify streaming loader
            loaded_files = list(load_metadata_files_stream(output_json))
            self.assertEqual(len(loaded_files), 3)
            paths = {f["rel_path"] for f in loaded_files}
            self.assertIn("folder1/file1.txt", paths)
            self.assertIn("folder1/file2.jpg", paths)
            self.assertIn("folder2/file3.mp4", paths)

    def test_folder_sampling_limit(self):
        """Verify that we don't store samples for too many folders."""
        import tempfile
        from reorganize_hdd.scanner import scan_and_summarize
        
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
            self.assertLessEqual(len(summary["folders"]), 500)
            # But total files should still be correct
            self.assertEqual(summary["total_files"], 600)

if __name__ == '__main__':
    unittest.main()
