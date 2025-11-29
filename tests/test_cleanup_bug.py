
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from reorganize_hdd.executor import cleanup_empty_dirs

class TestCleanupBug(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        
    def tearDown(self):
        shutil.rmtree(self.test_dir)
        
    def test_cleanup_destroys_bundle_internals(self):
        """Verify that the current cleanup logic incorrectly deletes empty folders inside bundles."""
        # Create a mock bundle structure
        bundle_path = self.test_dir / "Project.dspproj"
        internal_empty = bundle_path / "Contents" / "Resources" / "EmptyFolder"
        internal_empty.mkdir(parents=True)
        
        # Create a normal empty folder
        normal_empty = self.test_dir / "NormalEmpty"
        normal_empty.mkdir()
        
        # Run cleanup
        removed = cleanup_empty_dirs(self.test_dir)
        
        # Check results
        # The bug is that internal_empty IS removed. 
        # We expect this test to PASS if the bug exists (i.e., it confirms the bad behavior)
        # Or rather, we want to assert that it IS removed now, and later we will assert it is NOT removed.
        
        removed_paths = [str(Path(p)) for p in removed]
        
        # Normal folder should be removed
        self.assertIn("NormalEmpty", removed_paths)
        
        # Bundle internal folder should NOT be removed (fix verification)
        # Construct relative path string for assertion
        rel_path = str(internal_empty.relative_to(self.test_dir))
        self.assertNotIn(rel_path, removed_paths)

if __name__ == '__main__':
    unittest.main()
