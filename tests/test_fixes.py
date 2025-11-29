import unittest
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from reorganize_hdd.llm.client import _try_recover_truncated_json
from reorganize_hdd.planning.rules import generate_moves_from_rules, OrganizationRule, MatchCriteria
from reorganize_hdd.executor import apply_plan

class TestBugFixes(unittest.TestCase):
    
    def test_json_recovery_truncated_string(self):
        """Test that truncated strings are cut off safely."""
        # Case 1: Truncated inside a string value
        truncated = '{"moves": [{"old": "a", "new": "path/to/fi'
        recovered = _try_recover_truncated_json(truncated)
        
        # Should have removed the incomplete key/value pair or string
        # The logic tries to cut at the last comma/brace
        # In this case, it should probably result in {"moves": []} or similar valid JSON
        self.assertIsInstance(recovered, dict)
        
        # Case 2: Truncated after a complete object in a list
        truncated_list = '{"moves": [{"a": 1}, {"b": 2'
        recovered_list = _try_recover_truncated_json(truncated_list)
        self.assertIn("moves", recovered_list)
        # With stack-based recovery, we get [{"a": 1}, {}] because we close the partial object
        self.assertEqual(len(recovered_list["moves"]), 2)
        self.assertEqual(recovered_list["moves"][0]["a"], 1)

    def test_collision_handling_paths(self):
        """Test that collision handling doesn't produce ./ prefix."""
        files = [
            {"rel_path": "folder1/file.txt", "ext": ".txt"},
            {"rel_path": "folder2/file.txt", "ext": ".txt"}
        ]
        
        # Rule that maps everything to the same place
        rule = OrganizationRule(
            name="Test Rule",
            match=MatchCriteria(ext_in=[".txt"]),
            target_template="combined/file.txt",
            priority=10
        )
        
        moves = generate_moves_from_rules(files, [rule])
        
        destinations = [m["new_rel"] for m in moves]
        self.assertIn("combined/file.txt", destinations)
        
        # The second one should be combined/file_1.txt
        self.assertIn("combined/file_1.txt", destinations)
        
        # Let's test mapping to root
        rule_root = OrganizationRule(
            name="Root Rule",
            match=MatchCriteria(ext_in=[".txt"]),
            target_template="file.txt",
            priority=10
        )
        
        moves_root = generate_moves_from_rules(files, [rule_root])
        dests_root = [m["new_rel"] for m in moves_root]
        
        print(f"DEBUG: Root destinations: {dests_root}")
        
        self.assertIn("file.txt", dests_root)
        # Check for the collision rename
        collision_moves = [d for d in dests_root if d != "file.txt"]
        self.assertTrue(collision_moves, f"No collision move found in {dests_root}")
        
        collision_move = collision_moves[0]
        self.assertEqual(collision_move, "file_1.txt")
        self.assertFalse(collision_move.startswith("./"))

    @patch("reorganize_hdd.executor.shutil.move")
    @patch("reorganize_hdd.executor.os.stat")
    def test_executor_missing_source(self, mock_stat, mock_move):
        """Test that executor skips missing source files without crashing."""
        root = Path("/tmp/test_root")
        plan = {
            "moves": [
                {"old_rel": "missing.txt", "new_rel": "new.txt"}
            ]
        }
        
        # Mock root existence
        with patch.object(Path, "exists") as mock_exists:
            # Root exists
            # Source file does NOT exist
            # Dest parent exists (or created)
            mock_exists.side_effect = lambda: False if "missing.txt" in str(mock_exists.call_args[0]) else True
            
            # We need to mock resolve() to return a path that we can check
            with patch.object(Path, "resolve", return_value=root):
                 # Mock os.stat to return objects with st_dev
                mock_stat.return_value = MagicMock(st_dev=1)
                
                # Run apply_plan
                report = apply_plan(root, plan, dry_run=False, allow_cross_device=False)
                
                # Should not have called move
                mock_move.assert_not_called()
                
                # Should have recorded 0 moves
                self.assertEqual(len(report["moves"]), 0)

    def test_validator_allows_bundles(self):
        """Test that validator allows moving known bundle directories."""
        from reorganize_hdd.planning.validator import validate_plan
        
        root = Path("/tmp/test_root")
        plan = {
            "moves": [
                {"old_rel": "VIDEO_TS", "new_rel": "Movies/VIDEO_TS"},
                {"old_rel": "NormalFolder", "new_rel": "Movies/NormalFolder"},
                {"old_rel": "Project.fcp", "new_rel": "Projects/Project.fcp"}
            ]
        }
        
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "resolve", return_value=root), \
             patch.object(Path, "is_file") as mock_is_file, \
             patch.object(Path, "is_dir") as mock_is_dir:
            
            # Setup mocks
            # VIDEO_TS -> is_dir=True, is_file=False (Should be ALLOWED)
            # NormalFolder -> is_dir=True, is_file=False (Should be SKIPPED)
            # Project.fcp -> is_dir=True, is_file=False (Should be ALLOWED as bundle extension)
            
            def is_dir_side_effect():
                # We need to check which path is being checked
                # This is tricky with mocks, so we'll simplify by assuming checking based on name
                return True
            
            mock_is_dir.return_value = True
            mock_is_file.return_value = False
            
            # We need to mock the path names for the bundle check
            # Since we can't easily mock the 'name' attribute of the Path objects created inside the function
            # we will rely on the fact that the validator creates Path objects from the strings.
            # However, `src_path.name` will be correct because it comes from `root / old_rel`.
            
            valid_moves = validate_plan(root, plan)
            
            # We expect VIDEO_TS and Project.fcp to be valid, NormalFolder to be skipped
            allowed_sources = [m["old_rel"] for m in valid_moves]
            
            self.assertIn("VIDEO_TS", allowed_sources)
            self.assertIn("Project.fcp", allowed_sources)
            self.assertNotIn("NormalFolder", allowed_sources)

    def test_cleanup_empty_dirs(self):
        """Test that empty directories are cleaned up."""
        from reorganize_hdd.executor import cleanup_empty_dirs
        import tempfile
        import shutil
        
        # Create a temp directory structure
        # root/
        #   empty/
        #   nested/
        #     empty/
        #   not_empty/
        #     file.txt
        
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "empty").mkdir()
            (root / "nested" / "empty").mkdir(parents=True)
            (root / "not_empty").mkdir()
            (root / "not_empty" / "file.txt").touch()
            
            removed = cleanup_empty_dirs(root)
            
            # Check results
            self.assertFalse((root / "empty").exists())
            self.assertFalse((root / "nested" / "empty").exists())
            self.assertFalse((root / "nested").exists()) # Should be removed because it became empty
            self.assertTrue((root / "not_empty").exists())
            
            # Check return list
            # Note: order depends on os.walk, but generally bottom-up
            self.assertIn("empty", removed)
            self.assertIn("nested/empty", removed)
            self.assertIn("nested", removed)

    def test_scanner_detects_extension_bundles(self):
        """Test that scanner detects bundles by extension (e.g. .fcp, .dspproj)."""
        from reorganize_hdd.scanner import scan_directory
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
            files = scan_directory(root)
            
            # Check results
            rel_paths = [f["rel_path"] for f in files]
            
            # .fcp should be listed as a file (bundle), contents NOT listed
            self.assertIn("Project.fcp", rel_paths)
            self.assertNotIn("Project.fcp/Contents/Info.plist", rel_paths)
            
            # .dspproj should be listed as a file (bundle)
            self.assertIn("Project.dspproj", rel_paths)
            
            # Normal folder contents SHOULD be listed
            self.assertIn("Normal/file.txt", rel_paths)

if __name__ == "__main__":
    unittest.main()
