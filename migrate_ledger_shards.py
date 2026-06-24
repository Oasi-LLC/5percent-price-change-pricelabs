#!/usr/bin/env python3
"""
Migrate a monolithic adjustment ledger.json to sharded GitHub storage.

Use this once when the legacy ledger on automation-state grew past GitHub's
1 MB Contents API read limit.

Usage:
    python3 migrate_ledger_shards.py ~/Downloads/ledger.json --clear-lock
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

from pricelabs_tool.ledger_store import (
    LEDGER_VERSION,
    GitHubLedgerStore,
    empty_manifest,
    get_ledger_store,
    prune_records,
    resolve_ledger_backend,
)

load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate monolithic ledger to sharded GitHub files")
    parser.add_argument("ledger", type=Path, help="Local path to legacy ledger.json")
    parser.add_argument(
        "--clear-lock",
        action="store_true",
        help="Set lock to null in the new manifest",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print migration plan without writing to GitHub",
    )
    args = parser.parse_args()

    if resolve_ledger_backend() != "github":
        print("GITHUB_TOKEN must be set for GitHub ledger migration.")
        return 1

    with open(args.ledger) as f:
        payload = json.load(f)

    records = prune_records(payload.get("records", []))
    by_listing: dict = defaultdict(list)
    for item in records:
        listing_id = str(item.get("listing_id", ""))
        if listing_id:
            by_listing[listing_id].append(item)

    lock = None if args.clear_lock else payload.get("lock")
    manifest = empty_manifest()
    manifest["lock"] = lock

    print(f"Records to migrate: {len(records)} across {len(by_listing)} listing shard(s)")
    if lock:
        print(f"Manifest lock preserved: direction={lock.get('direction')} started={lock.get('started_at')}")
    elif args.clear_lock:
        print("Manifest lock will be cleared.")

    if args.dry_run:
        return 0

    store = get_ledger_store()
    if not isinstance(store, GitHubLedgerStore):
        print("Expected GitHub ledger store.")
        return 1

    existing_manifest, manifest_sha = store.read_manifest()
    store.write_manifest(manifest, manifest_sha)
    print(f"Wrote manifest to {store.manifest_path}")

    for listing_id, listing_records in sorted(by_listing.items()):
        _, shard_sha = store.read_listing_shard(listing_id)
        store.write_listing_shard(listing_id, listing_records, shard_sha)
        print(f"  shard {listing_id}: {len(listing_records)} record(s)")

    print("Migration complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
