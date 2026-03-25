from core.state import ExtractionState
from core.services.mathpix import mathpix_service
from core.services.gemini import gemini_service
from core.services.chunker import chunker
import logging

logger = logging.getLogger("extraction-service")

def process_document_node(state: ExtractionState) -> dict:
    """Process the document (OCR/Text Extraction)"""
    logger.info(f"Processing document: {state['file_path']}")
    try:
        # Step 1: Extract text using Mathpix (or other OCR)
        text = mathpix_service.extract_pdf(state["file_path"])
        
        # In a real impl, we'd also get pages/images here
        return {
            "full_text": text,
            "validation_status": "processing"
        }
    except Exception as e:
        logger.error(f"Document processing failed: {e}")
        return {
            "error": str(e), 
            "validation_status": "failed"
        }

def split_sections_node(state: ExtractionState) -> dict:
    """Split the document into manageable chunks"""
    if state.get("error"):
        return {}
        
    logger.info("Splitting sections...")
    try:
        expected = state["context"].get("expected_count", 50)
        chunks = chunker.chunk(state["full_text"], expected)
        logger.info(f"Created {len(chunks)} chunks")
        return {"chunks": chunks}
    except Exception as e:
        logger.error(f"Splitting failed: {e}")
        return {"error": str(e)}

def extract_questions_node(state: ExtractionState) -> dict:
    """Run AI extraction on each chunk"""
    if state.get("error"):
        return {}
        
    logger.info("Extracting questions...")
    all_questions = []
    
    try:
        # Parallel extraction could be done here with threads/asyncio
        # For now, sequential
        for i, chunk in enumerate(state["chunks"]):
            logger.info(f"Processing chunk {i+1}/{len(state['chunks'])}")
            
            qs = gemini_service.extract_chunk(
                chunk.text, 
                context={
                    "chunk_idx": i, 
                    "total_chunks": len(state["chunks"]),
                    **state["context"]
                }
            )
            all_questions.extend(qs)
            
        return {"extracted_questions": all_questions}
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        return {"error": str(e)}

def validate_extraction_node(state: ExtractionState) -> dict:
    """Validate completeness and quality"""
    if state.get("error"):
        return {"validation_status": "failed"}
        
    extracted = len(state["extracted_questions"])
    expected = state["context"].get("expected_count", 0)
    
    completeness = extracted / expected if expected > 0 else 0
    status = "completed" if completeness >= 0.9 else "partial"
    
    logger.info(f"Validation complete: {extracted}/{expected} ({completeness:.1%}) - {status}")
    
    return {
        "completeness": completeness,
        "validation_status": status
    }
