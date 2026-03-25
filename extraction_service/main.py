from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Dict, Optional
import uuid
import logging
from uuid import uuid4
from core.state import ExtractionRequest, ExtractionResponse, ExtractionState
from core.graph import create_extraction_graph
from core.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("extraction-service")

app = FastAPI(title="ExamFlow Extraction Service", version="1.0.0")

# Simple in-memory job store
jobs: Dict[str, Dict] = {}


def run_extraction_job(job_id: str, request: ExtractionRequest):
    """Run the extraction graph in background"""
    try:
        logger.info(f"Starting job {job_id} for file {request.file_path}")
        
        # Initialize state
        initial_state = {
            "file_path": request.file_path,
            "context": {
                "pattern_id": request.pattern_id,
                "expected_count": request.expected_count,
                "subjects": request.subjects
            },
            # Initialize other required fields
            "full_text": "",
            "chunks": [],
            "extracted_questions": [], 
            "validation_status": "pending",
            "retry_count": 0,
            "error": None
        }
        
        logger.info("Initializing graph...")
        app = create_extraction_graph()
        
        logger.info(f"Invoking graph with state keys: {list(initial_state.keys())}")
        final_state = app.invoke(initial_state)
        
        logger.info("Graph execution completed")
        
        if final_state.get("error"):
            logger.error(f"Graph returned error: {final_state['error']}")
            jobs[job_id] = {
                "status": "failed",
                "error": final_state["error"]
            }
        else:
            # Extract results
            questions = final_state.get("extracted_questions", [])
            completeness = final_state.get("completeness", 0.0)
            
            jobs[job_id] = {
                "status": "completed",
                "result": {
                    "questions": questions,
                    "metadata": {
                        "total": len(questions),
                        "completeness": completeness
                    }
                }
            }
            logger.info(f"Job {job_id} completed successfully with {len(questions)} questions")
            
    except Exception as e:
        logger.error(f"Job {job_id} failed with exception: {str(e)}", exc_info=True)
        jobs[job_id] = {
            "status": "failed",
            "error": str(e)
        }

@app.post("/extract", response_model=Dict)
async def extract_questions(request: ExtractionRequest, background_tasks: BackgroundTasks):
    """Start extraction job"""
    job_id = request.job_id or str(uuid4())
    
    # Store initial status
    jobs[job_id] = {"status": "processing"}
    
    # Start background task
    background_tasks.add_task(run_extraction_job, job_id, request)
    
    return {"job_id": job_id, "status": "processing"}

@app.get("/jobs/{job_id}", response_model=Dict)
async def get_job_status(job_id: str):
    """Get job status"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
        
    return jobs[job_id]

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
