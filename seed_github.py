"""Create a small, current-dated live GitHub sample. Dry-run unless --apply is supplied."""

import argparse
import json
import subprocess
from pathlib import Path


def api(endpoint, method="GET", payload=None):
    command = ["gh", "api", endpoint, "--method", method]
    data = None
    if payload is not None:
        command.extend(["--input", "-"])
        data = json.dumps(payload)
    result = subprocess.run(command, input=data, capture_output=True, text=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def choose_plan(dataset, limit):
    prs = dataset["pull_requests"]
    plan = [prs[index * (len(prs) - 1) // max(1, limit - 1)] for index in range(limit)]
    incident_prs = {row["pr_id"] for row in dataset["deployments"] if row["caused_incident"]}
    if incident_prs and not any(pr["id"] in incident_prs for pr in plan):
        plan[-1] = next(pr for pr in prs if pr["id"] in incident_prs)
    return plan


def seed_scenario(repo, pr, commits, state, state_path, incident=None):
    root = f"repos/{repo}"
    key = str(pr["id"])
    record = state["scenarios"].setdefault(key, {})
    branch = f"mock/change-{pr['id']}"
    if "head_sha" not in record:
        base = api(f"{root}/git/ref/heads/main")["object"]["sha"]
        base_commit = api(f"{root}/git/commits/{base}")
        tree = base_commit["tree"]["sha"]
        parent = base
        for commit in commits:
            blob = api(f"{root}/git/blobs", "POST", {
                "content": json.dumps(commit, indent=2) + "\n", "encoding": "utf-8",
            })
            new_tree = api(f"{root}/git/trees", "POST", {
                "base_tree": tree, "tree": [{
                    "path": f"samples/{pr['service']}/change-{pr['id']}.json",
                    "mode": "100644", "type": "blob", "sha": blob["sha"],
                }],
            })
            identity = {"name": f"Mock {pr['author']}",
                        "email": f"{pr['author']}@example.invalid", "date": commit["committed_at"]}
            created = api(f"{root}/git/commits", "POST", {
                "message": commit["message"], "tree": new_tree["sha"], "parents": [parent],
                "author": identity, "committer": identity,
            })
            parent, tree = created["sha"], new_tree["sha"]
        record["head_sha"] = parent
        save_state(state_path, state)
    if not record.get("branch_created"):
        existing = api(f"{root}/git/matching-refs/heads/mock/change-{pr['id']}")
        exact = [ref for ref in existing if ref["ref"] == f"refs/heads/{branch}"]
        if exact:
            if exact[0]["object"]["sha"] != record["head_sha"]:
                raise RuntimeError(f"Existing {branch} does not match this seed; refusing to overwrite")
        else:
            api(f"{root}/git/refs", "POST", {"ref": f"refs/heads/{branch}", "sha": record["head_sha"]})
        record["branch_created"] = True
        save_state(state_path, state)
    if "pr_number" not in record:
        existing = api(f"{root}/pulls?state=all&head={repo.split('/')[0]}:{branch}")
        pull = existing[0] if existing else api(f"{root}/pulls", "POST", {
            "title": f"[MOCK] {pr['title']}", "head": branch, "base": "main",
            "body": (f"Synthetic connector-test data. Historical scenario PR {pr['id']}.\n\n"
                     f"Scenario dates: {pr['created_at']} to {pr['merged_at']}.\n"
                     "GitHub PR timestamps are current, not these historical dates."),
        })
        record["pr_number"] = pull["number"]
        save_state(state_path, state)
    number = record["pr_number"]
    if not record.get("merged"):
        pull = api(f"{root}/pulls/{number}")
        if not pull["merged"]:
            response = api(f"{root}/pulls/{number}/merge", "PUT", {
                "sha": record["head_sha"], "merge_method": "merge",
            })
            if not response.get("merged"):
                raise RuntimeError(f"PR {number} was not merged")
        record["merged"] = True
        save_state(state_path, state)
    if "deployment_id" not in record:
        deployment = api(f"{root}/deployments", "POST", {
            "ref": record["head_sha"], "environment": "production", "auto_merge": False,
            "required_contexts": [], "description": f"Synthetic scenario {key}; no real deployment",
            "production_environment": True, "payload": {"mock_scenario_id": key},
        })
        record["deployment_id"] = deployment["id"]
        save_state(state_path, state)
    if not record.get("deployment_status"):
        api(f"{root}/deployments/{record['deployment_id']}/statuses", "POST", {
            "state": "success", "description": "Synthetic deployment for connector testing",
            "auto_inactive": False,
        })
        record["deployment_status"] = True
        save_state(state_path, state)
    if incident is not None:
        if "issue_number" not in record:
            title = f"[MOCK incident {key}] {incident['title']}"
            existing = api(f"{root}/issues?state=all&per_page=100&labels=mock-data,incident")
            matching = [issue for issue in existing if issue["title"] == title]
            issue = matching[0] if matching else api(f"{root}/issues", "POST", {
                "title": title, "labels": ["mock-data", "incident"],
                "body": (f"Synthetic regression associated with PR #{number}.\n\n"
                         f"Deployment ID: {record['deployment_id']}.\n"
                         f"Scenario detected: {incident['detected_at']}.\n"
                         f"Scenario restored: {incident['resolved_at']}.\n"
                         "GitHub issue timestamps are current. No real outage occurred."),
            })
            record["issue_number"] = issue["number"]
            save_state(state_path, state)
        if not record.get("issue_closed"):
            api(f"{root}/issues/{record['issue_number']}", "PATCH", {"state": "closed"})
            record["issue_closed"] = True
            save_state(state_path, state)
    if not record.get("workflow_dispatched"):
        api(f"{root}/actions/workflows/mock-ci.yml/dispatches", "POST", {
            "ref": "main", "inputs": {"scenario": key,
                                       "simulate_failure": "true" if pr["id"] % 3 == 0 else "false"},
        })
        record["workflow_dispatched"] = True
        save_state(state_path, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="benjaminmkainos/mock-delivery-metrics")
    parser.add_argument("--dataset", type=Path, default=Path("data/dataset.json"))
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--state", type=Path, default=Path(".seed-state.json"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    if not 1 <= args.limit <= len(dataset["pull_requests"]):
        parser.error("--limit must be between 1 and the number of dataset PRs")
    plan = choose_plan(dataset, args.limit)
    if not args.apply:
        print(f"DRY RUN: {args.repo}: {len(plan)} PRs, production deployment records, incident issues and CI dispatches.")
        print("Commit dates are historical. PRs, deployment records and Actions dates will be current.")
        print("Requires the repo files already published on main; no API requests made.")
        return
    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else {
        "repo": args.repo, "metadata": dataset["metadata"], "scenarios": {},
    }
    if state["repo"] != args.repo or state["metadata"] != dataset["metadata"]:
        parser.error("State belongs to a different repository or dataset; use a separate --state path")
    api(f"repos/{args.repo}/actions/workflows/mock-ci.yml")
    labels = api(f"repos/{args.repo}/labels?per_page=100")
    for name, color in (("mock-data", "0e8a16"), ("incident", "d73a4a")):
        if not any(label["name"] == name for label in labels):
            api(f"repos/{args.repo}/labels", "POST", {"name": name, "color": color})
    deployments = {row["id"]: row for row in dataset["deployments"]}
    for pr in plan:
        commits = [commit for commit in dataset["commits"] if commit["pr_id"] == pr["id"]]
        incident = next((row for row in dataset["incidents"]
                         if deployments[row["deployment_id"]]["pr_id"] == pr["id"]), None)
        seed_scenario(args.repo, pr, commits, state, args.state, incident)
        print(f"Seeded scenario {pr['id']}: PR #{state['scenarios'][str(pr['id'])]['pr_number']}")


if __name__ == "__main__":
    main()