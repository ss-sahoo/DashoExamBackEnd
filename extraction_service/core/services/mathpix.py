import os
import requests
import time
import logging
from typing import Optional, Dict, Tuple
from core.config import settings

logger = logging.getLogger("extraction-service")

class MathpixService:
    API_URL = "https://api.mathpix.com/v3/pdf"
    
    def __init__(self):
        self.app_id = settings.MATHPIX_APP_ID
        self.app_key = settings.MATHPIX_APP_KEY
        self.headers = {
            "app_id": self.app_id,
            "app_key": self.app_key
        }

    def extract_pdf(self, file_path: str, options: Optional[Dict] = None) -> str:
        """Extract text from PDF using Mathpix"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
            
        try:
            # simple implementation without polling for brevity in this step, 
            # ideally should poll like the original code
            # Reusing the logic from original code loosely
            
            with open(file_path, 'rb') as f:
                files = {'file': (os.path.basename(file_path), f, 'application/pdf')}
                data = {'options_json': '{"conversion_formats": {"md": true}, "math_inline_delimiters": ["$", "$"], "math_display_delimiters": ["$$", "$$"], "rm_spaces": true}'}
                
                logger.info(f"Uploading PDF to Mathpix: {file_path}")
                response = requests.post(self.API_URL, headers=self.headers, files=files, data=data, timeout=60)
                
            if response.status_code != 200:
                raise Exception(f"Mathpix upload failed: {response.text}")
                
            pdf_id = response.json().get('pdf_id')
            if not pdf_id:
                raise Exception("No PDF ID returned")
                
            # Poll for completion
            status_url = f"{self.API_URL}/{pdf_id}"
            start_time = time.time()
            while time.time() - start_time < 300:
                time.sleep(2)
                status_resp = requests.get(status_url, headers=self.headers)
                status = status_resp.json().get('status')
                
                if status == 'completed':
                    break
                elif status == 'error':
                    raise Exception(f"Mathpix processing error: {status_resp.text}")
            else:
                raise Exception("Mathpix timeout")
                
            # Get result
            md_url = f"{self.API_URL}/{pdf_id}.md"
            res = requests.get(md_url, headers=self.headers)
            if res.status_code == 200:
                return res.text
            
            # Fallback
            return requests.get(f"{self.API_URL}/{pdf_id}.txt", headers=self.headers).text
            
        except Exception as e:
            logger.error(f"Mathpix failed: {e}")
            raise

mathpix_service = MathpixService()
