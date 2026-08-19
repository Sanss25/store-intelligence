"""Replay a local events.jsonl file into the API.

Useful for demos (seed the dashboard without running the full CV
pipeline) and for rebuilding the DB from the durable JSONL log if
the API/SQLite store is ever wiped. Ingestion is idempotent, so
replaying an already-loaded file is a safe no-op.

Usage:
    python replay_events.py --file events.jsonl --api-url http://localhost:8000
"""
from __future__ import annotations

import argparse
import json

import requests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="events.jsonl")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    created, duplicate, failed = 0, 0, 0

    with open(args.file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            try:
                resp = requests.post(f"{args.api_url}/events/ingest", json=event, timeout=5)
                resp.raise_for_status()
                status = resp.json()["status"]
                if status == "created":
                    created += 1
                else:
                    duplicate += 1
            except requests.RequestException as exc:
                print(f"Failed to ingest {event.get('event_id')}: {exc}")
                failed += 1

    print(f"Done. created={created} duplicate={duplicate} failed={failed}")


if __name__ == "__main__":
    main()
