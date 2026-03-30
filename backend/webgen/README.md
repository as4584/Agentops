# backend/webgen/ — ★ Website Generation Pillar

The full website generation pipeline: from brief → architecture → code → AEO
optimisation → review → deploy. All webgen agents and their shared base live
in `agents/` inside this folder.

## Structure

```
webgen/
  agents/            # All website generation agents (stay here)
    base_agent.py    # WebgenAgent base class
    aeo_agent.py     # AEO / answer-engine optimisation
    architect_agent.py
    code_agent.py
    review_agent.py
    seo_agent.py
    ux_agent.py
  pipeline.py        # Pipeline orchestrator for a full site build
  models.py          # Webgen-specific Pydantic models
  site_store.py      # Persists generated site records
  template_store.py  # Manages reusable site templates
```

## Conventions

- All agents extend `WebgenAgent` from `agents/base_agent.py`
- Agent IDs follow the pattern `webgen_<role>` (e.g. `webgen_aeo`)
- Webgen agents must NOT import from `backend/content/` — pipelines are separate
- Generated sites land in `output/webgen/<site-slug>/`
- Site metadata is persisted under the `webgen_projects` memory namespace

## AEO (Answer Engine Optimisation)

The `aeo_agent.py` applies structured-data, FAQ schema, and semantic heading
patterns to maximise LLM/AI search engine visibility. See `docs/aeo-future-plan.md`
for the roadmap.

## Drift anchors

- Agent registry: `docs/AGENT_REGISTRY.md`
- Webgen architecture: `docs/HYBRID_ARCHITECTURE.md`
- AEO plan: `docs/aeo-future-plan.md`
