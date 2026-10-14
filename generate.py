"""Generate linked synthetic delivery records without modifying GitHub."""

import argparse
import csv
import hashlib
import json
import random
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import mean, median


def timestamp(value):
    return value.isoformat().replace("+00:00", "Z")


def generate(end_date, days=90, seed=42):
    if days < 1:
        raise ValueError("days must be positive")
    rng = random.Random(seed)
    start_date = end_date - timedelta(days=days - 1)
    tables = {name: [] for name in (
        "commits", "pull_requests", "reviews", "builds", "deployments", "incidents"
    )}
    sequence = 0
    for offset in range(days):
        current_date = start_date + timedelta(days=offset)
        if current_date.weekday() >= 5:
            continue
        phase = min(2, offset * 3 // days)
        for service in ("payments", "orders", "identity"):
            if rng.random() < (0.30, 0.18, 0.08)[phase]:
                continue
            sequence += 1
            pr_id = sequence
            actor = rng.choice(("alex", "blair", "casey", "devon"))
            deployed = datetime.combine(current_date, time(15, sequence % 60), timezone.utc)
            merged = deployed - timedelta(minutes=rng.randint(30, 120))
            created = merged - timedelta(hours=rng.randint(*( (24, 72), (12, 48), (4, 24) )[phase]))
            first_commit = created - timedelta(hours=rng.randint(1, 8))
            commit_count = rng.randint(2, 5)
            shas = []
            for position in range(commit_count):
                committed = first_commit + (created - first_commit) * position / commit_count
                sha = hashlib.sha1(f"mock:{seed}:{current_date}:{sequence}:{position}".encode()).hexdigest()
                shas.append(sha)
                tables["commits"].append({
                    "sha": sha, "pr_id": pr_id, "service": service, "author": actor,
                    "committed_at": timestamp(committed),
                    "message": f"feat({service}): synthetic change {sequence}.{position + 1}",
                })
            review_time = created + (merged - created) * 0.4
            reviewer = rng.choice([person for person in ("alex", "blair", "casey", "devon") if person != actor])
            tables["reviews"].append({
                "id": pr_id, "pr_id": pr_id, "service": service, "reviewer": reviewer,
                "submitted_at": timestamp(review_time), "state": "APPROVED",
            })
            tables["pull_requests"].append({
                "id": pr_id, "service": service, "author": actor,
                "title": f"Improve {service} delivery scenario {sequence}",
                "created_at": timestamp(created), "merged_at": timestamp(merged),
                "first_commit_at": timestamp(first_commit), "head_sha": shas[-1],
                "additions": rng.randint(10, 350), "deletions": rng.randint(0, 120),
                "commit_count": commit_count, "state": "merged",
            })
            failed_build = rng.random() < (0.25, 0.16, 0.08)[phase]
            for attempt in range(1, 3 if failed_build else 2):
                build_start = merged + timedelta(minutes=(attempt - 1) * 12)
                duration = rng.randint(180, 600)
                tables["builds"].append({
                    "id": len(tables["builds"]) + 1, "pr_id": pr_id,
                    "service": service, "head_sha": shas[-1], "attempt": attempt,
                    "started_at": timestamp(build_start),
                    "completed_at": timestamp(build_start + timedelta(seconds=duration)),
                    "duration_seconds": duration,
                    "conclusion": "failure" if failed_build and attempt == 1 else "success",
                })
            deployment_id = len(tables["deployments"]) + 1
            incident = rng.random() < (0.22, 0.13, 0.06)[phase]
            tables["deployments"].append({
                "id": deployment_id, "pr_id": pr_id, "service": service,
                "sha": shas[-1], "environment": "production",
                "deployed_at": timestamp(deployed), "status": "success",
                "caused_incident": incident,
                "lead_time_hours": (deployed - first_commit).total_seconds() / 3600,
            })
            if incident:
                detected = deployed + timedelta(minutes=rng.randint(5, 30))
                restored = detected + timedelta(minutes=rng.randint(*( (90, 360), (45, 180), (15, 90) )[phase]))
                tables["incidents"].append({
                    "id": len(tables["incidents"]) + 1, "deployment_id": deployment_id,
                    "service": service, "title": f"Production regression after change {pr_id}",
                    "detected_at": timestamp(detected), "resolved_at": timestamp(restored),
                    "recovery_minutes": (restored - detected).total_seconds() / 60,
                    "severity": rng.choice(("sev1", "sev2")), "state": "closed",
                })
    return {
        "metadata": {"synthetic": True, "seed": seed, "days": days,
                     "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
                     "schema_version": 1,
                     "sha_note": "Synthetic identifiers, not real Git object hashes"},
        **tables,
    }


def metrics(dataset):
    deployments = dataset["deployments"]
    incidents = dataset["incidents"]
    builds = dataset["builds"]
    prs = dataset["pull_requests"]
    return {
        "counts": {name: len(dataset[name]) for name in (
            "commits", "pull_requests", "reviews", "builds", "deployments", "incidents")},
        "deployments_per_calendar_day": len(deployments) / dataset["metadata"]["days"],
        "median_commit_to_production_hours": median([row["lead_time_hours"] for row in deployments]) if deployments else None,
        "change_failure_rate": sum(row["caused_incident"] for row in deployments) / len(deployments) if deployments else None,
        "mean_recovery_minutes": mean([row["recovery_minutes"] for row in incidents]) if incidents else None,
        "median_recovery_minutes": median([row["recovery_minutes"] for row in incidents]) if incidents else None,
        "build_success_rate": sum(row["conclusion"] == "success" for row in builds) / len(builds) if builds else None,
        "mean_build_duration_seconds": mean([row["duration_seconds"] for row in builds]) if builds else None,
        "median_pr_cycle_hours": median([
            (datetime.fromisoformat(row["merged_at"].replace("Z", "+00:00")) -
             datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))).total_seconds() / 3600
            for row in prs
        ]) if prs else None,
    }


def write_dataset(dataset, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / "dataset.json").write_text(json.dumps(dataset, indent=2) + "\n", encoding="utf-8")
    (output / "expected-metrics.json").write_text(json.dumps(metrics(dataset), indent=2) + "\n", encoding="utf-8")
    for name, rows in dataset.items():
        if name == "metadata":
            continue
        (output / f"{name}.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        with (output / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            if rows:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("data"))
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be positive")
    dataset = generate(args.end_date, args.days, args.seed)
    write_dataset(dataset, args.output)
    print(json.dumps(metrics(dataset), indent=2))


if __name__ == "__main__":
    main()