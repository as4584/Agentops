## ContentRoutes FastAPI Router Specification

### 1. Python Interface

```python
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel

class BrandIntake(BaseModel):
    brand_name: str
    brand_voice: str
    target_audience: str
    content_pillars: List[str]
    platforms: List[str]
    posting_frequency: str

class JobSummaryResponse(BaseModel):
    id: str
    topic: str
    status: str
    platform_targets: List[str]
    created_at: datetime
    updated_at: datetime

class JobDetailResponse(BaseModel):
    id: str
    topic: str
    status: str
    platform_targets: List[str]
    created_at: datetime
    updated_at: datetime
    script: Optional[str] = None
    assets: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

class RejectBody(BaseModel):
    reason: str

class RetryBody(BaseModel):
    restart_from: str

class IntakeStatus(BaseModel):
    status: str

class StatusSummary(BaseModel):
    counts: Dict[str, int]

class CalendarItem(BaseModel):
    job_id: str
    topic: str
    status: str
    scheduled_time: datetime
    platform_targets: List[str]

class ContentRoutes:
    def __init__(self, router: APIRouter, pipeline, job_store):
        self.router = router
        self.pipeline = pipeline
        self.job_store = job_store
        
    def register_routes(self):
        """Register all content endpoints"""
        pass
        
    def list_content_jobs(self) -> List[JobSummaryResponse]:
        """GET /content/jobs"""
        pass
        
    def get_content_job(self, job_id: str) -> JobDetailResponse:
        """GET /content/jobs/{job_id}"""
        pass
        
    def approve_content_job(self, job_id: str) -> Dict[str, str]:
        """POST /content/jobs/{job_id}/approve"""
        pass
        
    def reject_content_job(self, job_id: str, reason: RejectBody) -> Dict[str, str]:
        """POST /content/jobs/{job_id}/reject"""
        pass
        
    def retry_content_job(self, job_id: str, restart_from: RetryBody) -> Dict[str, str]:
        """POST /content/jobs/{job_id}/retry"""
        pass
        
    def run_content_pipeline(self, background_tasks: BackgroundTasks) -> Dict[str, str]:
        """POST /content/run"""
        pass
        
    def get_content_status(self) -> StatusSummary:
        """GET /content/status"""
        pass
        
    def save_intake(self, intake: BrandIntake) -> IntakeStatus:
        """POST /content/intake"""
        pass
        
    def get_intake(self) -> BrandIntake:
        """GET /content/intake"""
        pass
        
    def get_content_calendar(self) -> List[CalendarItem]:
        """GET /content/calendar"""
        pass
```

### 2. Core Logic - Step by Step

#### initialize():
1. Create APIRouter instance with prefix='/content'
2. Set up dependency injection for pipeline and job_store
3. Cache intake file path: `backend/memory/social_intake/brand_intake.json`

#### register_routes():
1. Add GET /content/jobs → list_content_jobs()
2. Add GET /content/jobs/{job_id} → get_content_job()
3. Add POST /content/jobs/{job_id}/approve → approve_content_job()
4. Add POST /content/jobs/{job_id}/reject → reject_content_job()
5. Add POST /content/jobs/{job_id}/retry → retry_content_job()
6. Add POST /content/run → run_content_pipeline()
7. Add GET /content/status → get_content_status()
8. Add POST /content/intake → save_intake()
9. Add GET /content/intake → get_intake()
10. Add GET /content/calendar → get_content_calendar()

#### list_content_jobs():
1. Call job_store.list_all_jobs()
2. For each job, extract: id, topic, status, platform_targets, created_at, updated_at
3. Return as List[JobSummaryResponse]

#### get_content_job(job_id):
1. Call job_store.get_job(job_id)
2. If None → raise HTTPException(404, "Job not found")
3. Return full job dict as JobDetailResponse

#### approve_content_job(job_id):
1. Validate job exists via job_store.get_job(job_id)
2. If None → raise HTTPException(404, "Job not found")
3. Call pipeline.approve_job(job_id)
4. Return {"status": "approved"}

#### reject_content_job(job_id, reason):
1. Validate job exists and body.reason is non-empty
2. If job not found → raise HTTPException(404)
3. Call pipeline.reject_job(job_id, reason.reason)
4. Return {"status": "rejected"}

#### retry_content_job(job_id, restart_from):
1. Validate job exists and body.restart_from is non-empty
2. If job not found → raise HTTPException(404)
3. Call pipeline.retry_job(job_id, restart_from.restart_from)
4. Return {"status": "retrying"}

#### run_content_pipeline(background_tasks):
1. background_tasks.add_task(pipeline.run_full)
2. Return {"status": "started"}

#### get_content_status():
1. Call pipeline.get_status_summary()
2. Return StatusSummary with the counts dict

#### save_intake(intake):
1. Open brand_intake.json in write mode
2. Use json.dump to serialize intake.model_dump()
3. Return {"status": "saved"}

#### get_intake():
1. Check if brand_intake.json exists
2. If not found → raise HTTPException(404, "No intake found")
3. Read and parse JSON into BrandIntake
4. Return BrandIntake model

#### get_content_calendar():
1. Call job_store.list_all_jobs()
2. Filter for jobs with scheduled_time field
3. Sort by scheduled_time ascending
4. For each, extract: job_id, topic, status, scheduled_time, platform_targets
5. Return List[CalendarItem]

### 3. Edge Cases to Handle

1. **Invalid job_id formats** - must return 400 if job_id is not a valid UUID
2. **Missing job on actions** - return 404 for approve/reject/retry of non-existent job
3. **Concurrent job updates** - handle race conditions gracefully by relying on job_store atomicity
4. **Malformed intake JSON** - handle JSON decode errors and return 500 with meaningful message
5. **Missing intake file** - return 404 for GET /content/intake when file doesn't exist
6. **Background task failures** - run_full() exceptions won't be visible to client (as expected with BackgroundTasks)
7. **Empty job store** - return empty list rather than error for GET /content/jobs with no jobs
8. **Invalid job states** - allow reject/retry even if job is in processing state (pipeline handles state validation)

### 4. What It Must NOT Do

1. Must NOT implement authentication or authorization
2. Must NOT validate brand intake data beyond Pydantic model validation
3. Must NOT persist anything except to specified brand_intake.json
4. Must NOT create or modify VideoJobs directly (only via pipeline)
5. Must NOT process the video generation pipeline
6. Must NOT handle file uploads or asset management
7. Must NOT implement real-time websockets or event streaming
8. Must NOT implement any caching beyond router-level caching
9. Must NOT process or store user credentials
10. Must NOT validate platform-specific content rules
11. Must NOT implement pagination for job listings
12. Must NOT implement filtering or search for jobs
13. Must NOT handle duplicate intake saves (overwrite is ok)
14. Must NOT implement job scheduling logic (that's the pipeline's job)
15. Must NOT implement notification mechanisms