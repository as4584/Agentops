# backend/content/ — ★ Content Creation Pillar

The full content production pipeline: from intake brief → script → voice →
video → QA → publish. All content creation agents and their shared base live here.

## What lives here (stay here — do not move to backend/agents/)

| File | Role |
|---|---|
| `base_agent.py` | `ContentAgent` base class — all content agents extend this |
| `script_writer.py` | Writes ad/marketing scripts from briefs |
| `voice_engine.py` | Text-to-speech integration |
| `video_pipeline.py` | Frame composition and video assembly |
| `analytics_agent.py` | Post-publish analytics collection |
| `qa_agent.py` | Quality assurance review |
| `publisher_agent.py` | Publishes approved content to channels |
| _(+ remaining agents)_ | See the pipeline in order below |

## Pipeline order

```
Intake → ScriptWriter → VoiceEngine → VideoGen → QA → Publisher → Analytics
```

## Conventions

- All agents in this folder extend `ContentAgent` from `base_agent.py`
- Agent IDs follow the pattern `content_<role>` (e.g. `content_qa`)
- Content agents must NOT import from `backend/webgen/` — pipelines are independent
- Shared state (cross-stage job info) uses the `content_jobs` memory namespace

## Drift anchors

- Agent registry: `docs/AGENT_REGISTRY.md`
- Content pipeline design: `docs/HYBRID_ARCHITECTURE.md`
- Known issues: `docs/KNOWN_ISSUES.md`
