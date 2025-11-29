import unittest
from datetime import datetime, timedelta
from reorganize_hdd.scanner import detect_clusters
from reorganize_hdd.planning.rules import MatchCriteria, OrganizationRule

class TestEventLogic(unittest.TestCase):
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

    def test_date_range_matching(self):
        criteria = MatchCriteria(
            date_start="2023-12-24T00:00:00",
            date_end="2023-12-26T23:59:59"
        )
        
        match_file = {"rel_path": "a.jpg", "modified": "2023-12-25T12:00:00", "ext": ".jpg"}
        no_match_file = {"rel_path": "b.jpg", "modified": "2023-12-20T12:00:00", "ext": ".jpg"}
        
        self.assertTrue(criteria.matches(match_file))
        self.assertFalse(criteria.matches(no_match_file))

    def test_type_variable(self):
        rule = OrganizationRule(
            name="Test Rule",
            match=MatchCriteria(),
            target_template="Events/{type}/"
        )
        
        photo = {"rel_path": "a.jpg", "ext": ".jpg", "modified": ""}
        video = {"rel_path": "b.mp4", "ext": ".mp4", "modified": ""}
        doc = {"rel_path": "c.pdf", "ext": ".pdf", "modified": ""}
        
        self.assertEqual(rule.render_target(photo), "Events/Photos/a.jpg")
        self.assertEqual(rule.render_target(video), "Events/Videos/b.mp4")
        self.assertEqual(rule.render_target(doc), "Events/Documents/c.pdf")

if __name__ == '__main__':
    unittest.main()
