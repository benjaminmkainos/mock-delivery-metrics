import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from devlake_webhooks import export_payloads
from generate import generate
from import_devlake import post_payload
from seed_github import choose_plan, seed_scenario


class IntegrationTests(unittest.TestCase):
    def test_sample_includes_incident_and_spans_window(self):
        dataset = generate(date(2026, 10, 13))
        plan = choose_plan(dataset, 6)
        self.assertEqual(len({pr["id"] for pr in plan}), 6)
        incident_prs = {row["pr_id"] for row in dataset["deployments"] if row["caused_incident"]}
        self.assertTrue(any(pr["id"] in incident_prs for pr in plan))
        self.assertGreaterEqual(len({pr["merged_at"][:7] for pr in plan}), 3)

    def test_import_rejects_remote_cleartext(self):
        with self.assertRaises(ValueError):
            post_payload("http://example.com/webhook", "test-token", {})

    def test_live_incident_creation_and_close(self):
        dataset = generate(date(2026, 10, 13))
        pr = dataset["pull_requests"][0]
        state = {"scenarios": {str(pr["id"]): {
            "head_sha": "actual-sha", "branch_created": True, "pr_number": 1,
            "merged": True, "deployment_id": 1, "deployment_status": True,
            "workflow_dispatched": True,
        }}}
        with tempfile.TemporaryDirectory() as directory:
            with patch("seed_github.api", side_effect=[[], {"number": 9}, {}]) as request:
                seed_scenario("example/mock", pr, [], state, Path(directory) / "state.json",
                              dataset["incidents"][0])
            self.assertEqual(request.call_args_list[1].args[1], "POST")
            self.assertEqual(request.call_args_list[2].args[1:], ("PATCH", {"state": "closed"}))
        self.assertTrue(state["scenarios"][str(pr["id"])]["issue_closed"])

    def test_webhook_scope_and_fields(self):
        dataset = generate(date(2026, 10, 13))
        groups = export_payloads(dataset, "https://github.com/example/mock")
        self.assertEqual(set(groups), {"payments", "orders", "identity"})
        self.assertEqual(sum(len(group["deployments"]) for group in groups.values()),
                         len(dataset["deployments"]))
        ids = []
        for group in groups.values():
            for deployment in group["deployments"]:
                ids.append(deployment["id"])
                self.assertLess(deployment["startedDate"], deployment["finishedDate"])
                self.assertEqual(deployment["environment"], "PRODUCTION")
                self.assertEqual(deployment["deploymentCommits"][0]["repoUrl"],
                                 "https://github.com/example/mock")
            for issue in group["issues"]:
                self.assertEqual(issue["status"], "DONE")
                self.assertEqual(issue["type"], "INCIDENT")
                self.assertLess(issue["createdDate"], issue["resolutionDate"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_dry_run_needs_no_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.json"
            path.write_text(json.dumps(generate(date(2026, 10, 13))), encoding="utf-8")
            result = subprocess.run([sys.executable, "seed_github.py", "--dataset", str(path)],
                                    capture_output=True, text=True, check=True)
            self.assertIn("DRY RUN", result.stdout)
            self.assertIn("no API requests", result.stdout)

    def test_completed_scenario_is_not_replayed(self):
        dataset = generate(date(2026, 10, 13))
        pr = dataset["pull_requests"][0]
        state = {"scenarios": {str(pr["id"]): {
            "head_sha": "actual-sha", "branch_created": True, "pr_number": 1,
            "merged": True, "deployment_id": 1, "deployment_status": True,
            "workflow_dispatched": True,
        }}}
        with patch("seed_github.api") as request:
            seed_scenario("example/mock", pr, [], state, Path("unused.json"))
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()