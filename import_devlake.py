"""Send exported payloads to per-service DevLake webhooks. Dry-run by default."""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_payload(url, token, payload):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Webhook URL must be HTTP(S)")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Use HTTPS for non-local webhook endpoints")
    request = Request(url, data=json.dumps(payload).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
    })
    with build_opener(NoRedirects()).open(request, timeout=30) as response:
        response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload-dir", type=Path, default=Path("data/devlake"))
    parser.add_argument("--service", choices=("payments", "orders", "identity"), required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    payloads = {endpoint: json.loads((args.payload_dir / f"{args.service}-{endpoint}.json").read_text(encoding="utf-8"))
                for endpoint in ("deployments", "issues")}
    print(f"{args.service}: {len(payloads['deployments'])} deployments, {len(payloads['issues'])} incidents")
    if not args.apply:
        print("DRY RUN: no requests sent. --apply requires DEVLAKE_WEBHOOK_URL and DEVLAKE_WEBHOOK_TOKEN.")
        return
    base = os.environ.get("DEVLAKE_WEBHOOK_URL", "").rstrip("/")
    token = os.environ.get("DEVLAKE_WEBHOOK_TOKEN", "")
    if not base or not token:
        parser.error("Set DEVLAKE_WEBHOOK_URL to the connection base URL and DEVLAKE_WEBHOOK_TOKEN")
    for endpoint, rows in payloads.items():
        for row in rows:
            post_payload(f"{base}/{endpoint}", token, row)
    print("Import complete. Recompute project metrics in DevLake after all service imports.")


if __name__ == "__main__":
    main()