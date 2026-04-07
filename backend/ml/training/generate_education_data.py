"""Generate gold training data for the education_agent.

Produces 800 ShareGPT-format JSONL examples.

Input: messy student question (confusion, frustration, partial knowledge)
Output: scaffolded response following the pattern:
  1. What is it — clear definition
  2. Why it matters — connect to outcomes/career
  3. Simple analogy — make it stick
  4. Real example — concrete, from BSEAI context when possible
  5. Quick check question — verify understanding
  6. Next step — what to explore or practice next

Pedagogy reward signals: scaffolding, chunking, analogies, follow-up questions, confusion detection

Usage:
    python -m backend.ml.training.generate_education_data
    python -m backend.ml.training.generate_education_data --count 400
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

# ── Studios & concepts ───────────────────────────────────────────────

_STUDIOS = [
    {
        "id": "IS 117",
        "name": "Studio 1: Web Development & Disciplined Inquiry",
        "edge": "Disciplined Inquiry",
        "concepts": [
            ("HTML semantics", "Using the right HTML elements for their intended purpose (not just divs)"),
            (
                "CSS specificity",
                "Rules that determine which CSS declarations win when multiple rules target the same element",
            ),
            ("DOM manipulation", "Changing the structure, style, or content of a web page using JavaScript"),
            (
                "HTTP request/response cycle",
                "The fundamental pattern of web communication: client asks, server answers",
            ),
            ("version control basics", "Using git to track, manage, and collaborate on code changes over time"),
            ("responsive design", "Making web pages look good on any screen size using flexible layouts"),
            ("accessibility (a11y)", "Making web content usable by people with disabilities"),
        ],
    },
    {
        "id": "IS 118",
        "name": "Studio 2: Full-Stack Engineering & Professional Judgment",
        "edge": "Professional Judgment",
        "concepts": [
            ("technical debt", "Shortcuts in code that save time now but cost more to fix later (Cunningham)"),
            ("REST API design", "Designing HTTP interfaces using resources, verbs, and status codes"),
            ("database normalization", "Organizing database tables to reduce redundancy and improve integrity"),
            ("authentication vs authorization", "Auth = who are you? Authz = what can you do?"),
            ("MVC pattern", "Model-View-Controller — separating data, presentation, and logic"),
            ("ORM basics", "Object-Relational Mapping — using objects in code to interact with database tables"),
            ("error handling patterns", "Try/catch, result types, graceful degradation — managing failure in code"),
        ],
    },
    {
        "id": "IS 218",
        "name": "Studio 3: Infrastructure & Resilience Thinking",
        "edge": "Resilience Thinking",
        "concepts": [
            ("containerization", "Packaging an app with its dependencies so it runs the same everywhere (Docker)"),
            ("CI/CD pipeline", "Automated workflow: build, test, deploy code changes continuously"),
            ("load balancing", "Distributing traffic across multiple servers to prevent overload"),
            ("12-factor app", "12 best practices for building modern, cloud-ready applications (Heroku)"),
            ("infrastructure as code", "Managing servers and networks through configuration files, not manual setup"),
            ("monitoring and alerting", "Watching system health metrics and getting notified when things go wrong"),
            ("disaster recovery", "Plans and procedures for restoring systems after a catastrophic failure"),
        ],
    },
    {
        "id": "IS 265",
        "name": "Studio 4: Business Analysis & Problem Finding",
        "edge": "Problem Finding",
        "concepts": [
            (
                "problem finding vs problem solving",
                "Finding the right problem is harder and more valuable than solving the wrong one",
            ),
            ("5 Whys technique", "Asking 'why' repeatedly to dig past symptoms to root causes (Toyoda/Toyota)"),
            ("stakeholder analysis", "Identifying everyone affected by a project and understanding their needs"),
            (
                "requirements elicitation",
                "Techniques for discovering what users actually need (not just what they say)",
            ),
            ("business process modeling", "Visual diagrams showing how work flows through an organization"),
            ("cost-benefit analysis", "Comparing the expected costs against benefits to make informed decisions"),
            (
                "MVP (minimum viable product)",
                "The smallest version of a product that delivers value and enables learning",
            ),
        ],
    },
    {
        "id": "IS 331",
        "name": "Studio 5: Data & Knowledge Systems & Epistemic Humility",
        "edge": "Epistemic Humility",
        "concepts": [
            ("vector embeddings", "Numbers that capture the meaning of text, enabling semantic similarity search"),
            (
                "RAG (retrieval-augmented generation)",
                "Feeding relevant documents to an LLM before it answers, reducing hallucination",
            ),
            ("ETL pipeline", "Extract-Transform-Load — moving data from sources, cleaning it, storing it"),
            (
                "data normalization vs denormalization",
                "Organizing data to reduce redundancy (normalize) vs duplicating for speed (denormalize)",
            ),
            ("knowledge graphs", "Networks of entities and relationships that represent structured knowledge"),
            ("data governance", "Policies for data quality, privacy, security, and lifecycle management"),
            ("semantic search", "Finding results by meaning rather than exact keyword matching"),
        ],
    },
    {
        "id": "IS 390",
        "name": "Studio 6: Systems Analysis & Design & Systems Thinking",
        "edge": "Systems Thinking",
        "concepts": [
            ("systems thinking", "Seeing the whole system and how parts interact, not just individual components"),
            (
                "essential vs accidental complexity",
                "Complexity from the problem itself vs complexity we add through poor design (Brooks)",
            ),
            (
                "state machines",
                "Models where a system is always in one defined state and transitions between states on events",
            ),
            ("hexagonal architecture", "Ports-and-adapters pattern: core logic is isolated from external systems"),
            ("SOLID principles", "Five object-oriented design principles for maintainable, extensible code"),
            ("design patterns", "Reusable solutions to common software design problems (Gang of Four)"),
            ("sequence diagrams", "Visual representation of how objects interact over time in a specific scenario"),
        ],
    },
    {
        "id": "IS 425",
        "name": "Studio 7: Applied Enterprise AI & Accountable Leadership",
        "edge": "Accountable Leadership",
        "concepts": [
            ("prompt engineering", "Crafting effective instructions for AI models to produce desired outputs"),
            ("AI hallucination", "When an AI confidently generates information that is incorrect or fabricated"),
            ("human-in-the-loop (HITL)", "Keeping humans involved in AI decision-making for safety and accountability"),
            ("model evaluation", "Measuring how well an AI model performs against defined criteria"),
            ("responsible AI", "Building AI systems that are fair, transparent, private, and accountable"),
            ("fine-tuning vs prompting", "Adapting a model's weights (fine-tune) vs adapting its inputs (prompt)"),
            ("token economics", "Understanding how LLMs process text in tokens and managing costs and context limits"),
        ],
    },
    {
        "id": "IS 482",
        "name": "Studio 8: Community AI Training & Translation",
        "edge": "Translation",
        "concepts": [
            (
                "AI translation (tech→non-tech)",
                "Explaining technical AI concepts to non-technical stakeholders clearly",
            ),
            ("community of practice", "A group of people who share a craft and learn from each other (Wenger)"),
            ("train-the-trainer", "Teaching people to become effective teachers themselves"),
            ("Feynman technique", "Explain simply → find gaps → return to source → simplify again"),
            ("cognitive load theory", "Working memory holds ~4 items; manage load or lose the learner (Sweller)"),
            ("CCR loop", "Create with AI → Critique with vocabulary → Revise with insight"),
            ("demo day preparation", "Building and presenting a real deliverable to a real audience"),
        ],
    },
]

# Student confusion templates — realistic student language
_CONFUSION_TEMPLATES: list[dict] = [
    # Basic confusion
    {
        "q": "what even is {concept}? i keep hearing it but idk what it means",
        "confusion_type": "vocabulary_gap",
        "severity": "low",
    },
    {
        "q": "um so in {studio_name} theres this thing about {concept}? whats the point",
        "confusion_type": "relevance_gap",
        "severity": "low",
    },
    {
        "q": "ok i think i get {concept} but can you explain it like im 5",
        "confusion_type": "abstraction_gap",
        "severity": "low",
    },
    # Frustration
    {
        "q": "i literally dont understand {concept}, ive read the slides 3 times and still confused",
        "confusion_type": "comprehension_block",
        "severity": "medium",
    },
    {
        "q": "why do we even need {concept}?? seems like extra work for no reason",
        "confusion_type": "motivation_gap",
        "severity": "medium",
    },
    {
        "q": "{concept} makes no sense to me, i thought programming was just writing code not all this theory stuff",
        "confusion_type": "expectation_mismatch",
        "severity": "medium",
    },
    # Partial knowledge
    {
        "q": "so {concept} is basically like {wrong_analogy} right?",
        "confusion_type": "misconception",
        "severity": "high",
    },
    {
        "q": "i can do {concept} in my code but i dont really understand WHY it works, is that ok?",
        "confusion_type": "procedural_only",
        "severity": "medium",
    },
    {
        "q": "whats the difference between {concept} and {related_concept}? they seem like the same thing",
        "confusion_type": "conflation",
        "severity": "high",
    },
    # Application struggles
    {
        "q": "how do i actually use {concept} in a real project tho? the examples in class are too simple",
        "confusion_type": "transfer_gap",
        "severity": "medium",
    },
    {
        "q": "i understand {concept} in theory but when i try to implement it everything breaks",
        "confusion_type": "theory_practice_gap",
        "severity": "high",
    },
    # Career anxiety
    {
        "q": "will i actually need {concept} in a real job or is this just academic stuff",
        "confusion_type": "career_relevance",
        "severity": "low",
    },
    {
        "q": "im in {studio_name} and feeling behind, everyone else seems to get {concept} but me",
        "confusion_type": "imposter_syndrome",
        "severity": "medium",
    },
    # Meta-learning
    {
        "q": "how should i study {concept}? reading the book isnt working",
        "confusion_type": "study_strategy",
        "severity": "low",
    },
    {
        "q": "wait so when you say {concept}, is that the same as what {other_source} calls it?",
        "confusion_type": "terminology_mapping",
        "severity": "medium",
    },
    # Multi-concept
    {
        "q": "in {studio_name} we covered {concept} and {related_concept} but i dont see how they connect",
        "confusion_type": "connection_gap",
        "severity": "high",
    },
]

_WRONG_ANALOGIES = {
    "vector embeddings": "just a list of numbers",
    "technical debt": "bugs in the code",
    "containerization": "like a zip file",
    "CI/CD pipeline": "a script that runs tests",
    "state machines": "just a bunch of if-else statements",
    "REST API design": "just URLs that return data",
    "systems thinking": "thinking about computer systems",
    "prompt engineering": "just talking to the AI",
    "hexagonal architecture": "having six layers",
    "RAG (retrieval-augmented generation)": "googling things for the AI",
}

_OTHER_SOURCES = [
    "the textbook",
    "Stack Overflow",
    "ChatGPT",
    "my friend who works at Google",
    "a YouTube tutorial",
    "the documentation",
]


def _pick_concept_and_studio() -> tuple[dict, str, str]:
    studio = random.choice(_STUDIOS)
    concept_name, concept_def = random.choice(studio["concepts"])
    return studio, concept_name, concept_def


def _pick_related_concept(studio: dict, exclude: str) -> str:
    others = [c[0] for c in studio["concepts"] if c[0] != exclude]
    if others:
        return random.choice(others)
    other_studio = random.choice(_STUDIOS)
    return random.choice(other_studio["concepts"])[0]


def _format_response(concept_name: str, concept_def: str, studio: dict) -> str:
    """Generate a scaffolded education response following the 6-step pattern."""
    human_edge = studio["edge"]
    studio_id = studio["id"]

    response = (
        f"**What is it:** {concept_def}\n\n"
        f"**Why it matters:** In {studio_id} ({studio['name'].split(': ', 1)[-1]}), "
        f"this concept develops your *{human_edge}* capability — one of the Human Edge skills "
        f"that AI cannot replicate. Understanding {concept_name} gives you the vocabulary and "
        f"mental model to evaluate AI-generated solutions, not just accept them.\n\n"
        f"**Simple analogy:** "
    )

    # Add analogy based on concept
    analogies = {
        "vector embeddings": "Think of it like GPS coordinates for meaning. Just as GPS turns a location into numbers (latitude, longitude), embeddings turn text into numbers that capture what it *means*. Similar ideas end up at nearby coordinates.",
        "technical debt": "It's like taking a shortcut through someone's yard instead of walking on the sidewalk. Works once, but if you keep doing it you'll wear a muddy path that's harder to fix than the original detour.",
        "containerization": "Imagine shipping a meal in a sealed lunchbox with utensils, napkin, and plate included. No matter whose kitchen you open it in, everything you need is inside. That's a container.",
        "CI/CD pipeline": "Like a car assembly line: each station checks one thing (tests), adds one thing (build), and passes it forward. If any station fails, the line stops before a broken car ships.",
        "state machines": "Think of a traffic light: it's always in exactly one state (red, yellow, green) and transitions between them based on events (timer, sensor). It never tries to be two colors at once.",
        "REST API design": "Like a restaurant menu: you (client) pick an item (resource) and tell the waiter (HTTP) what you want to do (GET=look, POST=order, PUT=change order, DELETE=cancel).",
        "systems thinking": "Like understanding weather vs just looking at the thermometer. Temperature is one data point; systems thinking means seeing how pressure, humidity, wind, and geography all interact to create the weather.",
        "prompt engineering": "Like writing a brief for a freelancer. The better your instructions (context, constraints, examples, format), the closer the output matches what you actually wanted.",
    }

    analogy_text = analogies.get(
        concept_name,
        f"Think of {concept_name} as a building block — each time you understand one more concept, it clicks into place with the others to form a bigger picture.",
    )
    response += analogy_text + "\n\n"

    response += "**Real example:** In the Agentop project, "
    examples = {
        "vector embeddings": "we use nomic-embed-text to convert documents into 768-dimensional vectors stored in the KnowledgeVectorStore. When you search 'how does routing work?', the system finds docs with similar meaning — not just matching words.",
        "technical debt": "the early router was a simple keyword match. It worked for 11 agents, but as we added more, the keyword collisions became unmanageable. We eventually needed a 3-tier router (C fast-path → LLM → keyword fallback) — the debt of the original shortcut.",
        "containerization": "the MCP tools run inside Docker containers via the MCP Bridge. Each tool group (github, filesystem, sqlite) is isolated so a crash in one doesn't take down others.",
        "CI/CD pipeline": "every push to dev runs: ruff check → ruff format --check → mypy → pytest (≥58% coverage) → frontend build → tsc --noEmit. Only when all pass can we merge to main.",
        "state machines": "the LangGraph orchestrator uses a state machine for agent routing. Each user message transitions through states: RECEIVED → CLASSIFIED → ROUTED → PROCESSING → COMPLETE.",
        "REST API design": "the FastAPI backend exposes RESTful endpoints: GET /skills for listing, GET /skills/{id} for details, PATCH /skills/{id} for toggling enabled state. Each resource has a clear URL and appropriate HTTP verb.",
        "systems thinking": "when the GLM-OCR sidecar goes down, it doesn't just break document extraction — it cascades: knowledge_agent can't index new docs, file_reader falls back to raw text (wasting tokens), and any agent requesting OCR gets degraded results.",
        "prompt engineering": "each of our 14 agents has a carefully crafted system prompt that constrains its behavior. The prompt_engineer agent goes further — it restructures messy user input into goal/constraints/success_criteria format before routing.",
    }
    response += (
        examples.get(
            concept_name,
            "this concept appears across multiple agents and tools, connecting theory to the practical system you're building.",
        )
        + "\n\n"
    )

    check_questions = {
        "vector embeddings": "If two sentences have very different words but mean the same thing, would their vector embeddings be close together or far apart?",
        "technical debt": "You need to ship a feature by Friday. You can do it the quick way (hardcoded values) or the clean way (configurable). Which approach creates technical debt, and when would you choose it anyway?",
        "containerization": "If a container includes everything the app needs to run, what problem does this solve when moving from your laptop to a server?",
        "CI/CD pipeline": "Why does the CI pipeline run tests BEFORE deployment rather than after?",
        "state machines": "Can a state machine be in two states at the same time? Why or why not?",
        "REST API design": "If you want to create a new customer record, which HTTP verb would you use: GET, POST, PUT, or DELETE?",
        "systems thinking": "If we optimize one agent to be 10x faster but it overwhelms the shared message bus, is that a net improvement? Why?",
        "prompt engineering": "What's the difference between giving an AI 'write me a good email' vs 'write a 3-paragraph professional email to a client declining a meeting, tone: apologetic but firm'?",
    }
    response += f"**Check question:** {check_questions.get(concept_name, f'In your own words, explain {concept_name} to someone who has never heard of it. What analogy would YOU use?')}\n\n"

    response += "**Next step:** "
    next_steps = {
        "vector embeddings": "Try running `nomic-embed-text` on two similar sentences and two different ones. Compare the cosine similarity scores. Then read about how our KnowledgeVectorStore uses this in `backend/knowledge/__init__.py`.",
        "technical debt": "Identify one piece of 'debt' in your current project. Write a 2-sentence note: what was the shortcut, and what would the 'proper' solution look like? This is the start of your AI Audit Log.",
        "containerization": "Run `docker ps` on the Agentop dev machine and identify which MCP tool groups are containerized. Try stopping one and observe how the system degrades gracefully.",
        "CI/CD pipeline": "Look at `.github/workflows/` in the Agentop repo. Trace what happens when you push to dev: which checks run in what order?",
    }
    response += next_steps.get(
        concept_name,
        f"Practice explaining {concept_name} to a classmate using only analogies — no jargon. If they understand, you've internalized it (Feynman technique).",
    )

    return response


def _generate_one(template: dict, studio: dict, concept_name: str, concept_def: str) -> dict:
    """Generate one ShareGPT example from a template."""
    q = template["q"]
    q = q.replace("{concept}", concept_name)
    q = q.replace("{studio_name}", studio["name"])

    if "{related_concept}" in q:
        q = q.replace("{related_concept}", _pick_related_concept(studio, concept_name))
    if "{wrong_analogy}" in q:
        q = q.replace("{wrong_analogy}", _WRONG_ANALOGIES.get(concept_name, "just a fancy word for the same thing"))
    if "{other_source}" in q:
        q = q.replace("{other_source}", random.choice(_OTHER_SOURCES))

    # Random casing/filler variation
    if random.random() < 0.3:
        q = q.lower()
    if random.random() < 0.2:
        q = random.choice(["um ", "so ", "ok ", "hey ", "wait "]) + q

    response_text = _format_response(concept_name, concept_def, studio)

    system_msg = (
        "You are the Agentop Education Agent. For every student question, follow this pattern:\n"
        "1. What is it — clear definition\n"
        "2. Why it matters — connect to Human Edge capability and career\n"
        "3. Simple analogy — make it stick\n"
        "4. Real example — from BSEAI or Agentop context\n"
        "5. Quick check question — verify understanding\n"
        "6. Next step — what to explore next\n\n"
        "Break concepts into steps. Remember misconceptions. Scaffold before lecturing.\n"
        "Be encouraging. Use the student's existing knowledge as a foundation."
    )

    return {
        "conversations": [
            {"from": "system", "value": system_msg},
            {"from": "human", "value": q},
            {"from": "gpt", "value": response_text},
        ],
        "metadata": {
            "source": "agentop_education_gold",
            "studio": studio["id"],
            "concept": concept_name,
            "human_edge": studio["edge"],
            "confusion_type": template["confusion_type"],
            "severity": template["severity"],
        },
    }


def generate(count: int = 800, seed: int = 42) -> list[dict]:
    """Generate `count` ShareGPT-format training examples for education_agent."""
    random.seed(seed)
    examples = []
    for _ in range(count):
        studio, concept_name, concept_def = _pick_concept_and_studio()
        template = random.choice(_CONFUSION_TEMPLATES)
        examples.append(_generate_one(template, studio, concept_name, concept_def))
    return examples


def main() -> None:
    count = 800
    if len(sys.argv) > 1 and sys.argv[1] == "--count":
        count = int(sys.argv[2])

    outdir = Path("data/training/gold")
    outdir.mkdir(parents=True, exist_ok=True)
    outpath = outdir / "education_agent_v1.jsonl"

    examples = generate(count=count)
    with open(outpath, "w") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")

    # Stats
    studios = {}
    confusion_types = {}
    for ex in examples:
        s = ex["metadata"]["studio"]
        c = ex["metadata"]["confusion_type"]
        studios[s] = studios.get(s, 0) + 1
        confusion_types[c] = confusion_types.get(c, 0) + 1

    print(f"Generated {len(examples)} examples → {outpath}")
    print(f"  Studio distribution: {dict(sorted(studios.items()))}")
    print(f"  Confusion types: {dict(sorted(confusion_types.items(), key=lambda x: -x[1]))}")


if __name__ == "__main__":
    main()
