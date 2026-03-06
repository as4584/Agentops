Good. I have everything I need. Here's the revised plan combining both options:

Plan: AEO Self-Improving System — Option D + E
TL;DR — Seven-node LangGraph cycle that discovers prompts → queries AI engines via APIs only (OpenRouter + Perplexity Sonar + Google Search JSON API, no browser scraping) → extracts citations → scores visibility → analyzes competitor pages → generates optimized content blocks → injects into WebGen projects. Storage uses SQLite (stdlib, already imported) for structured relational data and ChromaDB for vector similarity. The five broken non-atomic writes across the existing codebase are fixed as part of this work, since the cycle writes to multiple stores per run. New deps are minimal: chromadb, apscheduler, beautifulsoup4 (for competitor page analysis only).

Steps

1. Fix 5 broken atomic writes before adding anything new

These five methods all use bare Path.write_text() and will silently corrupt data during a multi-store cycle run. Copy the exact tmp → rename pattern from job_store.py (the only correct store):

__init__.py — _save_store(): write to store_file.with_suffix(".tmp"), then .rename(store_file)
__init__.py — append_shared_event(): same pattern on events_file
__init__.py — _save_to_disk(): tmp on _index_path
__init__.py — _save_business_profiles(): tmp on _profiles_path
site_store.py — save(): tmp on the project path
2. Add new config constants to config.py

Following the existing env-var pattern:

OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1") — not currently defined anywhere
AEO_TARGET_DOMAIN: str = os.getenv("AEO_TARGET_DOMAIN", "")
AEO_BRAND_NAME: str = os.getenv("AEO_BRAND_NAME", "")
AEO_SEED_QUERIES: list[str] — parsed from os.getenv("AEO_SEED_QUERIES", "[]") via json.loads
AEO_QUERY_ENGINES: list[str] — default ["openrouter", "perplexity_sonar", "google_search_api"]
AEO_CYCLE_INTERVAL_HOURS: int = int(os.getenv("AEO_CYCLE_INTERVAL_HOURS", "6"))
AEO_MAX_PROMPTS_PER_CYCLE: int = int(os.getenv("AEO_MAX_PROMPTS_PER_CYCLE", "50"))
PERPLEXITY_API_KEY: str = os.getenv("PERPLEXITY_API_KEY", "")
GOOGLE_SEARCH_API_KEY: str = os.getenv("GOOGLE_SEARCH_API_KEY", "")
GOOGLE_SEARCH_CX: str = os.getenv("GOOGLE_SEARCH_CX", "") — Custom Search Engine ID
3. Add dependencies to requirements.txt

chromadb>=0.5.0 — vector store for prompt dedup and block retrieval
apscheduler>=3.10.4 — in-process async scheduler (no Celery/Redis needed)
beautifulsoup4>=4.12.0 — competitor page gap analysis only (not for AI engine scraping)
No playwright Python package needed — the existing playwright.config.ts stays for E2E testing.

4. Create SQLite schema — backend/aeo/db.py

Three tables, managed via sqlite3 stdlib (already imported in __init__.py). Database file at backend/memory/aeo/aeo.db. Use WAL mode (PRAGMA journal_mode=WAL) for concurrent read-write safety. Schema:

prompts(id TEXT PK, text TEXT, category TEXT, source TEXT, priority_score REAL, last_tested_at TEXT, cycle_discovered TEXT)
visibility_history(id TEXT PK, cycle_id TEXT, domain TEXT, timestamp TEXT, citation_count INT, mention_count INT, visibility_score REAL, delta REAL, engine TEXT) — indexed on (domain, timestamp)
cycle_log(cycle_id TEXT PK, started_at TEXT, completed_at TEXT, state_node TEXT, target_domain TEXT, prompts_tested INT, errors TEXT)
Class AEODB: __init__ creates/migrates tables, all methods use context-managed connections. Methods: upsert_prompt, get_untested_prompts(limit), append_visibility, get_visibility_history(domain, limit), upsert_cycle, update_cycle_node.

5. Create ChromaDB vector store — backend/aeo/vector_store.py

Class AEOVectorStore. Persistent client at backend/memory/aeo/chroma/. Two collections only (not visibility history — that goes to SQLite):

aeo_prompts — embeddings via existing OllamaClient.embed() pattern, metadata includes category and last_tested_at; used for semantic dedup (cosine threshold 0.92 before insert)
aeo_content_blocks — blocks stored with metadata block_type, target_prompt_ids, injected_project_ids
Methods: is_duplicate_prompt(text) -> bool, upsert_prompt(record), search_blocks_for_prompt(prompt_text, top_k) -> list, upsert_block(block). The AEODB holds structured metadata; Chroma holds embeddings and similarity search.

6. Create Pydantic models — backend/aeo/models.py

Following patterns from models.py:

PromptRecord — id, text, category, source, priority_score, last_tested_at
AIQueryResult — prompt_id, engine, answer_text, cited_domains: list[str], brand_mentioned: bool, brand_position: int | None
VisibilityReport — domain, cycle_id, citation_count, mention_count, visibility_score, delta, per_engine: dict
ContentGap — your_url, competitor_url, competitor_domain, missing_faq: bool, missing_schema_types: list[str], missing_summary: bool, impact_score: float
OptimizedContentBlock — id, block_type, prompt_targets: list[str], html_content, json_ld: dict, target_page_ids: list[str]
AEOCycleState TypedDict — cycle_id, target_domain, brand_name, discovered_prompts, query_results, visibility_report, content_gaps, generated_blocks, injected_pages, errors, current_node
7. Create API query engine — backend/aeo/ai_query_engine.py

No Playwright. Three pure httpx clients:

query_openrouter(prompt, model) — POST to OPENROUTER_BASE_URL/chat/completions with web_search: true param using existing OPENROUTER_API_KEY. Parse choices[0].message.content for answer; parse citations array if returned (OpenRouter exposes source URLs when web search is active).
query_perplexity_sonar(prompt) — POST to https://api.perplexity.ai/chat/completions using PERPLEXITY_API_KEY with model sonar. Parse citations array from response — Perplexity Sonar API returns structured citation URLs natively.
query_google_search_api(prompt) — GET https://www.googleapis.com/customsearch/v1 with GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX. Returns organic URLs; extract featuredSnippet if present. Surfaces which domains dominate answer-box position.
query_all(prompt, engines) — async httpx.AsyncClient fan-out across configured engines, returns list[AIQueryResult]. Respects AEO_QUERY_ENGINES config.
Graceful degradation: if a key is blank for an engine, that engine is skipped with a logged warning — no crash.
8. Create citation extractor — backend/aeo/citation_extractor.py

extract_domains(urls: list[str]) -> list[str] — urllib.parse.urlparse to get hostname, strips www.
check_brand_mention(text, brand_name) -> bool — lowercased substring + common variant forms (hyphenated, spaced, abbreviated)
get_position(domains, target_domain) -> int | None — 1-indexed position in citation list
enrich_result(result: AIQueryResult, brand_name, target_domain) -> AIQueryResult — fills brand_mentioned, brand_position
9. Create visibility scorer — backend/aeo/visibility_scorer.py

score(citation_count, mention_count, position) -> float — citation_count * 5 + mention_count * 3 + position_weight where weight is 3 / position (decaying)
generate_report(domain, cycle_id, results) -> VisibilityReport — aggregates over all AIQueryResult for the domain, computes per-engine breakdown
compute_delta(prev: VisibilityReport | None, curr: VisibilityReport) -> float
get_top_competitors(results) -> list[str] — all cited domains ranked by frequency, excluding target domain
10. Create prompt discovery — backend/aeo/prompt_discovery.py

All httpx-only, no browser:

discover_from_autocomplete(seeds: list[str]) -> list[str] — httpx GET https://suggestqueries.google.com/complete/search?client=firefox&q=... (public, no auth)
discover_from_paa(seed_query) -> list[str] — Google Search JSON API (customsearch/v1) with GOOGLE_SEARCH_API_KEY; extracts questions from relatedSearches or QAPage schema in results snippets
generate_with_llm(niche, existing_prompts, count) -> list[str] — Ollama via existing OllamaClient, prompts LLM to generate novel questions given the niche
categorize(prompt) -> str — LLM classifies as informational | commercial | transactional
run(seeds, niche) -> list[PromptRecord] — calls all three, deduplicates via AEOVectorStore.is_duplicate_prompt(), stores via AEODB.upsert_prompt()
11. Create gap analyzer — backend/aeo/gap_analyzer.py

Competitor page analysis via httpx + BeautifulSoup (this is the legitimate use case for BS4 — fetching competitor public pages, not AI engine UIs):

fetch_page(url) -> BeautifulSoup
analyze_structure(soup) -> dict — checks: FAQ <details> or <dl> block, FAQPage JSON-LD in <script type="application/ld+json">, HowTo schema, H2/H3 count, summary paragraph under H1 (<60 words), SpeakableSpecification
compare(your_url, competitor_url) -> ContentGap — runs analyze_structure on both, diffs the results, computes impact_score (weighted: FAQ missing = 0.4, schema missing = 0.3, summary missing = 0.3)
analyze_top_competitors(your_url, competitor_domains) -> list[ContentGap] — async fan-out, returns sorted by impact_score
12. Create content optimizer — backend/aeo/content_optimizer.py

generate_faq_block(gaps, target_prompts) -> OptimizedContentBlock — Ollama LLM generates FAQ Q&A pairs + <details>/<summary> HTML + FAQPage JSON-LD. Checks AEOVectorStore.search_blocks_for_prompt() first to avoid regenerating if block already exists.
generate_summary_paragraph(topic) -> str — ≤40-word answer paragraph, LLM at temperature 0.3
generate_schema_patches(entity_type, missing_types) -> dict — fills Organization, Product, or SoftwareApplication JSON-LD
inject_into_project(project_id, blocks) — loads project via site_store.py, calls existing AEOAgent._inject_aeo() with merged AEOProfile (new blocks layered on top of existing faq_pairs), saves via SiteStore.save() (now atomic after step 1)
13. Create LangGraph cycle — backend/aeo/self_improvement_loop.py

Seven-node StateGraph(AEOCycleState) following the exact graph construction pattern from __init__.py:


discover → query → extract → score → analyze → generate → inject → END
Conditional edge after score: if delta >= 0 and no content gaps in last report → skip analyze/generate, jump straight to inject with cached blocks (avoids expensive LLM re-generation when score is already improving)
Each node writes its output node name to cycle_log via AEODB.update_cycle_node() — so a crash mid-cycle is observable and resumable
query node: async batch with concurrency cap of 5 (semaphore) to avoid rate-limiting all three API engines
SelfImprovementScheduler wraps the compiled graph: APScheduler AsyncIOScheduler, interval from AEO_CYCLE_INTERVAL_HOURS. Persists last_run to backend/memory/aeo/scheduler.json (atomic write). Prevents double-run by checking cycle_log for any cycle with completed_at = NULL.

14. Create FastAPI router — backend/aeo/router.py

POST /aeo/cycle/start — trigger immediate cycle; returns cycle_id
GET /aeo/cycle/status — current node from cycle_log, started_at, prompts_tested
GET /aeo/visibility — latest VisibilityReport for AEO_TARGET_DOMAIN
GET /aeo/visibility/history?limit=20 — time-series data from SQLite for chart rendering
GET /aeo/prompts — all prompts with category, last_tested_at, coverage stats
GET /aeo/gaps — latest ContentGap list sorted by impact_score
GET /aeo/blocks — all OptimizedContentBlock records
POST /aeo/blocks/{block_id}/inject/{project_id} — manual inject
GET /stream/aeo-activity — SSE using existing SSE pattern from server.py
GET /aeo/config / PUT /aeo/config — read/update domain, brand, seed queries, engines, interval
15. Register router in server.py

Add from backend.aeo.router import aeo_router and app.include_router(aeo_router, prefix="/aeo", tags=["aeo"]) — consistent with existing router includes (sandbox_router, content_pipeline_router, etc.)

16. Create frontend AEO Monitor page

New page at frontend/app/aeo-monitor/page.tsx (Next.js 15 app router, matching existing frontend structure):

Visibility score line chart (recharts) fed from GET /aeo/visibility/history
Prompts table: text, category, engines tested, brand visible (y/n), last tested
Content gaps panel: competitor domain, missing items, impact score (color-coded)
Generated blocks list with "Inject into Project" button → POST /aeo/blocks/{id}/inject/{projectId}
Cycle control: Start Cycle button + live status badge consuming SSE /stream/aeo-activity
Per-engine breakdown card: OpenRouter / Perplexity Sonar / Google Search API visibility scores side-by-side
17. Write tests — backend/tests/test_aeo_system.py

test_atomic_write_safety — verify all 5 fixed stores use tmp→rename (import and inspect source)
test_prompt_dedup — two semantically similar prompts → only one inserted (mocked Chroma threshold)
test_citation_extraction — mock AIQueryResult with known cited_domains → enrich_result returns correct brand_position
test_visibility_scoring_deterministic — fixed citation inputs → expected score value
test_gap_analyzer_detects_missing_faq — HTML without <details> or FAQPage JSON-LD → missing_faq=True, impact_score ≈ 0.4
test_api_engine_skips_if_key_blank — OPENROUTER_API_KEY = "" → engine not called, no exception
test_cycle_state_machine — monkeypatch all 7 node functions, verify state flows discover → inject and cycle_log is updated at each node
test_scheduler_no_double_run — completed_at = NULL row in cycle_log → start() returns existing cycle_id, does not launch new graph
Verification


pip install chromadb apscheduler beautifulsoup4# Set required env varsexport OPENROUTER_API_KEY=sk-...export PERPLEXITY_API_KEY=pplx-...export GOOGLE_SEARCH_API_KEY=...export GOOGLE_SEARCH_CX=...export AEO_TARGET_DOMAIN=lexmakesit.comexport AEO_BRAND_NAME="LexMakesIt"# Run all tests including new onesPYTHONPATH=. pytest backend/tests/test_aeo_system.py backend/tests/test_gatekeeper_smoke.py backend/tests/test_webgen_sandbox_enforcement.py -v# Start backend, trigger a cycleuvicorn backend.server:app --reloadcurl -X POST http://localhost:8000/aeo/cycle/startcurl http://localhost:8000/aeo/cycle/statuscurl http://localhost:8000/stream/aeo-activity   # SSE live feed
Decisions made

SQLite for structured data, Chroma for vectors — visibility history needs WHERE timestamp > range queries that Chroma cannot do; Chroma handles semantic dedup and block retrieval that flat SQL cannot do efficiently
WAL mode on SQLite — allows concurrent reads from FastAPI while the cycle writes, no extra locking needed
No Playwright Python dep — query_openrouter (web search mode), query_perplexity_sonar, and query_google_search_api cover all three meaningful AI visibility signals through official APIs with structured citation responses
BS4 for competitor pages only — fetching public competitor HTML for gap analysis is legitimate; it's not scraping an AI engine UI
Five atomic write fixes first — the cycle writes to SiteStore, MemoryStore, and two knowledge stores in a single run; fixing them is a prerequisite, not an add-on
KnowledgeVectorStore untouched — AEO blocks go into Chroma aeo_content_blocks; LLM knowledge stays in vectors.json; no mixed-bag contamination
Does this look right, or do you want to adjust anything before implementation?