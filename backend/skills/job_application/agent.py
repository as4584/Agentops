"""
Job Application Engine — Agentop Skill
Handles job search, resume tailoring, cover letter generation,
application tracking, and scholarship research for Lex Santiago.
Only uses skills verified from github.com/as4584 and this Agentop repo.
"""

import datetime
import sqlite3
from pathlib import Path

SKILL_DIR = Path(__file__).parent
DB_PATH = Path("data/job_applications.db")
RESUMES_DIR = Path("/mnt/c/Users/AlexS/Downloads")

RESUME_MAP = {
    "epic": "Alexander_Santiago_Epic.docx",
    "earthcam": "Alexander_Santiago_EarthCam.docx",
    "fdm": "Alexander_Santiago_FDM.docx",
    "camares": "Alexander_Santiago_Camares.docx",
    "bel": "Alexander_Santiago_BEL.docx",
    "uci": "Alexander_Santiago_UCI.docx",
    "default": "Alexander_Santiago_Resume_Updated.docx",
}

LEX_SKILLS = {
    "languages": ["Python", "TypeScript", "JavaScript", "Kotlin", "Dart", "Lua", "Rust", "SQL", "HTML/CSS"],
    "frameworks": [
        "FastAPI",
        "Flask",
        "Flutter",
        "LangGraph",
        "Docker",
        "Redis",
        "PostgreSQL",
        "Playwright",
        "Pydantic",
        "Next.js",
    ],
    "ai_ml": [
        "OpenAI GPT",
        "RAG pipelines",
        "Ollama",
        "LangGraph orchestration",
        "Twilio Voice",
        "multi-agent systems",
    ],
    "integrations": ["SAP ARP", "Lightspeed POS", "Twilio", "Google Sheets API", "MCP Docker bridge"],
    "practices": [
        "REST API design",
        "JWT auth",
        "Docker",
        "E2E testing (Playwright)",
        "Git",
        "CI/CD",
        "multi-agent orchestration",
    ],
    "projects": {
        "Agentop": "Local-first multi-agent AI orchestration system. LangGraph, Ollama, 47 tools, Drift Guard middleware, VS Code extension.",
        "AI Receptionist": "Production FastAPI + OpenAI + Twilio + RAG + PostgreSQL + Redis. Serving real salon/HVAC clients 24/7.",
        "Vendora": "Reseller inventory management app for multi-platform selling.",
        "ReflectAI": "Android (Kotlin) journaling app with AI reflection prompts and mood tracking.",
        "Restaurant App": "Cross-platform Flutter mobile ordering and menu app.",
        "IS218 Series": "FastAPI + Docker + JWT + Pydantic + Playwright E2E — Modules 10–13.",
        "DonXera Inventory": "SAP ARP + Lightspeed POS real-time inventory sync for 140+ SKUs across multiple locations.",
    },
}


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            role TEXT NOT NULL,
            url TEXT,
            status TEXT DEFAULT 'to_apply',
            resume_used TEXT,
            applied_date TEXT,
            follow_up_date TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scholarships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            provider TEXT,
            amount TEXT,
            deadline TEXT,
            url TEXT,
            requirements TEXT,
            status TEXT DEFAULT 'researching',
            notes TEXT
        )
    """)
    conn.commit()
    conn.close()


def track_application(
    company: str, role: str, url: str = "", status: str = "to_apply", resume_used: str = "", notes: str = ""
) -> dict:
    """Log a job application to the tracker."""
    init_db()
    applied = datetime.date.today().isoformat() if status == "applied" else None
    follow_up = (datetime.date.today() + datetime.timedelta(days=7)).isoformat() if applied else None
    resume = resume_used or RESUME_MAP.get(company.lower().split()[0], RESUME_MAP["default"])
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "INSERT INTO applications (company, role, url, status, resume_used, applied_date, follow_up_date, notes) VALUES (?,?,?,?,?,?,?,?)",
        (company, role, url, status, resume, applied, follow_up, notes),
    )
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return {"id": row_id, "company": company, "role": role, "status": status, "resume": resume}


def get_resume_for_company(company: str) -> str:
    """Return the best tailored resume filename for a given company."""
    key = company.lower().split()[0]
    return RESUME_MAP.get(key, RESUME_MAP["default"])


def generate_cover_letter(company: str, role: str, jd_keywords: list[str] | None = None) -> str:
    """Generate a cover letter template from Lex's verified skills and the job description."""
    _resume_file = get_resume_for_company(company)  # reserved: future resume-tailoring logic
    matched_skills = []
    if jd_keywords:
        all_skills = LEX_SKILLS["languages"] + LEX_SKILLS["frameworks"] + LEX_SKILLS["ai_ml"] + LEX_SKILLS["practices"]  # type: ignore[operator]
        matched_skills = [
            s for s in all_skills if any(k.lower() in s.lower() or s.lower() in k.lower() for k in jd_keywords)
        ]

    skills_line = (
        ", ".join(matched_skills[:6])
        if matched_skills
        else "Python, FastAPI, PostgreSQL, Docker, REST APIs, AI/ML pipelines"
    )

    return f"""Dear {company} Hiring Team,

I'm Alexander (Lex) Santiago, an Information Systems student at NJIT applying for the {role} position. I'm writing because my production experience building and shipping real AI systems aligns directly with what {company} does.

Since starting at NJIT I've been running a freelance software engineering business (LexMakesIt). I've shipped a production AI phone receptionist — FastAPI + OpenAI GPT + RAG + PostgreSQL + Redis — that handles real-time appointment scheduling and after-hours calls 24/7 for actual clients. I've also built a real-time inventory platform integrating SAP ARP with Lightspeed POS for a retail client across 140+ SKUs and multiple locations. Most recently I built Agentop, a local-first multi-agent AI orchestration system with LangGraph, a custom lex-v2 LLM router, and 47 tools.

The skills I'd bring to this role: {skills_line}.

I'm not a student who only has coursework. I have real production deployments, paying clients, and a GitHub full of shipped code (github.com/as4584). I'd be glad to walk through any of it live.

Resume attached. Portfolio: lexmakesit.com | GitHub: github.com/as4584

Thank you for your time,
Alexander (Lex) Santiago
as42519256@gmail.com | Newark, NJ
"""


def export_applications_csv(output_path: str = "/tmp/job_applications.csv") -> str:
    """Export all tracked applications to CSV."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT * FROM applications ORDER BY created_at DESC").fetchall()
    conn.close()
    header = "id,company,role,url,status,resume_used,applied_date,follow_up_date,notes,created_at\n"
    lines = [header] + [",".join(f'"{str(c)}"' for c in row) + "\n" for row in rows]
    with open(output_path, "w") as f:
        f.writelines(lines)
    return output_path


def get_skill_info() -> dict:
    return {
        "id": "job_application",
        "name": "Job Application Engine",
        "candidate": "Alexander (Lex) Santiago",
        "resumes_available": list(RESUME_MAP.keys()),
        "verified_skills_count": sum(len(v) if isinstance(v, list) else len(v) for v in LEX_SKILLS.values()),
        "db_path": str(DB_PATH),
    }
