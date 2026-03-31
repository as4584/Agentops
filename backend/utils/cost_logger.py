"""
cost_logger.py — AI Video Generation Cost Tracker

Call log_generation() after every model API call to record spend
and write a receipt. Totals are accumulated in cost_tracker.json.

Usage from any script:
    from backend.utils.cost_logger import log_generation

    log_generation(
        model="kling_v1_6_pro",
        endpoint="fal-ai/kling-video/v1.6/pro/image-to-video",
        clips=7,
        seconds_per_clip=5,
        campaign="xpel_ad",
        output_files=["scene_01.mp4", "scene_02.mp4"],
        prompts=["Close up, man raises fist...", "..."],
        notes="Scene 1-7 first pass"
    )

Or run directly from terminal to log a quick manual entry:
    python -m backend.utils.cost_logger \
        --model kling_v1_6_pro \
        --clips 7 \
        --seconds 5 \
        --campaign xpel_ad
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKER_PATH = REPO_ROOT / "animation_salvage_lab" / "07_docs" / "cost_tracker.json"
RECEIPTS_DIR = REPO_ROOT / "animation_salvage_lab" / "07_docs" / "receipts"

# ── Model cost table (USD per second of output) ────────────────────────────────
COST_PER_SECOND: dict[str, float] = {
    "hailuo": 0.018,
    "kling_v1_standard": 0.013,
    "kling_v1_6_pro": 0.023,
    "kling_v2_master": 0.042,
    "veo3_1_fast": 0.022,
    "veo3_1_standard": 0.350,
    "runway_gen2": 0.017,
    "other": 0.020,
}


def _load_tracker() -> dict:
    with open(TRACKER_PATH) as f:
        return json.load(f)


def _save_tracker(data: dict) -> None:
    with open(TRACKER_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _write_receipt(receipt: dict) -> Path:
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = receipt["timestamp"].replace(":", "-").replace(".", "-")
    filename = f"receipt_{ts}_{receipt['model']}_{receipt['campaign']}.json"
    path = RECEIPTS_DIR / filename
    with open(path, "w") as f:
        json.dump(receipt, f, indent=2)
    return path


def log_generation(
    model: str,
    clips: int,
    seconds_per_clip: float,
    campaign: str,
    endpoint: str = "",
    output_files: list[str] | None = None,
    prompts: list[str] | None = None,
    notes: str = "",
    cost_override_usd: float | None = None,
) -> dict:
    """
    Log a generation run, write a receipt, and update cost_tracker.json.

    Returns the receipt dict.
    """
    model_key = model if model in COST_PER_SECOND else "other"
    cost_per_second = COST_PER_SECOND[model_key]
    total_seconds = clips * seconds_per_clip
    total_cost = cost_override_usd if cost_override_usd is not None else round(total_seconds * cost_per_second, 4)

    timestamp = datetime.now(UTC).isoformat()
    receipt_id = f"{timestamp[:19].replace(':', '').replace('-', '')}_{model_key}"

    receipt = {
        "receipt_id": receipt_id,
        "timestamp": timestamp,
        "campaign": campaign,
        "model": model_key,
        "endpoint": endpoint,
        "clips_generated": clips,
        "seconds_per_clip": seconds_per_clip,
        "total_seconds_generated": total_seconds,
        "cost_per_second_usd": cost_per_second,
        "total_cost_usd": total_cost,
        "output_files": output_files or [],
        "prompts": prompts or [],
        "notes": notes,
    }

    # Write receipt file
    receipt_path = _write_receipt(receipt)
    receipt["receipt_file"] = str(receipt_path.relative_to(REPO_ROOT))

    # Update tracker
    tracker = _load_tracker()
    tracker["totals"]["all_time_spent_usd"] = round(tracker["totals"]["all_time_spent_usd"] + total_cost, 4)
    tracker["totals"]["all_time_clips_generated"] += clips
    tracker["totals"]["all_time_seconds_generated"] = round(
        tracker["totals"]["all_time_seconds_generated"] + total_seconds, 2
    )
    tracker["totals"]["all_time_seconds_generated"] = round(
        tracker["totals"].get("all_time_seconds_generated", 0) + total_seconds, 2
    )

    if model_key not in tracker["by_model"]:
        tracker["by_model"][model_key] = {"total_spent_usd": 0, "total_clips": 0, "total_seconds": 0}

    tracker["by_model"][model_key]["total_spent_usd"] = round(
        tracker["by_model"][model_key]["total_spent_usd"] + total_cost, 4
    )
    tracker["by_model"][model_key]["total_clips"] += clips
    tracker["by_model"][model_key]["total_seconds"] = round(
        tracker["by_model"][model_key]["total_seconds"] + total_seconds, 2
    )

    tracker["meta"]["last_updated"] = timestamp
    tracker["sessions"].append(
        {
            "receipt_id": receipt_id,
            "timestamp": timestamp,
            "campaign": campaign,
            "model": model_key,
            "clips": clips,
            "total_seconds": total_seconds,
            "cost_usd": total_cost,
            "receipt_file": receipt["receipt_file"],
        }
    )

    _save_tracker(tracker)

    # Print receipt to console
    print("\n" + "=" * 52)
    print("  GENERATION RECEIPT")
    print("=" * 52)
    print(f"  Receipt ID  : {receipt_id}")
    print(f"  Timestamp   : {timestamp[:19].replace('T', ' ')} UTC")
    print(f"  Campaign    : {campaign}")
    print(f"  Model       : {model_key}")
    if endpoint:
        print(f"  Endpoint    : {endpoint}")
    print(f"  Clips       : {clips} × {seconds_per_clip}s = {total_seconds}s total")
    print(f"  Rate        : ${cost_per_second}/sec")
    print(f"  This run    : ${total_cost:.4f}")
    print(f"  All-time    : ${tracker['totals']['all_time_spent_usd']:.4f}")
    print(f"  Receipt     : {receipt['receipt_file']}")
    if notes:
        print(f"  Notes       : {notes}")
    print("=" * 52 + "\n")

    return receipt


def print_summary() -> None:
    """Print a summary of all spend from cost_tracker.json."""
    tracker = _load_tracker()
    totals = tracker["totals"]
    print("\n" + "=" * 52)
    print("  COST TRACKER SUMMARY")
    print("=" * 52)
    print(f"  All-time spend  : ${totals['all_time_spent_usd']:.4f}")
    print(f"  Pre-tracker     : ${tracker['notes']['pre_tracker_spend_usd']:.2f} (estimated)")
    print(f"  Total clips     : {totals['all_time_clips_generated']}")
    print(f"  Total seconds   : {totals['all_time_seconds_generated']}s")
    print(f"  Sessions logged : {len(tracker['sessions'])}")
    print("-" * 52)
    print("  BY MODEL")
    for model, data in tracker["by_model"].items():
        if data["total_clips"] > 0:
            print(f"  {model:<22} ${data['total_spent_usd']:.4f}  ({data['total_clips']} clips)")
    print("=" * 52 + "\n")


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Log a video generation cost entry.")
    parser.add_argument("--model", required=False, help="Model key (e.g. kling_v1_6_pro)")
    parser.add_argument("--clips", type=int, default=0)
    parser.add_argument("--seconds", type=float, default=5.0, help="Seconds per clip")
    parser.add_argument("--campaign", default="unknown")
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--summary", action="store_true", help="Print summary and exit")

    args = parser.parse_args()

    if args.summary:
        print_summary()
        sys.exit(0)

    if not args.model:
        print("Error: --model is required unless using --summary")
        sys.exit(1)

    log_generation(
        model=args.model,
        clips=args.clips,
        seconds_per_clip=args.seconds,
        campaign=args.campaign,
        endpoint=args.endpoint,
        notes=args.notes,
    )
