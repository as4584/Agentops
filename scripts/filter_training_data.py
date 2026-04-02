#!/usr/bin/env python3
"""Filter and validate training data JSONL files.

Removes duplicates, validates schema, checks agent names, and produces
a clean combined dataset for fine-tuning.

Usage:
    python scripts/filter_training_data.py [--strict] [--output data/training/filtered.jsonl]
"""

import json
import os
import sys
from collections import Counter
from hashlib import sha256

VALID_AGENTS = {
    "soul_core",
    "devops_agent",
    "monitor_agent",
    "self_healer_agent",
    "code_review_agent",
    "security_agent",
    "data_agent",
    "comms_agent",
    "cs_agent",
    "it_agent",
    "knowledge_agent",
    "BLOCKED",
}

VALID_TOOLS = {
    "safe_shell",
    "file_reader",
    "doc_updater",
    "system_info",
    "webhook_send",
    "git_ops",
    "health_check",
    "log_tail",
    "alert_dispatch",
    "secret_scanner",
    "db_query",
    "process_restart",
}

REQUIRED_ROUTING_KEYS = {"user_message", "expected_agent"}
REQUIRED_TRAJECTORY_KEYS = {"task", "chosen_agent", "plan"}
REQUIRED_PREFERENCE_KEYS = {"task", "good_response", "bad_response"}


def detect_type(record: dict) -> str:
    if "user_message" in record and "expected_agent" in record:
        return "routing"
    if "plan" in record and "actions" in record:
        return "trajectory"
    if "good_response" in record and "bad_response" in record:
        return "preference"
    return "unknown"


def validate_routing(record: dict, strict: bool = False) -> list[str]:
    errors = []
    missing = REQUIRED_ROUTING_KEYS - set(record.keys())
    if missing:
        errors.append(f"Missing keys: {missing}")

    agent = record.get("expected_agent", "")
    if agent not in VALID_AGENTS:
        errors.append(f"Invalid agent: {agent}")

    tools = record.get("expected_tools", [])
    if strict:
        for t in tools:
            if t not in VALID_TOOLS:
                errors.append(f"Invalid tool: {t}")

    msg = record.get("user_message", "")
    if not msg or len(msg.strip()) == 0:
        errors.append("Empty user_message")

    return errors


def validate_trajectory(record: dict, strict: bool = False) -> list[str]:
    errors = []
    missing = REQUIRED_TRAJECTORY_KEYS - set(record.keys())
    if missing:
        errors.append(f"Missing keys: {missing}")

    agent = record.get("chosen_agent", "")
    if agent not in VALID_AGENTS:
        errors.append(f"Invalid agent: {agent}")

    plan = record.get("plan", [])
    if not plan or len(plan) < 2:
        errors.append("Plan must have >= 2 steps")

    return errors


def validate_preference(record: dict, strict: bool = False) -> list[str]:
    errors = []
    missing = REQUIRED_PREFERENCE_KEYS - set(record.keys())
    if missing:
        errors.append(f"Missing keys: {missing}")

    if record.get("good_response", "") == record.get("bad_response", ""):
        errors.append("good_response == bad_response")

    return errors


def content_hash(record: dict) -> str:
    """Hash by user_message or task to detect duplicates."""
    key = record.get("user_message", record.get("task", json.dumps(record, sort_keys=True)))
    return sha256(key.encode()).hexdigest()[:16]


def main():
    strict = "--strict" in sys.argv
    output = "data/training/filtered_combined.jsonl"
    for i, arg in enumerate(sys.argv):
        if arg == "--output" and i + 1 < len(sys.argv):
            output = sys.argv[i + 1]

    # Collect all JSONL files
    sources = []
    for dirpath in ["data/training", "data/dpo"]:
        if os.path.isdir(dirpath):
            for f in sorted(os.listdir(dirpath)):
                if f.endswith(".jsonl") and f != os.path.basename(output):
                    sources.append(os.path.join(dirpath, f))

    print(f"Scanning {len(sources)} JSONL files (strict={strict})")

    all_records = []
    seen_hashes = set()
    stats = Counter()

    for src in sources:
        with open(src) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as e:
                    stats["json_errors"] += 1
                    print(f"  JSON error in {src}:{line_num}: {e}")
                    continue

                rec_type = detect_type(record)
                stats[f"total_{rec_type}"] += 1

                # Validate
                if rec_type == "routing":
                    errors = validate_routing(record, strict)
                elif rec_type == "trajectory":
                    errors = validate_trajectory(record, strict)
                elif rec_type == "preference":
                    errors = validate_preference(record, strict)
                else:
                    errors = ["unknown record type"]

                if errors:
                    stats["validation_errors"] += 1
                    if strict:
                        print(f"  Rejected {src}:{line_num}: {errors}")
                    continue

                # Dedup
                h = content_hash(record)
                if h in seen_hashes:
                    stats["duplicates"] += 1
                    continue
                seen_hashes.add(h)

                record["_source"] = os.path.basename(src)
                record["_type"] = rec_type
                all_records.append(record)
                stats[f"kept_{rec_type}"] += 1

    # Write filtered output
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w") as f:
        for record in all_records:
            f.write(json.dumps(record) + "\n")

    print("\n=== Filter Results ===")
    for key, val in sorted(stats.items()):
        print(f"  {key}: {val}")
    print(f"\n  Total kept: {len(all_records)} → {output}")

    # Agent distribution
    agent_dist = Counter()
    for r in all_records:
        agent = r.get("expected_agent", r.get("chosen_agent", "unknown"))
        agent_dist[agent] += 1
    print("\n  Agent distribution:")
    for a, c in sorted(agent_dist.items(), key=lambda x: -x[1]):
        print(f"    {a}: {c}")

    return 0 if stats.get("validation_errors", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
