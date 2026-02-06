"""
Mathpix OCR Service for PDF text extraction
Uses Mathpix API to extract text, math equations (LaTeX), and tables from PDFs

Enhanced with caching support via OCRResult model to avoid redundant API calls.
"""
import os
import time
import hashlib
import logging
import requests
from typing import Optional, Dict, Tuple, TYPE_CHECKING
from django.conf import settings
from django.utils import timezone

if TYPE_CHECKING:
    from questions.models import OCRResult

logger = logging.getLogger('extraction')


class MathpixError(Exception):
    """Raised when Mathpix API call fails"""
    pass


class MathpixService:
    """
    Mathpix OCR service for extracting text from PDFs
    
    Features:
    - High-quality OCR for scanned PDFs
    - LaTeX extraction for mathematical equations
    - Table recognition and extraction
    - Supports large PDFs with multiple pages
    """
    
    API_URL = "https://api.mathpix.com/v3/pdf"
    POLL_INTERVAL = 3  # seconds between status checks
    MAX_WAIT_TIME = 300  # 5 minutes max wait
    
    def __init__(self, app_id: Optional[str] = None, app_key: Optional[str] = None):
        """Initialize Mathpix service with credentials"""
        self.app_id = app_id or getattr(settings, 'MATHPIX_APP_ID', None) or os.environ.get('MATHPIX_APP_ID')
        self.app_key = app_key or getattr(settings, 'MATHPIX_APP_KEY', None) or os.environ.get('MATHPIX_APP_KEY')
        
        if not self.app_id or not self.app_key:
            raise MathpixError(
                "Mathpix credentials not configured. "
                "Set MATHPIX_APP_ID and MATHPIX_APP_KEY in environment or settings."
            )
        
        self.headers = {
            "app_id": self.app_id,
            "app_key": self.app_key
        }
    
    def extract_pdf(self, file_path: str, options: Optional[Dict] = None) -> str:
        """
        Extract text content from PDF using Mathpix API
        
        Args:
            file_path: Path to the PDF file
            options: Optional extraction options
            
        Returns:
            Extracted text content with LaTeX preserved
            
        Raises:
            MathpixError: If extraction fails
        """
        if not os.path.exists(file_path):
            raise MathpixError(f"File not found: {file_path}")
        
        logger.info(f"Starting Mathpix PDF extraction for: {file_path}")
        
        try:
            # Step 1: Upload PDF and start processing
            pdf_id = self._upload_pdf(file_path, options)
            logger.info(f"PDF uploaded successfully, ID: {pdf_id}")
            
            # Step 2: Wait for processing to complete
            self._wait_for_completion(pdf_id)
            logger.info(f"PDF processing completed for ID: {pdf_id}")
            
            # Step 3: Get the extracted text
            text_content = self._get_text_result(pdf_id)
            logger.info(f"Extracted {len(text_content)} characters from PDF")
            
            return text_content
            
        except MathpixError:
            raise
        except Exception as e:
            logger.error(f"Mathpix extraction failed: {str(e)}")
            raise MathpixError(f"Failed to extract PDF: {str(e)}")
    
    def _upload_pdf(self, file_path: str, options: Optional[Dict] = None) -> str:
        """Upload PDF to Mathpix and get processing ID"""
        
        # Default options for question extraction
        default_options = {
            "conversion_formats": {"md": True},  # Get markdown output
            "math_inline_delimiters": ["$", "$"],
            "math_display_delimiters": ["$$", "$$"],
            "rm_spaces": True,
            "enable_tables_fallback": True,
        }
        
        if options:
            default_options.update(options)
        
        with open(file_path, 'rb') as f:
            files = {
                'file': (os.path.basename(file_path), f, 'application/pdf')
            }
            data = {
                'options_json': str(default_options).replace("'", '"').replace("True", "true").replace("False", "false")
            }
            
            response = requests.post(
                self.API_URL,
                headers=self.headers,
                files=files,
                data=data,
                timeout=60
            )
        
        if response.status_code != 200:
            error_msg = response.json().get('error', response.text)
            raise MathpixError(f"Failed to upload PDF: {error_msg}")
        
        result = response.json()
        pdf_id = result.get('pdf_id')
        
        if not pdf_id:
            raise MathpixError("No PDF ID returned from Mathpix")
        
        return pdf_id
    
    def _wait_for_completion(self, pdf_id: str) -> None:
        """Poll Mathpix API until PDF processing is complete"""
        
        status_url = f"{self.API_URL}/{pdf_id}"
        start_time = time.time()
        
        while True:
            elapsed = time.time() - start_time
            if elapsed > self.MAX_WAIT_TIME:
                raise MathpixError(f"PDF processing timed out after {self.MAX_WAIT_TIME} seconds")
            
            response = requests.get(status_url, headers=self.headers, timeout=30)
            
            if response.status_code != 200:
                raise MathpixError(f"Failed to check PDF status: {response.text}")
            
            result = response.json()
            status = result.get('status')
            
            logger.debug(f"PDF {pdf_id} status: {status}")
            
            if status == 'completed':
                return
            elif status == 'error':
                error_msg = result.get('error', 'Unknown error')
                raise MathpixError(f"PDF processing failed: {error_msg}")
            elif status in ['split', 'processing']:
                # Still processing, wait and retry
                time.sleep(self.POLL_INTERVAL)
            else:
                # Unknown status, wait and retry
                logger.warning(f"Unknown PDF status: {status}")
                time.sleep(self.POLL_INTERVAL)
    
    def _get_text_result(self, pdf_id: str) -> str:
        """Get the extracted text/markdown from processed PDF"""
        
        # Try to get markdown output first (best for questions with math)
        md_url = f"{self.API_URL}/{pdf_id}.md"
        
        response = requests.get(md_url, headers=self.headers, timeout=60)
        
        if response.status_code == 200:
            return response.text
        
        # Fallback to plain text
        txt_url = f"{self.API_URL}/{pdf_id}.txt"
        response = requests.get(txt_url, headers=self.headers, timeout=60)
        
        if response.status_code == 200:
            return response.text
        
        # Last resort: get JSON and extract text
        json_url = f"{self.API_URL}/{pdf_id}"
        response = requests.get(json_url, headers=self.headers, timeout=60)
        
        if response.status_code != 200:
            raise MathpixError(f"Failed to get extraction result: {response.text}")
        
        result = response.json()
        
        # Extract text from pages
        pages = result.get('pages', [])
        text_parts = []
        
        for page in pages:
            page_text = page.get('text', '')
            if page_text:
                text_parts.append(page_text)
        
        if not text_parts:
            raise MathpixError("No text content extracted from PDF")
        
        return '\n\n'.join(text_parts)
    
    def extract_image(self, file_path: str) -> str:
        """
        Extract text from image using Mathpix API
        
        Args:
            file_path: Path to the image file
            
        Returns:
            Extracted text content with LaTeX preserved
        """
        if not os.path.exists(file_path):
            raise MathpixError(f"File not found: {file_path}")
        
        logger.info(f"Starting Mathpix image extraction for: {file_path}")
        
        image_url = "https://api.mathpix.com/v3/text"
        
        # Determine content type
        ext = os.path.splitext(file_path)[1].lower()
        content_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.webp': 'image/webp'
        }
        content_type = content_types.get(ext, 'image/jpeg')
        
        with open(file_path, 'rb') as f:
            files = {
                'file': (os.path.basename(file_path), f, content_type)
            }
            data = {
                'options_json': '{"math_inline_delimiters": ["$", "$"], "math_display_delimiters": ["$$", "$$"], "rm_spaces": true}'
            }
            
            response = requests.post(
                image_url,
                headers=self.headers,
                files=files,
                data=data,
                timeout=60
            )
        
        if response.status_code != 200:
            error_msg = response.json().get('error', response.text)
            raise MathpixError(f"Failed to extract image: {error_msg}")
        
        result = response.json()
        text = result.get('text', '')
        
        if not text:
            # Try latex_styled if text is empty
            text = result.get('latex_styled', '')
        
        if not text:
            raise MathpixError("No text content extracted from image")
        
        logger.info(f"Extracted {len(text)} characters from image")
        return text
    
    def get_usage(self) -> Dict:
        """Get current API usage statistics"""
        usage_url = "https://api.mathpix.com/v3/usage"
        
        response = requests.get(usage_url, headers=self.headers, timeout=30)
        
        if response.status_code != 200:
            raise MathpixError(f"Failed to get usage: {response.text}")
        
        return response.json()
    
    # ===========================
    # Caching Methods
    # ===========================
    
    @staticmethod
    def _compute_file_hash(file_path: str) -> str:
        """
        Compute SHA256 hash of a file for deduplication.
        
        Args:
            file_path: Path to the file
            
        Returns:
            SHA256 hash as hex string
        """
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            # Read in 64KB chunks for memory efficiency
            for byte_block in iter(lambda: f.read(65536), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def extract_pdf_with_cache(
        self, 
        file_path: str, 
        options: Optional[Dict] = None
    ) -> Tuple[str, 'OCRResult']:
        """
        Extract text from PDF with caching support.
        
        If the file has been previously processed, returns cached result.
        Otherwise, processes the file and stores the result.
        
        Args:
            file_path: Path to the PDF file
            options: Optional extraction options
            
        Returns:
            Tuple of (extracted_text, OCRResult instance)
            
        Raises:
            MathpixError: If extraction fails
        """
        from questions.models import OCRResult
        
        if not os.path.exists(file_path):
            raise MathpixError(f"File not found: {file_path}")
        
        # Compute file hash for deduplication
        file_hash = self._compute_file_hash(file_path)
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        
        logger.info(f"Checking cache for PDF: {file_name} (hash: {file_hash[:16]}...)")
        
        # Check for existing cached result
        cached = OCRResult.get_cached_result(file_hash)
        if cached:
            logger.info(f"Cache HIT: Returning cached OCR result for {file_name}")
            cached.record_access()
            return cached.extracted_text, cached
        
        logger.info(f"Cache MISS: Processing PDF with Mathpix: {file_name}")
        
        # Create OCR result record for tracking
        ocr_result = OCRResult.objects.create(
            file_path=file_path,
            file_hash=file_hash,
            file_size=file_size,
            file_name=file_name,
            ocr_provider='mathpix',
            status='pending'
        )
        
        start_time = time.time()
        
        try:
            # Step 1: Upload PDF
            pdf_id = self._upload_pdf(file_path, options)
            ocr_result.mark_processing(mathpix_pdf_id=pdf_id)
            logger.info(f"PDF uploaded successfully, ID: {pdf_id}")
            
            # Step 2: Wait for completion
            self._wait_for_completion(pdf_id)
            logger.info(f"PDF processing completed for ID: {pdf_id}")
            
            # Step 3: Get result
            text_content = self._get_text_result(pdf_id)
            
            # Step 4: Get page count from metadata
            page_count = self._get_page_count(pdf_id)
            
            processing_time = time.time() - start_time
            
            # Mark as completed and store result
            ocr_result.mark_completed(
                extracted_text=text_content,
                page_count=page_count,
                processing_time=processing_time
            )
            
            logger.info(
                f"Extracted {len(text_content)} characters from {page_count} pages "
                f"in {processing_time:.2f}s - result cached"
            )
            
            return text_content, ocr_result
            
        except MathpixError as e:
            ocr_result.mark_failed(str(e))
            raise
        except Exception as e:
            ocr_result.mark_failed(str(e))
            logger.error(f"Mathpix extraction failed: {str(e)}")
            raise MathpixError(f"Failed to extract PDF: {str(e)}")
    
    def extract_image_with_cache(self, file_path: str) -> Tuple[str, 'OCRResult']:
        """
        Extract text from image with caching support.
        
        Args:
            file_path: Path to the image file
            
        Returns:
            Tuple of (extracted_text, OCRResult instance)
        """
        from questions.models import OCRResult
        
        if not os.path.exists(file_path):
            raise MathpixError(f"File not found: {file_path}")
        
        # Compute file hash
        file_hash = self._compute_file_hash(file_path)
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        
        logger.info(f"Checking cache for image: {file_name} (hash: {file_hash[:16]}...)")
        
        # Check for cached result
        cached = OCRResult.get_cached_result(file_hash)
        if cached:
            logger.info(f"Cache HIT: Returning cached OCR result for {file_name}")
            cached.record_access()
            return cached.extracted_text, cached
        
        logger.info(f"Cache MISS: Processing image with Mathpix: {file_name}")
        
        # Create OCR result record
        ocr_result = OCRResult.objects.create(
            file_path=file_path,
            file_hash=file_hash,
            file_size=file_size,
            file_name=file_name,
            ocr_provider='mathpix',
            status='processing'
        )
        
        start_time = time.time()
        
        try:
            # Extract image (images are processed immediately, no polling needed)
            text_content = self.extract_image(file_path)
            processing_time = time.time() - start_time
            
            # Store result
            ocr_result.mark_completed(
                extracted_text=text_content,
                page_count=1,  # Images are single page
                processing_time=processing_time
            )
            
            logger.info(
                f"Extracted {len(text_content)} characters from image "
                f"in {processing_time:.2f}s - result cached"
            )
            
            return text_content, ocr_result
            
        except MathpixError as e:
            ocr_result.mark_failed(str(e))
            raise
        except Exception as e:
            ocr_result.mark_failed(str(e))
            logger.error(f"Mathpix image extraction failed: {str(e)}")
            raise MathpixError(f"Failed to extract image: {str(e)}")
    
    def _get_page_count(self, pdf_id: str) -> int:
        """Get the page count from Mathpix PDF metadata"""
        try:
            json_url = f"{self.API_URL}/{pdf_id}"
            response = requests.get(json_url, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                return result.get('num_pages', 0) or len(result.get('pages', []))
        except Exception as e:
            logger.warning(f"Failed to get page count: {e}")
        
        return 0
    
    @classmethod
    def get_cached_text(cls, file_path: str) -> Optional[str]:
        """
        Get cached OCR text for a file if available.
        
        This is a convenience method that doesn't require Mathpix credentials.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Cached text content or None if not cached
        """
        from questions.models import OCRResult
        
        if not os.path.exists(file_path):
            return None
        
        file_hash = cls._compute_file_hash(file_path)
        cached = OCRResult.get_cached_result(file_hash)
        
        if cached:
            cached.record_access()
            return cached.extracted_text
        
        return None
