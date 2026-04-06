# Job Application Engine Skill

Agentop skill for running Lex's job search campaign. Uses verified skills from the repo and GitHub (as4584) only — no fabricated credentials.

## What This Skill Does

| Capability | Description |
|---|---|
| `search_jobs` | Queries job boards for NJ/NYC roles matching Lex's stack |
| `tailor_resume` | Picks the right tailored resume for a given company/role |
| `generate_cover_letter` | Drafts a cover letter from job description + Lex's real projects |
| `track_application` | Logs application to SQLite with status, date, follow-up reminder |
| `research_scholarships` | Searches NJIT, NJ state, and CS-specific scholarships |
| `export_applications` | Exports tracker to CSV for review |

## Tailored Resumes Available
| Company | File |
|---|---|
| Master (updated with Agentop) | `Alexander_Santiago_Resume_Updated.docx` |
| Epic (EHR/patient systems) | `Alexander_Santiago_Epic.docx` |
| EarthCam (AI SaaS backend) | `Alexander_Santiago_EarthCam.docx` |
| FDM Group (consulting) | `Alexander_Santiago_FDM.docx` |
| Camarès Inc. (ERP/CRM integration) | `Alexander_Santiago_Camares.docx` |
| Brand Experience Lab (AI/IoT retail) | `Alexander_Santiago_BEL.docx` |
| Unique Comp Inc. (enterprise systems) | `Alexander_Santiago_UCI.docx` |

## Verified Skills (GitHub: as4584)
Repos confirmed: Agentop, ai-receptionist-gemini-fastapi, Vendora, reflectai, Restaurant_app, IS218 Modules 10–13, lexmakesit, cookie-cutter-receptionist, Full-Stack-app, SigmaSimulator

## Usage via Agentop
```
POST /chat
{
  "agent": "gsd",
  "message": "Use the job_application skill to search for 10 backend developer roles in NJ and add them to my tracker"
}
```

## Agent Commands
- `apply job_application.search_jobs location="NJ" role="backend developer" limit=10`
- `apply job_application.tailor_resume company="EarthCam" jd="<job description>"`
- `apply job_application.generate_cover_letter company="EarthCam" role="Senior Backend Developer"`
- `apply job_application.track_application company="EarthCam" role="Senior Backend Developer" url="..." status="applied"`
- `apply job_application.research_scholarships type="STEM" school="NJIT"`
