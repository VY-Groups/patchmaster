#!/usr/bin/env python3
"""pm-evidence: offline verifier for Patch-SecOps Solution evidence bundles (S1-6).

Usage:
    python scripts/pm_evidence.py <bundle.json> [--policy policy.json] [--pubkey KEY]
    python scripts/pm_evidence.py --stdin < bundle.json

Exit code 0 on PASS, 1 on FAIL. Runs without network or the master.
"""

import argparse
import base64
import hashlib
import json
import sys


def _hash_payload(payload):
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def verify_bundle(bundle, policy=None, pubkey=None):
    failures = []
    warnings = []

    for f in ("bundle_hash", "item_count"):
        if f not in bundle:
            failures.append(f"missing field: {f}")
    if failures:
        return False, failures, warnings

    items = bundle.get("items", [])
    if len(items) != bundle.get("item_count", -1):
        failures.append(f"item_count mismatch: declared {bundle.get('item_count')} actual {len(items)}")

    # broken chain: previous_bundle_hash must be present when not first
    # (we can't know first-ness offline; require the field to exist)
    if "previous_bundle_hash" not in bundle:
        failures.append("missing field: previous_bundle_hash")

    for i, it in enumerate(items):
        if "payload_hash" not in it:
            failures.append(f"item {i}: missing payload_hash")
            continue
        if "payload" in it:
            recomputed = _hash_payload(it["payload"])
            if recomputed != it["payload_hash"]:
                failures.append(f"item {i}: payload_hash mismatch")

    item_hashes = [it.get("payload_hash") for it in items if it.get("payload_hash")]
    h = hashlib.sha256()
    prev = bundle.get("previous_bundle_hash")
    if prev:
        h.update(prev.encode("utf-8"))
    for ih in sorted(item_hashes):
        h.update(ih.encode("utf-8"))
    h.update(str(bundle.get("job_id") or "").encode("utf-8"))
    recomputed_bundle = h.hexdigest()
    if recomputed_bundle != bundle.get("bundle_hash"):
        failures.append(f"bundle_hash mismatch: computed {recomputed_bundle} stored {bundle.get('bundle_hash')}")

    if policy:
        required_steps = set(policy.get("required_steps", []))
        present_steps = {it.get("step") for it in items}
        missing = required_steps - present_steps
        if missing:
            failures.append(f"missing required steps: {sorted(missing)}")
        # removed-step detection: every item's step must be in policy allowed set if provided
        allowed = set(policy.get("allowed_steps", [])) if policy.get("allowed_steps") else None
        if allowed is not None:
            for it in items:
                if it.get("step") not in allowed:
                    failures.append(f"disallowed step: {it.get('step')}")

    if bundle.get("signature"):
        if pubkey:
            try:
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
                pub_raw = base64.b64decode(pubkey)
                pub = Ed25519PublicKey.from_public_bytes(pub_raw)
                sig = base64.b64decode(bundle["signature"])
                pub.verify(sig, bundle["bundle_hash"].encode("utf-8"))
                warnings.append("signature verified (Ed25519)")
            except Exception as e:
                failures.append(f"signature verification failed: {e}")
        else:
            warnings.append("signature present; pass --pubkey to verify (Ed25519)")

    return len(failures) == 0, failures, warnings


def main():
    parser = argparse.ArgumentParser(description="Verify an evidence bundle offline.")
    parser.add_argument("bundle_path", nargs="?", help="Path to bundle JSON file")
    parser.add_argument("--stdin", action="store_true", help="Read bundle from stdin")
    parser.add_argument("--policy", help="Path to policy JSON (required_steps list)")
    parser.add_argument("--pubkey", help="Base64 Ed25519 public key for signature verification")
    args = parser.parse_args()

    if args.stdin:
        bundle = json.load(sys.stdin)
    elif args.bundle_path:
        with open(args.bundle_path) as f:
            bundle = json.load(f)
    else:
        parser.error("provide a bundle path or --stdin")
        return 2

    policy = None
    if args.policy:
        with open(args.policy) as f:
            policy = json.load(f)

    ok, failures, warnings = verify_bundle(bundle, policy, pubkey=args.pubkey)
    if ok:
        print("PASS")
        for w in warnings:
            print(f"  note: {w}")
        return 0
    else:
        print("FAIL")
        for f in failures:
            print(f"  - {f}")
        for w in warnings:
            print(f"  note: {w}")
        return 1


if __name__ == "__main__":
    sys.exit(main())