#!/usr/bin/env python3
"""
continue_ml — WebGen critique-regen-train loop.
================================================
Loads the most recent completed WebGen project, scores all pages,
re-generates pages below the UX threshold with critique injected,
writes DPO training pairs, and saves a new gallery iteration.

Usage:
    python -m cli.continue_ml                          # latest project, 2 rounds, threshold 75
    python -m cli.continue_ml --rounds 3 --threshold 70
    python -m cli.continue_ml --project d50def3b91e0
    python -m cli.continue_ml --gallery                # show gallery and exit

Supervise: run → review generated pages → edit prompts → run again.
Each run writes DPO data and increments the gallery version.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.llm import OllamaClient
from backend.webgen.agents.design_advisor import DesignAdvisorAgent
from backend.webgen.agents.page_generator import PageGeneratorAgent
from backend.webgen.agents.ux_scorer import score_html
from backend.webgen.gallery import list_gallery, save_iteration
from backend.webgen.site_store import SiteStore
from backend.webgen.template_store import TemplateStore

# ── Display helpers ─────────────────────────────────────────────────────────


def _bar(score: int, width: int = 12) -> str:
    filled = round(score / 100 * width)
    color = "\033[92m" if score >= 75 else "\033[93m" if score >= 55 else "\033[91m"
    return f"{color}{'█' * filled}{'░' * (width - filled)}\033[0m"


def print_gallery() -> None:
    items = list_gallery()
    if not items:
        print("  Gallery is empty — run the WebGen pipeline first to generate a site.")
        return
    print(f"\n  {'━' * 64}")
    print("   WebGen Gallery — All Iterations")
    print(f"  {'━' * 64}")
    for item in items[:20]:
        avg = item.get("avg_ux_score", 0)
        scores = item.get("ux_scores", {})
        low = sum(1 for s in scores.values() if s < 75)
        print(
            f"  v{item['version']:>2}  {_bar(avg)} {avg:>3}/100  "
            f"{item['business_slug']:<30}  [{item['model']}]  "
            f"{item['timestamp'][:10]}  ({low} pages need work)"
        )
    print(f"  {'━' * 64}\n")


def print_scores(ux_scores: dict[str, int], label: str = "Current scores") -> None:
    if not ux_scores:
        return
    avg = sum(ux_scores.values()) // len(ux_scores)
    print(f"\n  {label} (avg {avg}/100):")
    for slug, score in sorted(ux_scores.items(), key=lambda x: x[1]):
        marker = " ✗" if score < 75 else " ✓"
        print(f"    {_bar(score, 10)} {score:>3}/100  {slug}{marker}")


# ── Core loop ────────────────────────────────────────────────────────────────


async def run_critique_regen(
    project_id: str | None,
    rounds: int,
    threshold: int,
) -> None:
    store = SiteStore()
    projects = store.list_projects()

    if not projects:
        print("  No projects found. Run the WebGen pipeline first via the frontend or API.")
        return

    # Select project
    if project_id:
        project = next((p for p in projects if p.id.startswith(project_id)), None)
        if not project:
            print(f"  Project '{project_id}' not found. Available IDs:")
            for p in projects[-5:]:
                print(f"    {p.id}  {p.brief.business_name}  ({p.status.value})")
            return
    else:
        ready = [p for p in projects if "READY" in str(p.status)]
        project = ready[-1] if ready else projects[-1]

    print(f"\n  {'═' * 64}")
    print("   continue_ml")
    print(f"  {'═' * 64}")
    print(f"  Project  : {project.brief.business_name}  [{project.id}]")
    print(f"  Status   : {project.status.value}")
    print(f"  Rounds   : {rounds}  |  Threshold: {threshold}/100")
    print(f"  {'═' * 64}")

    llm = OllamaClient()
    template_store = TemplateStore()
    generator = PageGeneratorAgent(llm, template_store)
    design_advisor = DesignAdvisorAgent()
    design_ctx = design_advisor.advise(project.brief)
    generator.design_ctx = design_ctx

    nav_items = [
        {"label": p.nav_label, "href": f"{p.slug}.html"} for p in sorted(project.pages, key=lambda p: p.nav_order)
    ]

    # Score any pages that aren't scored yet
    ux_scores: dict[str, int] = dict(project.metadata.get("ux_scores", {}))
    for page in project.pages:
        if page.html and page.slug not in ux_scores:
            ux_scores[page.slug] = score_html(page.html).total
    project.metadata["ux_scores"] = ux_scores

    print_scores(ux_scores, "Scores before regen")

    all_dpo_pairs: list[dict] = []

    for round_num in range(1, rounds + 1):
        low_pages = [p for p in project.pages if ux_scores.get(p.slug, 100) < threshold]
        if not low_pages:
            print(f"\n  ✓ Round {round_num}: all pages at or above {threshold}. Done early.")
            break

        print(f"\n  ──── Round {round_num}/{rounds} ─── {len(low_pages)} page(s) to regen ────")

        for page in low_pages:
            old_score = ux_scores.get(page.slug, 0)
            old_html = page.html or ""
            violations = [e for e in project.errors if f"[{page.slug}]" in e]
            ux_prev = score_html(old_html)
            violations += [f"ux: {v}" for v in ux_prev.violations]

            print(f"  ↻  [{page.slug}] score={old_score}  violations={len(violations)}")
            for v in ux_prev.violations[:4]:
                print(f"       - {v}")

            page.html = await generator._regenerate_with_critique(
                page, project.brief, nav_items, project.global_css or "", violations
            )
            new_score = score_html(page.html).total
            ux_scores[page.slug] = new_score
            delta = new_score - old_score
            arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
            print(f"     {arrow} {old_score} → {new_score}  ({delta:+d})")

            if new_score > old_score:
                all_dpo_pairs.append(
                    {
                        "task": f"generate HTML page '{page.slug}' for {project.brief.business_type.value}",
                        "page_slug": page.slug,
                        "business_name": project.brief.business_name,
                        "model": str(getattr(llm, "model", "local")),
                        "bad_html": old_html,
                        "bad_score": old_score,
                        "good_html": page.html,
                        "good_score": new_score,
                        "violations_fixed": ux_prev.violations,
                        "category": "webgen_critique_regen",
                        "timestamp": datetime.now(tz=UTC).isoformat(),
                    }
                )

        project.metadata["ux_scores"] = ux_scores
        store.save(project)

    print_scores(ux_scores, "Scores after regen")

    # Write updated HTML to disk
    output_dir = Path(project.output_dir)
    if output_dir.exists():
        updated = 0
        for page in project.pages:
            if page.html:
                (output_dir / f"{page.slug}.html").write_text(page.html)
                updated += 1
        print(f"\n  ✓ Wrote {updated} page(s) to {output_dir}")

    # Write DPO pairs
    if all_dpo_pairs:
        ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        dpo_path = PROJECT_ROOT / "data" / "dpo" / f"webgen_critique_dpo_{ts}.jsonl"
        dpo_path.parent.mkdir(parents=True, exist_ok=True)
        with dpo_path.open("w") as f:
            for pair in all_dpo_pairs:
                f.write(json.dumps(pair) + "\n")
        print(f"  ✓ Wrote {len(all_dpo_pairs)} DPO pairs → data/dpo/{dpo_path.name}")
    else:
        print("  — No improvements detected this run; no DPO pairs written.")

    # Save gallery iteration
    model_name = str(getattr(llm, "model", "local"))
    slug = project.brief.business_name.lower().replace(" ", "-").replace("'", "")
    gallery_path = save_iteration(
        output_dir=project.output_dir,
        business_slug=slug,
        model_name=model_name,
        ux_scores=ux_scores,
        design_style=project.metadata.get("design_context", {}).get("style_name", ""),
        notes=f"continue_ml — {rounds} round(s), threshold={threshold}",
    )
    avg_final = sum(ux_scores.values()) // len(ux_scores) if ux_scores else 0
    print(f"  ✓ Gallery saved: {gallery_path.name}  (avg {avg_final}/100)")

    print_gallery()


# ── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="continue_ml: WebGen critique-regen-train loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--project", "-p", default=None, help="Project ID prefix (default: latest READY)")
    parser.add_argument("--rounds", "-r", type=int, default=2, help="Regen rounds (default: 2)")
    parser.add_argument("--threshold", "-t", type=int, default=70, help="Min UX score to skip page (default: 70)")
    parser.add_argument("--gallery", "-g", action="store_true", help="Show gallery and exit")
    args = parser.parse_args()

    if args.gallery:
        print_gallery()
        return

    asyncio.run(run_critique_regen(args.project, args.rounds, args.threshold))


if __name__ == "__main__":
    main()
