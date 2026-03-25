"""
Stage 3: Document Splitter
Splits document text into chunks aligned with section boundaries.
Each chunk is tagged with subject, section type, and expected question range.
"""
import re
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger('extraction')


@dataclass
class DocumentChunk:
    """A chunk of document text ready for extraction"""
    text: str
    subject: str
    section_name: str
    question_type: str
    start_question: int
    end_question: int
    expected_count: int
    chunk_index: int = 0
    total_chunks: int = 1
    marks_per_question: int = 4
    negative_marking: float = 0
    format_description: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


class DocumentSplitter:
    """
    Stage 3 of the extraction pipeline.
    
    Splits the document into chunks that align with section boundaries.
    This is a KEY IMPROVEMENT — the old system split at arbitrary character counts,
    often cutting questions in half. This splitter uses the blueprint from Stage 2
    to split at actual section/subject transitions.
    
    Splitting strategy:
    1. Split by subject first (using subject markers from blueprint)
    2. Within each subject, split by section (MCQ, Numerical, etc.)
    3. Within each section, split by chunk size if section is too large
    """
    
    MAX_CHUNK_QUESTIONS = 30  # Max questions per extraction call
    MAX_CHUNK_CHARS = 25000  # Max characters per chunk
    
    def split(self, full_text: str, blueprint) -> List[DocumentChunk]:
        """
        Split document text into extraction-ready chunks.
        
        Args:
            full_text: Complete document text
            blueprint: DocumentBlueprint from Stage 2
            
        Returns:
            List of DocumentChunk objects, each tagged with subject/type info
        """
        logger.info(f"[Stage 3] Splitting document into chunks...")
        
        chunks = []
        
        # Strategy 1: Split by subject markers if available
        subject_texts = self._split_by_subjects(full_text, blueprint)
        
        chunk_index = 0
        
        for subj in blueprint.subjects:
            subject_text = subject_texts.get(subj.name, '')
            
            if not subject_text.strip():
                logger.warning(f"[Stage 3] No text found for subject: {subj.name}")
                # Assign equal portion of text as fallback
                total_subjects = len(blueprint.subjects)
                if total_subjects > 0:
                    subj_idx = [s.name for s in blueprint.subjects].index(subj.name)
                    chunk_size = len(full_text) // total_subjects
                    start = subj_idx * chunk_size
                    end = start + chunk_size if subj_idx < total_subjects - 1 else len(full_text)
                    subject_text = full_text[start:end]
            
            # Split subject text by sections
            for section in subj.sections:
                section_text = self._extract_section_text(
                    subject_text, section, subj.sections
                )
                
                if not section_text.strip():
                    section_text = subject_text  # Fallback: use full subject text
                
                # Split section into sub-chunks if too large
                sub_chunks = self._split_section_into_chunks(
                    section_text, section, subj.name
                )
                
                for sc_text, sc_start, sc_end in sub_chunks:
                    chunk = DocumentChunk(
                        text=sc_text,
                        subject=subj.name,
                        section_name=section.name,
                        question_type=section.question_type,
                        start_question=sc_start,
                        end_question=sc_end,
                        expected_count=sc_end - sc_start + 1,
                        chunk_index=chunk_index,
                        marks_per_question=section.marks_per_question,
                        negative_marking=section.negative_marking,
                        format_description=section.format_description,
                    )
                    chunks.append(chunk)
                    chunk_index += 1
        
        # Set total_chunks on all chunks
        total = len(chunks)
        for c in chunks:
            c.total_chunks = total
        
        logger.info(
            f"[Stage 3] Document split into {len(chunks)} chunks: " +
            ", ".join(f"{c.subject}/{c.section_name}({c.expected_count}q)" for c in chunks)
        )
        
        return chunks
    
    def _split_by_subjects(self, full_text: str, blueprint) -> Dict[str, str]:
        """Split document text by subject using markers from the blueprint"""
        result = {}
        
        if len(blueprint.subjects) <= 1:
            # Single subject — use entire text
            subj_name = blueprint.subjects[0].name if blueprint.subjects else 'Unknown'
            result[subj_name] = full_text
            return result
        
        # Find subject positions in the text
        subject_positions = []
        text_lower = full_text.lower()
        
        for subj in blueprint.subjects:
            subj_name = subj.name
            subj_lower = subj_name.lower()
            
            # Try multiple patterns to find subject start
            patterns = [
                # Exact header match
                rf'(?:^|\n)\s*(?:#{1,4}\s*)?{re.escape(subj_lower)}\s*(?:\n|$)',
                # With "Subject:" prefix
                rf'(?:^|\n)\s*(?:subject\s*[-:]\s*)?{re.escape(subj_lower)}\s*(?:\n|$)',
                # With separator lines
                rf'(?:^|\n)\s*[-=_]+\s*{re.escape(subj_lower)}\s*[-=_]*\s*(?:\n|$)',
                # Bold/emphasized subjects
                rf'(?:^|\n)\s*\*\*{re.escape(subj_lower)}\*\*',
                # Start position hint from blueprint
            ]
            
            best_pos = -1
            for pattern in patterns:
                match = re.search(pattern, text_lower, re.IGNORECASE | re.MULTILINE)
                if match:
                    best_pos = match.start()
                    break
            
            # Also try the start_position hint from AI analysis
            if best_pos == -1 and subj.start_position:
                hint = subj.start_position.lower()[:80]
                idx = text_lower.find(hint)
                if idx >= 0:
                    best_pos = idx
            
            subject_positions.append({
                'name': subj_name,
                'position': best_pos,
            })
        
        # Sort by position, put -1 (not found) at the end
        found = [sp for sp in subject_positions if sp['position'] >= 0]
        not_found = [sp for sp in subject_positions if sp['position'] < 0]
        
        found.sort(key=lambda x: x['position'])
        ordered = found + not_found
        
        # Extract text for each subject
        for i, sp in enumerate(ordered):
            if sp['position'] < 0:
                # Subject marker not found — will get fallback text
                result[sp['name']] = ''
                continue
            
            start = sp['position']
            
            # End at next subject's start, or end of text
            if i + 1 < len(ordered) and ordered[i + 1]['position'] >= 0:
                end = ordered[i + 1]['position']
            else:
                end = len(full_text)
            
            result[sp['name']] = full_text[start:end].strip()
        
        return result
    
    def _extract_section_text(
        self,
        subject_text: str,
        target_section,
        all_sections: list
    ) -> str:
        """
        Extract text for a specific section within a subject.
        Uses question number markers to find section boundaries.
        """
        if len(all_sections) <= 1:
            return subject_text
        
        start_q = target_section.start_question
        end_q = target_section.end_question
        
        # Find where the target section's questions start
        start_pattern = rf'(?:^|\n)\s*(?:Q\.?\s*)?{start_q}[\.\)\:]'
        end_pattern = None
        
        # Find where the next section starts
        section_idx = all_sections.index(target_section)
        if section_idx + 1 < len(all_sections):
            next_start = all_sections[section_idx + 1].start_question
            end_pattern = rf'(?:^|\n)\s*(?:Q\.?\s*)?{next_start}[\.\)\:]'
        
        # Find start position
        start_match = re.search(start_pattern, subject_text, re.MULTILINE)
        start_pos = start_match.start() if start_match else 0
        
        # Find end position
        if end_pattern:
            end_match = re.search(end_pattern, subject_text[start_pos:], re.MULTILINE)
            end_pos = start_pos + end_match.start() if end_match else len(subject_text)
        else:
            end_pos = len(subject_text)
        
        section_text = subject_text[start_pos:end_pos].strip()
        
        # Also try section name markers
        if not section_text or len(section_text) < 50:
            name_lower = target_section.name.lower()
            for pattern in [
                rf'(?:^|\n)\s*{re.escape(name_lower)}',
                rf'(?:^|\n)\s*section\s+[a-z]',
            ]:
                match = re.search(pattern, subject_text.lower(), re.MULTILINE)
                if match:
                    section_text = subject_text[match.start():end_pos].strip()
                    break
        
        return section_text if section_text else subject_text
    
    def _split_section_into_chunks(
        self,
        section_text: str,
        section,
        subject_name: str
    ) -> List[tuple]:
        """
        Split a section into smaller chunks if it's too large.
        Returns list of (chunk_text, start_q, end_q) tuples.
        """
        total_questions = section.question_count
        
        # If small enough, return as single chunk
        if (total_questions <= self.MAX_CHUNK_QUESTIONS and
                len(section_text) <= self.MAX_CHUNK_CHARS):
            return [(section_text, section.start_question, section.end_question)]
        
        # Need to split into sub-chunks
        chunks = []
        
        if total_questions > self.MAX_CHUNK_QUESTIONS:
            # Split by question number markers
            chunk_size = self.MAX_CHUNK_QUESTIONS
            
            for q_start in range(section.start_question, section.end_question + 1, chunk_size):
                q_end = min(q_start + chunk_size - 1, section.end_question)
                
                # Find text boundaries for this question range
                chunk_text = self._extract_question_range_text(
                    section_text, q_start, q_end, section.end_question
                )
                
                if chunk_text.strip():
                    chunks.append((chunk_text, q_start, q_end))
        else:
            # Split by character count
            mid = len(section_text) // 2
            # Find a good split point (paragraph boundary)
            split_point = section_text.rfind('\n\n', mid - 500, mid + 500)
            if split_point == -1:
                split_point = section_text.rfind('\n', mid - 200, mid + 200)
            if split_point == -1:
                split_point = mid
            
            mid_q = (section.start_question + section.end_question) // 2
            chunks.append((section_text[:split_point], section.start_question, mid_q))
            chunks.append((section_text[split_point:], mid_q + 1, section.end_question))
        
        return chunks if chunks else [(section_text, section.start_question, section.end_question)]
    
    def _extract_question_range_text(
        self,
        text: str,
        start_q: int,
        end_q: int,
        section_end_q: int
    ) -> str:
        """Extract text for a specific question number range"""
        # Find start of start_q
        start_pattern = rf'(?:^|\n)\s*(?:Q\.?\s*)?{start_q}[\.\)\:]'
        start_match = re.search(start_pattern, text, re.MULTILINE)
        start_pos = start_match.start() if start_match else 0
        
        # Find start of the question AFTER end_q
        next_q = end_q + 1
        if next_q <= section_end_q:
            end_pattern = rf'(?:^|\n)\s*(?:Q\.?\s*)?{next_q}[\.\)\:]'
            end_match = re.search(end_pattern, text[start_pos:], re.MULTILINE)
            end_pos = start_pos + end_match.start() if end_match else len(text)
        else:
            end_pos = len(text)
        
        return text[start_pos:end_pos].strip()
