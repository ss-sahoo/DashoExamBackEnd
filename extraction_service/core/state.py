from typing import List, Dict, Optional, Annotated, TypedDict
from pydantic import BaseModel, Field

# Using TypedDict for LangGraph compatibility
class Question(BaseModel):
    question_number: int
    question_text: str
    question_type: str = "single_mcq"
    options: List[str] = Field(default_factory=list)
    correct_answer: str = ""
    solution: str = ""
    confidence: float = 0.0

class Chunk(BaseModel):
    text: str
    start_q: int
    end_q: int

class ExtractionState(TypedDict):
    # Inputs
    file_path: str
    file_type: str
    context: Dict  # {pattern, expected_count, etc}
    
    # Processing
    full_text: Optional[str]
    pages: List[str]
    images: List[str]
    has_latex: bool
    
    # Chunking
    chunks: List[Chunk]
    
    # Extraction
    extracted_questions: List[Question]
    unmapped_questions: List[Dict]
    
    # Validation
    completeness: float
    validation_status: str
    retry_count: int
    
    # Errors
    error: Optional[str]

# Simple input/output models for API
class ExtractionRequest(BaseModel):
    file_path: str
    pattern_id: str
    expected_count: int = 0
    subjects: List[str] = []
    job_id: Optional[str] = None

class ExtractionResponse(BaseModel):
    job_id: str
    status: str
    questions: List[Dict]
    metadata: Dict
