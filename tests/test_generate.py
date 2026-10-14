import unittest
from datetime import date, datetime

from generate import generate, metrics


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.dataset = generate(date(2026, 10, 13))

    def test_reproducible_window(self):
        self.assertEqual(self.dataset, generate(date(2026, 10, 13)))
        self.assertEqual(self.dataset["metadata"]["start_date"], "2026-07-16")
        dates = {row["deployed_at"][:10] for row in self.dataset["deployments"]}
        self.assertTrue(all("2026-07-16" <= day <= "2026-10-13" for day in dates))
        self.assertEqual({day[:7] for day in dates}, {"2026-07", "2026-08", "2026-09", "2026-10"})

    def test_relationships_and_chronology(self):
        prs = {row["id"]: row for row in self.dataset["pull_requests"]}
        deployments = {row["id"]: row for row in self.dataset["deployments"]}
        for row in self.dataset["deployments"]:
            pr = prs[row["pr_id"]]
            self.assertLess(pr["first_commit_at"], pr["created_at"])
            self.assertLess(pr["created_at"], pr["merged_at"])
            self.assertLess(pr["merged_at"], row["deployed_at"])
            self.assertEqual(pr["head_sha"], row["sha"])
            for build in self.dataset["builds"]:
                if build["pr_id"] == row["pr_id"]:
                    self.assertLess(build["completed_at"], row["deployed_at"])
        for row in self.dataset["incidents"]:
            deployment = deployments[row["deployment_id"]]
            self.assertTrue(deployment["caused_incident"])
            self.assertLess(deployment["deployed_at"], row["detected_at"])
            self.assertLess(row["detected_at"], row["resolved_at"])
            datetime.fromisoformat(row["resolved_at"].replace("Z", "+00:00"))

    def test_metric_denominators(self):
        result = metrics(self.dataset)
        self.assertEqual(result["change_failure_rate"],
                         len(self.dataset["incidents"]) / len(self.dataset["deployments"]))
        self.assertGreater(result["build_success_rate"], 0)
        self.assertLess(result["build_success_rate"], 1)
        self.assertGreater(result["mean_recovery_minutes"], 0)

    def test_empty_and_invalid_windows(self):
        weekend = generate(date(2026, 10, 11), days=1)
        self.assertIsNone(metrics(weekend)["change_failure_rate"])
        with self.assertRaises(ValueError):
            generate(date(2026, 10, 13), days=0)


if __name__ == "__main__":
    unittest.main()