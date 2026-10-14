# Mock Delivery Metrics

Reproducible synthetic delivery history for Apache DevLake and Power BI tests.
The checked-in dataset covers **90 calendar days, July 16 to October 13, 2026**.
It represents three services: payments, orders and identity, with four fictitious
contributors. Delivery becomes faster and more reliable across three 30-day phases.
Weekends have no deployments. All timestamps are UTC.

## Two distinct data sources

1. **Historical fixtures:** linked commits, PRs, reviews, builds, deployments and
   incidents in `data/`, in JSON and CSV. These are synthetic records, not GitHub
   objects. Power BI can fetch them through GitHub's Contents API using a PAT.
   DevLake does not automatically collect these files through its GitHub plugin.
2. **Live GitHub sample:** `seed_github.py` creates backdated Git commits, real PRs,
   deployment records, incident issues and Actions runs. GitHub assigns current
   dates to everything except the Git commits. This tests authentication and
   native connector behavior, not historical PR or CI trends.

GitHub's normal APIs cannot backdate PR creation/merges, reviews, issues,
deployment records or Actions runs. Historical dates in a PR body do not change
the dates seen by a collector. Fixture SHA values are synthetic identifiers and
do not correspond to the actual SHA values created by the live seeder.

## Generate and test

Python 3.9+ and GitHub CLI (`gh`) for live seeding. Python scripts use only the
standard library; no pip dependencies are required.

```sh
python3 -m unittest discover -s tests -v
python3 generate.py --end-date 2026-10-13 --days 90 --seed 42
python3 devlake_webhooks.py
python3 seed_github.py
```

Without `--end-date`, generation ends yesterday. Reusing the date and seed gives
identical output. Generation overwrites the files in the selected output directory.
PR creation and first commits can precede the deployment window by several days;
the 90-day window is defined by production deployment dates.

## Expected metrics

`data/expected-metrics.json` provides exact values for this snapshot:

| Metric | Expected |
| --- | ---: |
| Commits / merged PRs / reviews | 568 / 160 / 160 |
| Build attempts / production deployments / incidents | 184 / 160 / 18 |
| Deployments per calendar day | 1.778 |
| Median first-commit-to-production lead time | 29.8 hours |
| Change failure rate | 11.25% |
| Mean recovery time | 149.17 minutes |
| Median recovery time | 133 minutes |
| Build success rate, including retries | 86.96% |
| Mean build duration | 390.22 seconds |
| Median PR creation-to-merge cycle time | 23 hours |

Each PR has one production deployment and one approval by another synthetic
contributor. Failed builds retry successfully. A change failure means a successful
production deployment subsequently caused an incident, not that CI failed.
Recovery is measured from incident detection to resolution. Deployment frequency
here is count / calendar days, not DevLake's deployment-days-per-week definition.
DevLake uses median recovery time; do not compare that panel against the mean.
All PRs and incidents are closed: this snapshot does not test WIP or aging backlog.

## Power BI via a GitHub PAT

Use `powerbi/GitHubDataset.pq` as a blank-query function, then invoke it with owner
`benjaminmkainos`, repository `mock-delivery-metrics`, branch `main`, and a token
parameter. This reads `data/dataset.json` via the real GitHub Contents API, not
native PR/Actions endpoints. The files must first be published to GitHub.

For a fine-grained read-only PAT, select this repository and grant **Contents:
read** and **Metadata: read**. Native connector testing also needs appropriate
Actions, Pull requests, Issues and Deployments read permissions. Confirm the
permissions supported by your installed DevLake version.

Set the Web connector's authentication to **Anonymous** for this query because
the Authorization header is supplied by M. Treat the token parameter and any PBIX
containing it as secrets: ordinary Power Query parameters are not a secure vault.
For shared production dashboards use an approved credential-aware connector or
gateway. Never commit tokens or token-filled queries.

The function returns a record of tables. Create reference queries such as
`= DeliveryData[deployments]` and `= DeliveryData[pull_requests]`. Explicitly set
timestamp columns to Date/Time/Timezone, IDs to whole numbers, metric columns to
decimal numbers, and `caused_incident` to logical before creating relationships:

- PR `id` -> commits/reviews/builds/deployments `pr_id`.
- Deployment `id` -> incidents `deployment_id`.
- Date dimension -> deployment date for DORA trends, build date for CI trends.

The existing dashboard's endpoints are currently unknown. If it reads native
`/pulls`, `/issues` or `/actions/runs`, this query requires a separate test copy
or adapter; the files will not appear as native records automatically.

## Historical DevLake ingestion

`data/devlake/` contains payloads using the documented Incoming Webhook schema.
Create a separate webhook scope and test project **per service** in DevLake.
Do not put all three service scopes in one DORA project: DevLake associates an
incident with the latest prior deployment in the project, regardless of service.
Aggregate the three isolated service results externally if needed.

For each service, set `DEVLAKE_WEBHOOK_URL` to the generated connection base URL,
for example `https://devlake.example/api/rest/plugins/webhook/1`, and set
`DEVLAKE_WEBHOOK_TOKEN` privately in your terminal to that connection's API key.
Do not append `/deployments` or `/issues`; the importer does that itself.

```sh
python3 import_devlake.py --service payments
python3 import_devlake.py --service payments --apply
```

Repeat for orders and identity with their respective connection URLs and keys.
The first command is a dry-run. Apply posts deployments first, then incidents.
HTTPS is required except for localhost; requests have a 30-second timeout and
redirects are refused to avoid forwarding credentials. Stable IDs allow DevLake
to identify repeated records, but verify upsert behavior in your installed version
before re-importing; stop and inspect a partial failure rather than blindly retry.

Configure each project to include its webhook scope and recalculate/retransform
project metrics after import. Avoid mixing the live GitHub sample into these
historical test projects, which would change the counts and incident mappings.
Webhook ingestion has not yet been tested against your running DevLake version.

**Supported by these webhook payloads:** historical deployment frequency, change
failure rate and recovery time. **Not covered:** historical PR lead time, reviews
or CI build history. Synthetic commit SHAs have no matching collected GitHub
commits/PRs, so deployment webhooks alone cannot produce valid PR-based lead time.
The webhook's generic Lead Time support does not remove that dependency.

For all four historical DORA panels, the sibling `mock-data-work` project already
provides `generate_mock_devlake_data.py` and a DevLake database loader. That route
bypasses collection and needs a disposable database, version-compatible tables,
and correctly aligned project/scope IDs. It is separate from this dataset and its
expected values. Full historical PR/CI collector testing requires a compatible
mock source or a purpose-built, version-specific import, not a live GitHub PAT.

## Live GitHub connector sample

First publish these files on `main`, including `.github/workflows/mock-ci.yml`.
Authenticate `gh` privately (`gh auth login` or an existing `GH_TOKEN` environment
variable). Do not paste a PAT into chat. A write-capable fine-grained PAT needs
Contents, Pull requests, Issues, Actions and Deployments read/write permissions
on this repo. Publishing the workflow may also need Workflows write permission.

```sh
python3 seed_github.py --limit 6
python3 seed_github.py --limit 6 --apply
```

The seeder samples scenarios across the window and includes an incident example.
It creates `mock/change-*` branches through GitHub's Git Database API, merges
sample PRs, records synthetic production deployments, closes incident issues,
and dispatches inexpensive CI runs (every third scenario intentionally fails).
There is no actual application deployment. Deployment records and CI simulations
are independent test events, not evidence that a failed build reached production.
No attempt is made to fabricate reviews: GitHub cannot approve your own PR from
the same account. Native review testing needs a separate reviewer identity.

`--limit 160` can publish every scenario's backdated commits, but all PR and
workflow timestamps will still be current and API/Actions usage will increase.
The API can rate-limit bulk writes; start with the six-scenario smoke test.
The script stops on API errors and does not bypass branch protection or force-push.
Protecting `main` may prevent the scripted merges.

Local `.seed-state.json` checkpoints successful operations and is gitignored.
Preserve it for reruns. Branches and PRs are checked before creation, but a network
failure between a successful deployment/dispatch request and saving its checkpoint
can still produce duplicates on retry. Inspect GitHub before resuming after errors.
Do not delete the state and rerun blindly. This script never deletes remote objects.

## References

- [GitHub PR creation parameters](https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request)
- [GitHub workflow runs](https://docs.github.com/en/rest/actions/workflow-runs)
- [DevLake Incoming Webhooks](https://devlake.apache.org/docs/Plugins/webhook/)
- [DevLake GitHub plugin](https://devlake.apache.org/docs/Plugins/github/)