#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from backend.knowledge import KnowledgeVectorStore
from backend.llm import OllamaClient


async def _run(force_rebuild: bool) -> int:
    client = OllamaClient()
    try:
        if not await client.is_available():
            print("Ollama is not reachable. Start it with: ollama serve", file=sys.stderr)
            return 1

        store = KnowledgeVectorStore(client)
        await store.ensure_index(force_rebuild=force_rebuild)
        stats = store.stats()
        print(json.dumps({"success": True, "force_rebuild": force_rebuild, **stats}, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}), file=sys.stderr)
        return 1
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed or rebuild the local knowledge vector index.")
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Force a full re-embed/rebuild even if the cached signature matches.",
    )
    args = parser.parse_args()
    return asyncio.run(_run(force_rebuild=args.force_rebuild))


if __name__ == "__main__":
    raise SystemExit(main())
