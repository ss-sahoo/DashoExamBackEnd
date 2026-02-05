import logging
import os
import google.generativeai as genai
from typing import Optional, Dict, Tuple
from django.conf import settings
from PIL import Image

logger = logging.getLogger('extraction')

class GeminiOCRError(Exception):
    """Raised when Gemini OCR fails"""
    pass

class GeminiOCRService:
    """
    OCR service using Google Gemini Pro Vision.
    Provides fallback capabilities when Mathpix is unavailable.
    """
    
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        """Initialize Gemini OCR service"""
        self.api_key = api_key or getattr(settings, 'GEMINI_API_KEY', None) or os.environ.get('GEMINI_API_KEY')
        self.model_name = model_name or getattr(settings, 'GEMINI_MODEL', None) or os.environ.get('GEMINI_MODEL') or "gemini-2.0-flash"
        
        if not self.api_key:
            raise GeminiOCRError("Gemini API key not configured. Set GEMINI_API_KEY in settings or environment.")
            
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(self.model_name)
        
    def extract_image(self, file_path: str, prompt: Optional[str] = None) -> str:
        """
        Extract text from image using Gemini API.
        
        Args:
            file_path: Path to the image file
            prompt: Optional custom prompt for extraction
            
        Returns:
            Extracted text content with LaTeX preserved
        """
        if not os.path.exists(file_path):
            raise GeminiOCRError(f"File not found: {file_path}")
            
        logger.info(f"Starting Gemini OCR extraction for: {file_path}")
        
        try:
            image = Image.open(file_path)
            
            # Optimized prompt for mathematical question extraction
            default_prompt = (
                "Transcribe the text in this image. "
                "If there is any mathematical notation, use LaTeX format with $ for inline math and $$ for block math. "
                "Preserve the structure of the question, including options if present. "
                "Output only the transcribed text."
            )
            
            final_prompt = prompt or default_prompt
            
            response = self.model.generate_content(
                [final_prompt, image],
                generation_config={
                    'temperature': 0.1,  # Low temperature for accuracy
                    'top_p': 0.95,
                    'max_output_tokens': 2048,
                }
            )
            
            if not response.text:
                raise GeminiOCRError("Gemini returned empty response for OCR")
                
            logger.info(f"Successfully extracted {len(response.text)} characters from image using Gemini")
            return response.text
            
        except Exception as e:
            logger.error(f"Gemini OCR failed: {str(e)}")
            raise GeminiOCRError(f"Failed to extract text using Gemini: {str(e)}")
            
    def extract_pdf(self, file_path: str, prompt: Optional[str] = None) -> str:
        """
        Extract text from PDF using Gemini API.
        This is particularly useful for scanned PDFs where PyPDF2 fails.
        """
        if not os.path.exists(file_path):
            raise GeminiOCRError(f"File not found: {file_path}")
            
        logger.info(f"Starting Gemini PDF extraction for: {file_path}")
        
        try:
            # For Gemini, the best way to handle PDFs is to upload them
            # Check if file is small enough for direct upload or needs File API
            # For simplicity, we'll use the File API upload approach which supports multi-page PDFs
            
            uploaded_file = genai.upload_file(path=file_path, mime_type="application/pdf")
            
            # Wait for the file to be processed if necessary (usually instant for small PDFs)
            # Standard prompt for PDF question extraction
            default_prompt = (
                "Transcribe all text from this PDF document. "
                "If there are any mathematical equations or chemical formulas, use LaTeX format (e.g., $E=mc^2$). "
                "Keep the flow of the document. "
                "Output only the transcribed content without any extra commentary."
            )
            
            final_prompt = prompt or default_prompt
            
            response = self.model.generate_content(
                [final_prompt, uploaded_file],
                generation_config={
                    'temperature': 0.1,
                    'top_p': 0.95,
                    'max_output_tokens': 8192, # Allow for more content in PDFs
                }
            )
            
            # Cleanup: Files are active for 48 hours by default, but we can't easily delete here 
            # without keeping track of the URI. The API doesn't support immediate deletion 
            # as easily as one would hope without extra steps.
            
            if not response.text:
                raise GeminiOCRError("Gemini returned empty response for PDF OCR")
                
            logger.info(f"Successfully extracted {len(response.text)} characters from PDF using Gemini")
            return response.text
            
        except Exception as e:
            logger.error(f"Gemini PDF OCR failed: {str(e)}")
            raise GeminiOCRError(f"Failed to extract PDF text using Gemini: {str(e)}")

    @staticmethod
    def is_configured() -> bool:
        """Check if Gemini is configured"""
        return bool(getattr(settings, 'GEMINI_API_KEY', None) or os.environ.get('GEMINI_API_KEY'))
