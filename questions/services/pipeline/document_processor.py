"""
Stage 1: Document Processor
Converts uploaded files (PDF, DOCX, TXT, images) into structured text + images.
Uses existing FileParserService and Mathpix for OCR.
"""
import os
import re
import hashlib
import logging
from typing import Dict, Optional, List
from pathlib import Path

logger = logging.getLogger('extraction')


class DocumentProcessorError(Exception):
    """Raised when document processing fails"""
    pass


class DocumentProcessor:
    """
    Stage 1 of the extraction pipeline.
    
    Converts uploaded files into a structured document dict containing:
    - full_text: Complete extracted text
    - pages: Per-page text (if available)
    - images: Extracted image paths
    - metadata: File info, page count, text length
    - text_hash: SHA256 hash of the full text for caching
    """
    
    MAX_FILE_SIZE_MB = 50
    
    def __init__(self):
        self._file_parser = None
        self._mathpix_service = None
    
    @property
    def file_parser(self):
        """Lazy-load existing FileParserService"""
        if self._file_parser is None:
            from questions.services.file_parser import FileParserService
            self._file_parser = FileParserService()
        return self._file_parser
    
    @property
    def mathpix_service(self):
        """Lazy-load existing MathpixService"""
        if self._mathpix_service is None:
            try:
                from questions.services.mathpix_service import MathpixService
                self._mathpix_service = MathpixService()
            except Exception as e:
                logger.warning(f"Mathpix service unavailable: {e}")
        return self._mathpix_service
    
    def process(self, file_path: str, file_type: str = '') -> Dict:
        """
        Process a file and extract all text content.
        
        Args:
            file_path: Absolute path to the uploaded file
            file_type: MIME type (auto-detected if empty)
            
        Returns:
            {
                'full_text': str,
                'pages': [str, ...],
                'images': [str, ...],
                'metadata': {
                    'file_name': str,
                    'file_type': str,
                    'file_size': int,
                    'page_count': int,
                    'text_length': int,
                    'has_images': bool,
                    'has_latex': bool,
                    'text_hash': str,
                }
            }
        """
        logger.info(f"[Stage 1] Processing document: {file_path}")
        
        # Validate file exists
        if not os.path.exists(file_path):
            raise DocumentProcessorError(f"File not found: {file_path}")
        
        # Validate file size
        file_size = os.path.getsize(file_path)
        max_bytes = self.MAX_FILE_SIZE_MB * 1024 * 1024
        if file_size > max_bytes:
            raise DocumentProcessorError(
                f"File size ({file_size / 1024 / 1024:.1f}MB) exceeds "
                f"maximum ({self.MAX_FILE_SIZE_MB}MB)"
            )
        
        # Auto-detect file type if not provided
        if not file_type:
            file_type = self._detect_file_type(file_path)
        
        # Extract text using existing FileParserService
        try:
            full_text = self.file_parser.parse_file(file_path, file_type)
        except Exception as e:
            raise DocumentProcessorError(f"Text extraction failed: {str(e)}")
        
        if not full_text or not full_text.strip():
            raise DocumentProcessorError("No text content extracted from document")
        
        # Clean the extracted text
        full_text = self._clean_text(full_text)
        
        # Try to extract per-page text if PDF
        pages = self._extract_pages(file_path, file_type)
        
        # Detect images in document
        images = self._detect_images(file_path, file_type)
        
        # Detect LaTeX content
        has_latex = self._detect_latex(full_text)
        
        # Build text hash for caching
        text_hash = hashlib.sha256(full_text.encode('utf-8')).hexdigest()
        
        result = {
            'full_text': full_text,
            'pages': pages,
            'images': images,
            'metadata': {
                'file_name': os.path.basename(file_path),
                'file_type': file_type,
                'file_size': file_size,
                'page_count': len(pages) if pages else 1,
                'text_length': len(full_text),
                'has_images': len(images) > 0,
                'has_latex': has_latex,
                'text_hash': text_hash,
            }
        }
        
        logger.info(
            f"[Stage 1] Document processed: {len(full_text)} chars, "
            f"{len(pages)} pages, {len(images)} images, LaTeX: {has_latex}"
        )
        
        return result
    
    def _detect_file_type(self, file_path: str) -> str:
        """Auto-detect file type from extension"""
        ext = Path(file_path).suffix.lower()
        type_map = {
            '.pdf': 'application/pdf',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.doc': 'application/msword',
            '.txt': 'text/plain',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
        }
        return type_map.get(ext, 'text/plain')
    
    def _clean_text(self, text: str) -> str:
        """Clean extracted text while preserving LaTeX and structure"""
        # Remove excessive blank lines (more than 2 consecutive)
        text = re.sub(r'\n{4,}', '\n\n\n', text)
        
        # Remove null bytes
        text = text.replace('\x00', '')
        
        # Normalize whitespace within lines (but keep newlines)
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            # Collapse multiple spaces but preserve leading whitespace
            leading = len(line) - len(line.lstrip())
            content = re.sub(r'  +', ' ', line.strip())
            cleaned_lines.append(' ' * min(leading, 4) + content)
        
        return '\n'.join(cleaned_lines)
    
    def _extract_pages(self, file_path: str, file_type: str) -> List[str]:
        """Extract per-page text if possible (PDF only)"""
        if not file_path.endswith('.pdf'):
            return []
        
        try:
            import PyPDF2
            pages = []
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text = page.extract_text()
                    if text and text.strip():
                        pages.append(text.strip())
            return pages
        except Exception as e:
            logger.debug(f"Per-page extraction failed: {e}")
            return []
    
    def _detect_images(self, file_path: str, file_type: str) -> List[str]:
        """Detect images in the document (for later Vision API calls)"""
        images = []
        
        if file_type in ['image/jpeg', 'image/png']:
            # The file itself is an image
            images.append(file_path)
        elif file_path.endswith('.pdf'):
            # For PDFs, check if any pages are image-heavy
            try:
                import PyPDF2
                with open(file_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    for i, page in enumerate(reader.pages):
                        text = page.extract_text()
                        # If a page has very little text, it might be image-heavy
                        if text and len(text.strip()) < 50:
                            logger.debug(f"Page {i+1} appears to be image-heavy")
            except Exception:
                pass
        
        return images
    
    def _detect_latex(self, text: str) -> bool:
        """Detect if text contains LaTeX content"""
        latex_patterns = [
            r'\$[^$]+\$',           # Inline math $...$
            r'\$\$[^$]+\$\$',       # Display math $$...$$
            r'\\frac\{',            # Fractions
            r'\\sqrt',              # Square root
            r'\\int',               # Integral
            r'\\sum',               # Summation
            r'\\alpha|\\beta|\\gamma|\\theta|\\pi',  # Greek letters
            r'\\begin\{',           # LaTeX environments
            r'\\[^a-zA-Z]',         # LaTeX commands starting with backslash
        ]
        
        for pattern in latex_patterns:
            if re.search(pattern, text):
                return True
        return False
