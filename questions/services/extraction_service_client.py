import requests
import json
import logging
from django.conf import settings
from typing import Dict, Any, Optional

logger = logging.getLogger('extraction')

class ExtractionServiceClient:
    """Client for interacting with the separate Extraction Microservice"""
    
    def __init__(self):
        # Default to localhost:8020 if not set
        self.base_url = getattr(settings, 'EXTRACTION_SERVICE_URL', 'http://localhost:8020')
        self.api_key = getattr(settings, 'EXTRACTION_SERVICE_API_KEY', '')
    
    def submit_extraction(self, file_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit a file for extraction
        
        Args:
            file_path: Absolute path to the file (must be accessible by service)
            context: Extraction context (pattern, expected count, etc)
            
        Returns:
            Dict containing job_id and status
        """
        url = f"{self.base_url}/extract"
        
        payload = {
            "file_path": file_path,
            "pattern_id": str(context.get('pattern_id', '')),
            "expected_count": context.get('expected_question_count', 0),
            "subjects": context.get('subjects', []),
            "job_id": str(context.get('job_id')) if context.get('job_id') else None
        }
        
        try:
            logger.info(f"Submitting extraction job to {url}")
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to submit extraction job: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response: {e.response.text}")
            raise Exception(f"Extraction service unavailable: {str(e)}")

    def get_status(self, job_id: str) -> Dict[str, Any]:
        """Get status of an extraction job"""
        url = f"{self.base_url}/jobs/{job_id}"
        
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get job status: {e}")
            raise Exception(f"Failed to check status: {str(e)}")

# Singleton instance
extraction_client = ExtractionServiceClient()
