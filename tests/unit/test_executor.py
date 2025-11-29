import unittest
import shutil
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from reorganize_hdd.executor import apply_plan, cleanup_empty_dirs

class TestExecutor(unittest.TestCase):
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

    def test_cleanup_empty_dirs(self):
        """Test that empty directories are cleaned up."""
        import tempfile
        
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

    @patch("reorganize_hdd.executor.save_json")
    @patch("reorganize_hdd.executor.shutil.move")
    @patch("reorganize_hdd.executor.os.stat")
    def test_undo_generation(self, mock_stat, mock_move, mock_save_json):
        """Test that undo plan is generated correctly."""
        root = Path("/tmp/test_root")
        plan = {
            "moves": [
                {"old_rel": "a.txt", "new_rel": "b.txt", "reason": "Test"}
            ]
        }
        
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "resolve", return_value=root):
            
            mock_stat.return_value = MagicMock(st_dev=1)
            
            apply_plan(root, plan, dry_run=False)
            
            # Check if save_json was called for undo_plan.json
            mock_save_json.assert_called()
            args, _ = mock_save_json.call_args
            undo_plan = args[0]
            
            self.assertEqual(undo_plan["type"], "undo")
            self.assertEqual(len(undo_plan["moves"]), 1)
            self.assertEqual(undo_plan["moves"][0]["old_rel"], "b.txt")
            self.assertEqual(undo_plan["moves"][0]["new_rel"], "a.txt")
            self.assertTrue("Undo" in undo_plan["moves"][0]["reason"])

if __name__ == "__main__":
    unittest.main()
