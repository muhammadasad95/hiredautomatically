import unittest
import sqlite3

from job_priority import classify_priority_tier, job_priority_key, select_pending_jobs


class JobPriorityTests(unittest.TestCase):
    def test_requested_tier_order(self):
        cases = [
            (("Remote IAM Architect", "Remote position", "Remote"), 0),
            (("Backend Engineer", "Remote position", "Remote"), 1),
            (("IAM Architect", "Hybrid work schedule", "New York"), 2),
            (("Backend Engineer", "On-site position", "Boston"), 3),
        ]

        for job, expected_tier in cases:
            with self.subTest(job=job):
                self.assertEqual(classify_priority_tier(*job)[0], expected_tier)

    def test_identity_in_description_counts(self):
        tier, _, _, is_identity = classify_priority_tier(
            "Senior Software Engineer",
            "This remote role will own identity governance and access management.",
            "United States",
        )
        self.assertEqual(tier, 0)
        self.assertTrue(is_identity)

    def test_unknown_work_mode_is_review_tier(self):
        tier, label, work_mode, _ = classify_priority_tier(
            "IAM Engineer", "Build identity services for the company.", "New York"
        )
        self.assertEqual(tier, 4)
        self.assertEqual(work_mode, "unknown")
        self.assertIn("review", label.lower())

    def test_negated_remote_is_not_classified_as_remote(self):
        tier, _, work_mode, _ = classify_priority_tier(
            "IAM Engineer", "Remote work is not available; this is an on-site role.", "Boston"
        )
        self.assertEqual(tier, 2)
        self.assertEqual(work_mode, "onsite")

    def test_hybrid_cloud_does_not_imply_hybrid_work(self):
        tier, _, work_mode, _ = classify_priority_tier(
            "Cloud Engineer", "Experience with hybrid cloud infrastructure required.", "Boston"
        )
        self.assertEqual(tier, 4)
        self.assertEqual(work_mode, "unknown")

    def test_secondary_sort_uses_match_then_freshness(self):
        jobs = [
            ("Remote Engineer", "Remote position", "Remote", 70, "2026-10-20", "c"),
            ("Remote Engineer", "Remote position", "Remote", 90, "2026-10-18", "b"),
            ("Remote Engineer", "Remote position", "Remote", 90, "2026-10-19", "a"),
        ]
        ordered = sorted(jobs, key=lambda job: job_priority_key(*job[:5], stable_id=job[5]))
        self.assertEqual([job[5] for job in ordered], ["a", "b", "c"])

    def make_connection(self, include_posted_date=True):
        connection = sqlite3.connect(":memory:")
        posted_column = ", date_posted TEXT" if include_posted_date else ""
        connection.execute(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, title TEXT, company TEXT, "
            "description TEXT, location TEXT, match_score INTEGER, status TEXT" + posted_column + ")"
        )
        return connection

    def test_selector_applies_priority_and_batch_limit(self):
        connection = self.make_connection()
        connection.executemany(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("onsite", "IAM Engineer", "C", "On-site role", "Boston", 99, "PENDING", "2026-10-20"),
                ("remote-other", "Backend Engineer", "C", "Remote position", "Remote", 99, "PENDING", "2026-10-20"),
                ("remote-iam", "IAM Engineer", "C", "Remote position", "Remote", 60, "PENDING", "2026-10-20"),
                ("unknown", "IAM Engineer", "C", "Build identity systems", "Boston", 100, "PENDING", "2026-10-20"),
                ("not-pending", "IAM Engineer", "C", "Remote position", "Remote", 100, "TAILORED", "2026-10-20"),
            ],
        )

        selected, unknown_count, eligible_count = select_pending_jobs(connection, limit=2)

        self.assertEqual([row[0] for row in selected], ["remote-iam", "remote-other"])
        self.assertEqual(unknown_count, 1)
        self.assertEqual(eligible_count, 3)
        connection.close()

    def test_selector_holds_unknown_unless_explicitly_included(self):
        connection = self.make_connection()
        connection.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("unknown", "IAM Engineer", "C", "Build identity systems", "Boston", 100, "PENDING", "2026-10-20"),
        )

        selected, unknown_count, eligible_count = select_pending_jobs(connection, limit=10)
        self.assertEqual(selected, [])
        self.assertEqual(unknown_count, 1)
        self.assertEqual(eligible_count, 0)

        selected, unknown_count, eligible_count = select_pending_jobs(
            connection, limit=10, include_unknown=True
        )
        self.assertEqual([row[0] for row in selected], ["unknown"])
        self.assertEqual(unknown_count, 0)
        self.assertEqual(eligible_count, 1)
        connection.close()

    def test_selector_supports_schema_without_posted_date(self):
        connection = self.make_connection(include_posted_date=False)
        connection.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("remote", "IAM Engineer", "C", "Remote position", "Remote", 80, "PENDING"),
        )

        selected, unknown_count, eligible_count = select_pending_jobs(connection, limit=1)
        self.assertEqual([row[0] for row in selected], ["remote"])
        self.assertIsNone(selected[0][6])
        self.assertEqual((unknown_count, eligible_count), (0, 1))
        connection.close()


if __name__ == "__main__":
    unittest.main()
