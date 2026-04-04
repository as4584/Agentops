# DRIFT GUARD — Agentop Multi-Agent System

> This document defines the architectural invariants, system boundaries,
> prohibited patterns, and rules that prevent architectural drift.
> Violations trigger CRITICAL_DRIFT_EVENT and halt execution.

---

## 1. Architectural Invariants

These invariants MUST hold at all times. Violation halts execution.

| ID    | Invariant                                              | Severity |
|-------|--------------------------------------------------------|----------|
| INV-1 | LLM layer must not depend on frontend                  | CRITICAL |
| INV-2 | Agents must not directly call each other                | CRITICAL |
| INV-3 | Tools cannot register new tools dynamically             | CRITICAL |
| INV-4 | Memory namespaces must not overlap                      | CRITICAL |
| INV-5 | Documentation must precede mutation                     | CRITICAL |
| INV-6 | No agent may modify its own registry entry directly     | HIGH     |
| INV-7 | All tool executions must be logged                      | HIGH     |
| INV-8 | Dashboard must be read-only (no direct backend mutation) | HIGH    |
| INV-9 | Shared memory is append-only via orchestrator           | HIGH     |
| INV-10| No circular imports between modules                     | MEDIUM   |
| INV-11| WebGen output MUST use hand-crafted design system, not LLM HTML | HIGH |
| INV-12| Vercel repos MUST include explicit framework/build/install/output fields | MEDIUM |
| INV-13| All cloud LLM calls MUST route through LLMRouter — no direct OpenRouter calls | HIGH |
| INV-14| API keys MUST live in .env with chmod 600 — never committed to git | CRITICAL |
| INV-15| Monthly cloud LLM cost MUST NOT exceed budget without soul_core approval | HIGH |
| INV-16| Embeddings MUST use local models only — cloud does not support them | MEDIUM || INV-17| Agents MUST NOT accumulate images/screenshots in conversation context — max 10 per session | CRITICAL |
| INV-18| Credentials MUST NEVER appear in agent context, tool params, or logs — vault-only | CRITICAL |
| INV-19| Browser automation MUST go through browser-worker pod — no host-level Playwright | HIGH     |
| INV-20| Network reserved ports (Xbox: 3074,88,500,3544,4500) MUST NOT be modified by agents | CRITICAL |
## 2. System Boundaries

```
┌─────────────────────────────────────────────────┐
│ BOUNDARY: Frontend ↔ Backend                     │
│ Protocol: REST API only                          │
│ Direction: Frontend reads, Backend writes         │
│ Mutation: Frontend CANNOT mutate backend state    │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│ BOUNDARY: Backend ↔ LLM                          │
│ Protocol: HTTP to Ollama                         │
│ Direction: Backend sends prompts, LLM responds   │
│ Mutation: LLM has NO state, NO side effects      │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│ BOUNDARY: Agent ↔ Agent                          │
│ Protocol: Via orchestrator ONLY                  │
│ Direction: Orchestrator mediates all routing     │
│ Mutation: Agents CANNOT directly invoke others   │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│ BOUNDARY: Agent ↔ Memory                         │
│ Protocol: Namespaced JSON store                  │
│ Direction: Agent reads/writes own namespace only │
│ Mutation: Cross-namespace access PROHIBITED      │
└─────────────────────────────────────────────────┘
```

## 3. Prohibited Patterns

| ID     | Pattern                                         | Why Prohibited                        |
|--------|-------------------------------------------------|---------------------------------------|
| PROH-1 | Dynamic tool registration at runtime             | Prevents untracked capability growth  |
| PROH-2 | Direct agent-to-agent function calls             | Violates orchestrator mediation       |
| PROH-3 | Frontend writing to backend state                | Breaks read-only dashboard contract   |
| PROH-4 | Silent filesystem mutations                      | Requires documentation trail          |
| PROH-5 | Importing LLM modules from frontend code         | Violates layer separation             |
| PROH-6 | Recursive directory deletion via safe_shell      | Safety constraint                     |
| PROH-7 | Package installation via safe_shell              | Security: controlled environment      |
| PROH-8 | Direct /docs modification without registry check | Governance bypass                     |

## 4. Rules for Tool Addition

1. Define tool in `backend/tools/` module.
2. Add entry to `SOURCE_OF_TRUTH.md` tool table.
3. Add entry to `CHANGE_LOG.md`.
4. Declare modification type: `READ_ONLY` | `STATE_MODIFY` | `ARCHITECTURAL_MODIFY`.
5. If `ARCHITECTURAL_MODIFY`: implement documentation enforcement hook.
6. Register tool in tool registry with proper guards.
7. Assign tool to specific agents in `AGENT_REGISTRY.md`.
8. Verify no invariant violations.

## 5. Rules for Agent Creation

1. Define agent in `AGENT_REGISTRY.md` FIRST (documentation precedes code).
2. Verify unique memory namespace (INV-4).
3. Verify tool permissions don't violate boundaries.
4. Implement agent class in `backend/agents/`.
5. Register in orchestrator graph.
6. Update `SOURCE_OF_TRUTH.md` agent table.
7. Add `CHANGE_LOG.md` entry.
8. Test agent isolation.

## 6. Rules for Memory Schema Changes

1. Document proposed schema change in `CHANGE_LOG.md`.
2. Verify no namespace overlap (INV-4).
3. Implement migration if existing data affected.
4. Update `SOURCE_OF_TRUTH.md` memory structure section.
5. Test isolation after change.

## 7. Drift Detection Criteria

The system is in a DRIFT state when:

- **YELLOW (Pending):** A code change exists without corresponding documentation update.
- **RED (Violation):** An architectural invariant is actively violated.
- **GREEN (Aligned):** All code changes have documentation. All invariants hold.

## 8. Response to Drift

| State  | Action                                              |
|--------|-----------------------------------------------------|
| GREEN  | Normal operation                                    |
| YELLOW | Log WARNING. Allow operation. Flag for review.      |
| RED    | Log CRITICAL_DRIFT_EVENT. Halt execution. Alert.    |

---

## 9. Anti-Patterns — Documented Disasters

### ANTI-1: Bella's Kitchen (WebGen V1 — LLM-Generated HTML)

**Location:** `output/webgen/bellas-kitchen/`
**Status:** DEPRECATED — DO NOT REPRODUCE
**Date:** 2026-03-01

#### What Happened

WebGen V1 let the LLM (llama3.2) generate full HTML pages including layout, styling, and content. The result was a generic, template-looking Italian restaurant site with zero design authority.

#### Why It Failed

| Problem                         | Description                                                |
|---------------------------------|------------------------------------------------------------|
| Generic Tailwind CDN injection  | `<script src="https://cdn.tailwindcss.com">` — no build step, no tree-shaking, runtime dependency |
| System-UI font stack            | `system-ui, -apple-system, sans-serif` — no typographic identity, looks like a browser default |
| Default blue color palette      | `#2563eb` primary — Tailwind default blue, screams "starter template"  |
| No design tokens                | Hardcoded values everywhere, no systematic spacing/color/motion system  |
| LLM hallucinated layout         | Random div nesting, inconsistent spacing, no vertical rhythm            |
| No image treatment              | Stock photos with no filters, no editorial tone, no vignettes           |
| No motion system                | Zero scroll reveals, no parallax, no interaction feedback               |
| No SEO schemas                  | No JSON-LD, no OG tags, no canonical URLs, invisible to search engines  |
| Flat file structure              | `about.html`, `menu.html` — no directory routing, no clean URLs         |
| No design hierarchy             | Everything same weight — headings, body, cards all feel equivalent      |

#### Lesson

**NEVER let the LLM generate HTML layout or styling.** The LLM writes copy. The design system, component library, and layout are hand-crafted or pulled from vetted templates. The V2 approach (Innovation Development Solutions) proved this: same LLM, same hardware, but the system constrains the LLM to copy-only while humans/design-system own visual output.

#### Mandatory Rule (INV-11)

| ID     | Invariant                                                        | Severity |
|--------|------------------------------------------------------------------|----------|
| INV-11 | WebGen output MUST use a hand-crafted design system, not LLM-generated HTML | HIGH     |

Any future WebGen pipeline MUST:
1. Use CSS custom properties (design tokens) — no inline/arbitrary values
2. Use curated typography (serif + sans-serif pairing minimum)
3. Include JSON-LD structured data on every page
4. Apply editorial image treatments (desaturation, vignette, grain)
5. Include scroll-based motion (IntersectionObserver reveals minimum)
6. Use directory-based routing (`/about/index.html` not `about.html`)

**Bella's Kitchen exists solely as a cautionary artifact. It must never be served to a customer.**

---

### ANTI-2: Vercel Framework Mismatch (Deploy Failure — 2026-03-02)

**Incident:** First deploy of IDS V2 static site to Vercel failed with `Build Failed: Command "npm run vercel-build" exited with 1`
**Repo:** `https://github.com/as4584/damianwebsite`
**Duration:** ~10 minutes from push to fix

#### What Happened

The `damianwebsite` repo was previously a **Next.js** application. Vercel project settings had `Framework Preset: Next.js` saved at the project level. When we replaced the repo contents with a static HTML/CSS/JS site, Vercel still tried to run `npm run vercel-build` (the Next.js build command) even though there was no `package.json`, no `node_modules`, and no Next.js in the repo.

#### Root Cause

| Factor                           | Detail                                                          |
|----------------------------------|-----------------------------------------------------------------|
| Vercel project-level settings    | `Framework Preset: Next.js` persists in Vercel dashboard even when repo contents change |
| Incomplete vercel.json           | Initial config omitted `framework`, `buildCommand`, `installCommand`, `outputDirectory` — Vercel fell back to project settings |
| Assumption error                 | Assumed removing framework fields from vercel.json was sufficient; Vercel project settings take precedence over omitted fields |

#### Fix Applied

Added explicit overrides to `vercel.json`:

```json
{
  "framework": null,
  "buildCommand": "",
  "installCommand": "",
  "outputDirectory": "."
}
```

These fields **override** Vercel project settings, forcing static file serving mode regardless of what the dashboard says.

#### Mandatory Rule (INV-12)

| ID     | Invariant                                                                  | Severity |
|--------|----------------------------------------------------------------------------|----------|
| INV-12 | Vercel repos MUST include explicit `framework`, `buildCommand`, `installCommand`, `outputDirectory` in vercel.json | MEDIUM   |

When deploying static sites to a repo that previously hosted a framework-based app:
1. `vercel.json` MUST explicitly set `"framework": null`
2. `vercel.json` MUST explicitly set `"buildCommand": ""`
3. `vercel.json` MUST explicitly set `"installCommand": ""`
4. `vercel.json` MUST explicitly set `"outputDirectory": "."`
5. **Never rely on field omission** — Vercel project settings override missing fields
6. After pushing, verify the deploy succeeds before reporting completion

### ANTI-3: CSS/JS Class Name Mismatch (Invisible Page — 2026-03-02)

**Incident:** WebGen V3 site rendered as completely blank — all content invisible despite valid HTML
**Site:** Innovation Development Solutions V3 (Bainbridge-inspired redesign)
**Duration:** Full rebuild cycle wasted

#### What Happened

V3 CSS and JS were generated in separate `create_file` calls during the same build session. CSS defined `.reveal.visible` as the class that transitions elements from `opacity: 0` to `opacity: 1`. JS used `classList.add('revealed')` instead of `classList.add('visible')`. Since every content section uses the `.reveal` class (which starts at `opacity: 0; transform: translateY(2rem)`), the entire page appeared blank — text existed in DOM but was invisible.

Additionally, 8 CSS class definitions were missing entirely:
- `.contact-form`, `.contact-form-wrap`, `.form-row`, `.form-note` (contact page)
- `.industry-card-icon`, `.industry-card-title`, `.industry-card-text`, `.industry-card-link` (industries page)

These classes were used in HTML but never defined in `style.css`, causing unstyled/broken layouts.

#### Root Cause

| Factor | Detail |
|---|---|
| Split file generation | CSS and JS created in separate tool calls with no cross-validation step |
| No contract enforcement | No shared constant, config, or naming convention enforced between CSS and JS |
| No render verification | Site was pushed to GitHub before being visually verified in a browser |
| HTML/CSS divergence | HTML templates were written using intuitive class names that didn't exist in the CSS file |

#### Why This Is Catastrophic

Unlike a broken button or wrong color, this failure produces a **completely blank page** — indistinguishable from a broken deploy. The user sees nothing. The DOM has content but it's all at `opacity: 0`. DevTools is required to even diagnose the issue.

#### Fix Applied

1. Changed `classList.add('revealed')` → `classList.add('visible')` in `js/main.js`
2. Added all 8 missing CSS class definitions to `css/style.css`
3. Full class audit: extracted every class from all HTML files, cross-referenced against CSS definitions

#### Mandatory Rules (INV-17, INV-18, INV-19)

| ID | Invariant | Severity |
|---|---|---|
| INV-17 | CSS animation trigger classes MUST be verified against JS `classList` calls before any commit | CRITICAL |
| INV-18 | After building a multi-file static site, run a class audit: extract all HTML classes and verify each has a CSS definition | HIGH |
| INV-19 | Static sites MUST be visually verified in a browser BEFORE pushing to any remote repository | HIGH |

#### Prevention Checklist (run after every WebGen build)

```bash
# 1. Extract all HTML classes
grep -oP 'class="[^"]*"' *.html **/*.html | tr '"' '\n' | tr ' ' '\n' | sort -u > /tmp/html_classes.txt

# 2. Check each against CSS
while read cls; do
  [ -z "$cls" ] && continue
  grep -q "\.$cls" css/style.css || echo "MISSING CSS: .$cls"
done < /tmp/html_classes.txt

# 3. Check JS classList calls match CSS
grep -oP "classList\.(add|toggle)\(['\"]([^'\"]+)" js/main.js | sed "s/.*['\"]//" | while read cls; do
  grep -q "\.$cls" css/style.css || echo "MISSING CSS TARGET: .$cls (used in JS)"
done

# 4. Visual verify before push
python3 -m http.server 8888  # then open browser
```

#### Lesson

> **Never trust that separately-generated files agree on naming conventions. Always cross-validate before deploy. A page at `opacity: 0` looks identical to an empty page.**
