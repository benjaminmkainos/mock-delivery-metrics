"""Export historical payloads for DevLake Incoming Webhooks, grouped by service."""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path


def export_payloads(dataset, repo_url):
    groups = {}
    prefix = f"mock-{dataset['metadata']['seed']}-{dataset['metadata']['start_date']}"
    for deployment in dataset["deployments"]:
        service = deployment["service"]
        group = groups.setdefault(service, {"deployments": [], "issues": []})
        finished = deployment["deployed_at"]
        started = (datetime.fromisoformat(finished.replace("Z", "+00:00")) -
                   timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        group["deployments"].append({
            "id": f"{prefix}-deployment-{deployment['id']}",
            "createdDate": started, "startedDate": started, "finishedDate": finished,
            "environment": "PRODUCTION", "result": "SUCCESS",
            "displayTitle": f"Synthetic {service} deployment {deployment['id']}",
            "deploymentCommits": [{
                "repoUrl": repo_url, "refName": "main", "commitSha": deployment["sha"],
                "startedDate": started, "finishedDate": finished, "result": "SUCCESS",
            }],
        })
    for incident in dataset["incidents"]:
        groups[incident["service"]]["issues"].append({
            "issueKey": f"{prefix}-incident-{incident['id']}",
            "title": incident["title"], "type": "INCIDENT", "status": "DONE",
            "originalStatus": "closed", "createdDate": incident["detected_at"],
            "updatedDate": incident["resolved_at"], "resolutionDate": incident["resolved_at"],
            "severity": incident["severity"], "component": incident["service"],
            "description": f"Synthetic incident linked to deployment {incident['deployment_id']}",
        })
    return groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/dataset.json"))
    parser.add_argument("--repo-url", default="https://github.com/benjaminmkainos/mock-delivery-metrics")
    parser.add_argument("--output", type=Path, default=Path("data/devlake"))
    args = parser.parse_args()
    groups = export_payloads(json.loads(args.dataset.read_text(encoding="utf-8")), args.repo_url)
    args.output.mkdir(parents=True, exist_ok=True)
    for service, payloads in groups.items():
        for endpoint, rows in payloads.items():
            destination = args.output / f"{service}-{endpoint}.json"
            destination.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(groups)} service scopes to {args.output}; no requests sent.")


if __name__ == "__main__":
    main()