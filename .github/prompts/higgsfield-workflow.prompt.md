---
description: "Higgsfield Workflow — produce AI videos via Higgsfield.ai using the headed Chromium MCP server (port 8812). Applies to clients/probodyforlife/ and backend/mcp/higgsfield* files."
---

# Higgsfield Workflow Prompt

You are producing AI videos on **Higgsfield.ai** using a headed Chromium browser
controlled by the Higgsfield MCP server (port 8812).

## Characters registered in the DB

| character_id | Name | Image path |
|---|---|---|
| `char_xpel` | Xpel | `clients/probodyforlife/VideoGenerator/characters/Xpel/diuretic/front.png` |
| `char_mrwilly` | MrWilly | `clients/probodyforlife/VideoGenerator/characters/MrWilly/front.png` |

## 10-step production sequence (MANDATORY)

1. `hf_login` — restore or open a Higgsfield browser session
2. `db_query` — confirm `soul_id_status = 'active'` for the character
3. If NOT active → `hf_create_soul_id` → confirm active before continuing
4. `hf_navigate /create` — open the video creation UI
5. `hf_log_evidence` (label=`pre_submit`) — screenshot before anything changes
6. `hf_submit_video` — fill model / prompt / duration / character and queue the job
7. `hf_log_evidence` (label=`post_submit`) — screenshot right after queue
8. `hf_poll_result` — wait for video to complete (15 min timeout)
9. On failure → `hf_log_evidence` (label=`failure`) + write RAG entry + alert_dispatch
10. On success → return `result_url`, log to cost tracker

## Hard rules (never break)

- NEVER navigate to `/pricing`, `/billing`, `/checkout`, `/upgrade`, `/subscribe`, `/payment`, `/plans`, `/buy`, `/credit`
- NEVER submit video if Soul ID status != `active` — create it first
- ALWAYS screenshot before AND after submission (steps 5+7)
- ALWAYS log failures immediately — the research agent reads them
- You have ZERO authority to purchase anything

## Available models on Higgsfield

| Model key | Best for | Duration |
|---|---|---|
| `kling_3_0` | Motion, character interaction | 5-10s |
| `kling_2_6` | Budget motion shots | 5s |
| `veo_3_1` | Cinematic quality, audio | 8s |
| `hailuo_02` | Static beauty shots | 3-4s max |
| `sora_2` | Complex scenes | 5-20s |
| `wan_2_6` | Fast/cheap test clips | 3-5s |

## Starting the MCP server

```bash
cd /root/studio/testing/Agentop
source .venv/bin/activate
python -m backend.mcp.higgsfield_playwright_server
# Server starts on port 8812 (headed Chromium)
```

## Checking character status

```bash
curl http://localhost:8000/api/higgsfield/characters | python -m json.tool
```

## Evidence + RAG logs location

- Screenshots: `data/higgsfield/evidence/<character_id>/`
- RAG corpus: `data/higgsfield/rag_corpus/`
- Session cookies: `data/higgsfield/.session_cookies.json` (gitignored)
