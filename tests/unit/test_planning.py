import unittest
from pathlib import Path
from unittest.mock import patch
from reorganize_hdd.planning.rules import generate_moves_from_rules, OrganizationRule, MatchCriteria
from reorganize_hdd.llm.client import _try_recover_truncated_json

class TestPlanning(unittest.TestCase):
    def test_json_recovery_truncated_string(self):
        """Test that truncated strings are cut off safely."""
        # Case 1: Truncated inside a string value
        truncated = '{"moves": [{"old": "a", "new": "path/to/fi'
        recovered = _try_recover_truncated_json(truncated)
        self.assertIsInstance(recovered, dict)
        
        # Case 2: Truncated after a complete object in a list
        truncated_list = '{"moves": [{"a": 1}, {"b": 2'
        recovered_list = _try_recover_truncated_json(truncated_list)
        self.assertIn("moves", recovered_list)
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
        self.assertIn("combined/file_1.txt", destinations)
        
        # Test mapping to root
        rule_root = OrganizationRule(
            name="Root Rule",
            match=MatchCriteria(ext_in=[".txt"]),
            target_template="file.txt",
            priority=10
        )
        
        moves_root = generate_moves_from_rules(files, [rule_root])
        dests_root = [m["new_rel"] for m in moves_root]
        
        self.assertIn("file.txt", dests_root)
        collision_moves = [d for d in dests_root if d != "file.txt"]
        self.assertTrue(collision_moves)
        self.assertEqual(collision_moves[0], "file_1.txt")
        self.assertFalse(collision_moves[0].startswith("./"))

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
            
            mock_is_dir.return_value = True
            mock_is_file.return_value = False
            
            valid_moves = validate_plan(root, plan)
            allowed_sources = [m["old_rel"] for m in valid_moves]
            
            self.assertIn("VIDEO_TS", allowed_sources)
            self.assertIn("Project.fcp", allowed_sources)
            self.assertNotIn("NormalFolder", allowed_sources)

if __name__ == "__main__":
    unittest.main()
