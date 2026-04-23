#!/usr/bin/env python3
"""CloudClaw reference image search.

Calls shared-api/search/images (Serper under the hood) and prints a JSON
list of candidate reference images for the image skill to pick from.

Auth is injected transparently by the pod's network layer.
"""

import argparse
import json
import os
import sys

import requests

SHARED_API = os.environ.get("SHARED_API", "http://shared-api")
SEARCH_IMAGES = f"{SHARED_API}/search/images"


def main():
    ap = argparse.ArgumentParser(description="CloudClaw reference image search")
    ap.add_argument("--query", required=True)
    ap.add_argument("--limit", type=int, default=6)
    args = ap.parse_args()

    try:
        r = requests.get(
            SEARCH_IMAGES,
            params={"q": args.query, "limit": args.limit},
            timeout=30,
        )
        if r.status_code == 403:
            print(json.dumps({"status": "error", "reason": "quota_exceeded"}))
            sys.exit(2)
        r.raise_for_status()
        body = r.json()
    except requests.RequestException as e:
        print(json.dumps({"status": "error", "reason": f"provider_error: {e}"}))
        sys.exit(2)

    results = body.get("results") or body.get("images") or []
    print(json.dumps({"status": "ok", "results": results}, indent=2))


if __name__ == "__main__":
    main()
