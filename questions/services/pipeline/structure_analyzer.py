"""
Stage 2: Structure Analyzer
Uses AI (Gemini) to analyze document structure BEFORE extraction.
Returns a "blueprint" of subjects, sections, question types, and ranges.
"""
import json
import re
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict
from django.conf import settings

from .prompts import STRUCTURE_ANALYSIS_PROMPT

logger = logging.getLogger('extraction')


class StructureAnalysisError(Exception):
    """Raised when structure analysis fails"""
    pass


@dataclass
class SectionBlueprint:
    """Blueprint for a single section within a subject"""
    name: str
    question_type: str  # single_mcq, multiple_mcq, numerical, etc.
    start_question: int
    end_question: int
    question_count: int
    marks_per_question: int = 4
    negative_marking: float = 0
    format_description: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SubjectBlueprint:
    """Blueprint for a single subject"""
    name: str
    sections: List[SectionBlueprint] = field(default_factory=list)
    start_position: str = ""  # Text marker where this subject begins
    total_questions: int = 0
    
    def to_dict(self) -> Dict:
        d = asdict(self)
        d['sections'] = [s.to_dict() for s in self.sections]
        return d


@dataclass
class DocumentBlueprint:
    """Complete blueprint of the document structure"""
    document_type: str = "questions_with_answers"
    confidence: float = 0.0
    instructions: str = ""
    subjects: List[SubjectBlueprint] = field(default_factory=list)
    total_questions: int = 0
    numbering_format: str = "Q1."
    answer_format: str = "Answer: A"
    matches_pattern: bool = False
    issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        d = asdict(self)
        d['subjects'] = [s.to_dict() for s in self.subjects]
        return d


class StructureAnalyzer:
    """
    Stage 2 of the extraction pipeline.
    
    Analyzes the document to produce a blueprint BEFORE extraction.
    This is the KEY IMPROVEMENT — knowing the structure allows:
    - Splitting by actual section boundaries
    - Using type-specific prompts per section
    - Validating counts against the pattern
    """
    
    def __init__(self):
        self._client = None
        self._model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash')
    
    @property
    def client(self):
        """Lazy-initialize Gemini client"""
        if self._client is None:
            api_key = getattr(settings, 'GEMINI_API_KEY', None)
            if not api_key:
                raise StructureAnalysisError("GEMINI_API_KEY not configured")
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                self._client = genai.GenerativeModel(self._model_name)
            except ImportError:
                raise StructureAnalysisError("google-generativeai not installed")
        return self._client
    
    def analyze(
        self,
        full_text: str,
        pattern,  # ExamPattern model instance
        document_metadata: Optional[Dict] = None
    ) -> Dict:
        """
        Analyze document structure and return a blueprint + validation.
        
        Args:
            full_text: Complete document text
            pattern: ExamPattern model instance
            document_metadata: Optional metadata from Stage 1
            
        Returns:
            {
                'blueprint': DocumentBlueprint,
                'can_proceed': bool,
                'validation': {
                    'matches_pattern': bool,
                    'issues': [...],
                    'subject_match_score': float
                },
                'pattern_comparison': {
                    'expected': {...},
                    'detected': {...},
                    'differences': [...]
                }
            }
        """
        logger.info("[Stage 2] Analyzing document structure...")
        
        # Get pattern info
        pattern_subjects = self._get_pattern_subjects(pattern)
        expected_total = pattern.total_questions
        
        logger.info(
            f"[Stage 2] Pattern expects: {expected_total} questions across "
            f"subjects: {pattern_subjects}"
        )
        
        # Try AI analysis first
        try:
            blueprint = self._ai_analyze(full_text, pattern_subjects, expected_total)
        except Exception as e:
            logger.warning(f"[Stage 2] AI analysis failed: {e}. Using regex fallback.")
            blueprint = self._regex_fallback(full_text, pattern_subjects, expected_total)
        
        # Validate against pattern
        validation = self._validate_against_pattern(blueprint, pattern)
        
        # Build pattern comparison
        pattern_comparison = self._build_pattern_comparison(blueprint, pattern)
        
        can_proceed = validation['matches_pattern'] or validation.get('subject_match_score', 0) >= 0.5
        
        if not can_proceed:
            logger.warning(
                f"[Stage 2] Document structure doesn't match pattern. "
                f"Issues: {validation['issues']}"
            )
        else:
            logger.info(
                f"[Stage 2] Structure analysis complete. "
                f"Detected {blueprint.total_questions} questions across "
                f"{len(blueprint.subjects)} subjects. "
                f"Match score: {validation.get('subject_match_score', 0):.2f}"
            )
        
        return {
            'blueprint': blueprint,
            'can_proceed': can_proceed,
            'validation': validation,
            'pattern_comparison': pattern_comparison,
        }
    
    def _get_pattern_subjects(self, pattern) -> List[str]:
        """Extract unique subject names from pattern sections"""
        sections = pattern.sections.all()
        return list(set(s.subject for s in sections))
    
    def _get_pattern_sections(self, pattern) -> List[Dict]:
        """Get pattern sections as dicts"""
        sections = pattern.sections.all().order_by('subject', 'order', 'start_question')
        result = []
        for s in sections:
            result.append({
                'id': s.id,
                'name': s.name,
                'subject': s.subject,
                'question_type': s.question_type,
                'start_question': s.start_question,
                'end_question': s.end_question,
                'question_count': s.total_questions_in_section,
                'marks_per_question': s.marks_per_question,
                'negative_marking': float(s.negative_marking),
            })
        return result
    
    def _ai_analyze(
        self,
        full_text: str,
        pattern_subjects: List[str],
        expected_total: int
    ) -> DocumentBlueprint:
        """Use Gemini AI to analyze document structure"""
        
        # Truncate text for analysis prompt (structure is usually in first few pages)
        analysis_text = full_text[:15000]
        
        # Also include some text from middle and end to catch all sections
        text_len = len(full_text)
        if text_len > 20000:
            middle_start = text_len // 3
            end_start = text_len - 5000
            analysis_text += f"\n\n--- MIDDLE SECTION (position ~{middle_start}) ---\n"
            analysis_text += full_text[middle_start:middle_start + 5000]
            analysis_text += f"\n\n--- END SECTION (position ~{end_start}) ---\n"
            analysis_text += full_text[end_start:]
        
        prompt = STRUCTURE_ANALYSIS_PROMPT.format(
            pattern_subjects=', '.join(pattern_subjects),
            expected_total=expected_total,
            document_text=analysis_text
        )
        
        try:
            response = self.client.generate_content(
                prompt,
                generation_config={
                    'temperature': 0.1,  # Very low for consistent structure
                    'top_p': 0.95,
                    'max_output_tokens': 8192,
                }
            )
            
            response_text = response.text
            
            # Parse JSON from response
            json_data = self._parse_json_response(response_text)
            
            # Convert to blueprint
            return self._json_to_blueprint(json_data)
            
        except Exception as e:
            logger.error(f"AI structure analysis failed: {e}")
            raise StructureAnalysisError(f"AI analysis failed: {str(e)}")
    
    def _parse_json_response(self, response: str) -> Dict:
        """Parse JSON from AI response"""
        # Try to extract JSON from markdown code fence
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try raw JSON
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                raise StructureAnalysisError("No JSON found in AI response")
        
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            # Try to fix common JSON issues
            json_str = json_str.replace("'", '"')
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*]', ']', json_str)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                raise StructureAnalysisError(f"Invalid JSON in response: {e}")
    
    def _json_to_blueprint(self, data: Dict) -> DocumentBlueprint:
        """Convert parsed JSON to DocumentBlueprint"""
        blueprint = DocumentBlueprint(
            document_type=data.get('document_type', 'questions_with_answers'),
            confidence=data.get('confidence', 0.5),
            instructions=data.get('instructions', ''),
            total_questions=data.get('total_questions', 0),
            numbering_format=data.get('numbering_format', 'Q1.'),
            answer_format=data.get('answer_format', 'Answer: A'),
        )
        
        # Parse subjects
        for subj_data in data.get('subjects', []):
            subj = SubjectBlueprint(
                name=subj_data.get('name', 'Unknown'),
                start_position=subj_data.get('start_position', ''),
            )
            
            # Parse sections
            for sect_data in subj_data.get('sections', []):
                section = SectionBlueprint(
                    name=sect_data.get('name', 'Section'),
                    question_type=self._normalize_type(sect_data.get('question_type', 'single_mcq')),
                    start_question=sect_data.get('start_question', 1),
                    end_question=sect_data.get('end_question', 1),
                    question_count=sect_data.get('question_count', 0),
                    marks_per_question=sect_data.get('marks_per_question', 4),
                    negative_marking=sect_data.get('negative_marking', 0),
                    format_description=sect_data.get('format_description', ''),
                )
                subj.sections.append(section)
            
            # Calculate total for subject
            subj.total_questions = sum(s.question_count for s in subj.sections)
            blueprint.subjects.append(subj)
        
        # Recalculate total if subjects give better data
        subjects_total = sum(s.total_questions for s in blueprint.subjects)
        if subjects_total > 0:
            blueprint.total_questions = subjects_total
        
        return blueprint
    
    def _normalize_type(self, q_type: str) -> str:
        """Normalize question type to standard enum"""
        type_map = {
            'mcq': 'single_mcq',
            'single': 'single_mcq',
            'single_correct': 'single_mcq',
            'single_mcq': 'single_mcq',
            'multi': 'multiple_mcq',
            'multiple': 'multiple_mcq',
            'multi_correct': 'multiple_mcq',
            'multiple_mcq': 'multiple_mcq',
            'multiple_correct': 'multiple_mcq',
            'numerical': 'numerical',
            'integer': 'numerical',
            'numeric': 'numerical',
            'calculation': 'numerical',
            'subjective': 'subjective',
            'essay': 'subjective',
            'descriptive': 'subjective',
            'long_answer': 'subjective',
            'true_false': 'true_false',
            'tf': 'true_false',
            'boolean': 'true_false',
            'fill_blank': 'fill_blank',
            'fill_in': 'fill_blank',
            'fill_blanks': 'fill_blank',
            'fill_in_the_blank': 'fill_blank',
            'fill_in_the_blanks': 'fill_blank',
            'assertion_reason': 'single_mcq',
            'match_following': 'single_mcq',
        }
        normalized = q_type.lower().strip().replace(' ', '_').replace('-', '_')
        return type_map.get(normalized, 'single_mcq')
    
    def _regex_fallback(
        self,
        full_text: str,
        pattern_subjects: List[str],
        expected_total: int
    ) -> DocumentBlueprint:
        """Regex-based fallback when AI analysis fails"""
        logger.info("[Stage 2] Running regex fallback analysis...")
        
        blueprint = DocumentBlueprint(
            document_type='questions_with_answers',
            confidence=0.4,
        )
        
        # Detect subjects by scanning for subject headers
        detected_subjects = []
        text_lower = full_text.lower()
        
        for subj in pattern_subjects:
            subj_lower = subj.lower()
            # Look for subject headers like "PHYSICS", "Subject: Physics", etc.
            patterns = [
                rf'(?:^|\n)\s*(?:#{1,4}\s*)?{re.escape(subj_lower)}\s*(?:\n|$)',
                rf'(?:^|\n)\s*(?:subject\s*:\s*)?{re.escape(subj_lower)}\s*(?:\n|$)',
                rf'(?:^|\n)\s*---+\s*{re.escape(subj_lower)}\s*---+',
            ]
            for pattern in patterns:
                if re.search(pattern, text_lower, re.IGNORECASE | re.MULTILINE):
                    detected_subjects.append(subj)
                    break
        
        if not detected_subjects:
            # If no subjects found, use all pattern subjects
            detected_subjects = pattern_subjects
        
        # Count questions per subject (rough estimate)
        total_q_count = self._count_questions_regex(full_text)
        per_subject = max(1, total_q_count // len(detected_subjects)) if detected_subjects else total_q_count
        
        for subj in detected_subjects:
            subject_bp = SubjectBlueprint(name=subj, total_questions=per_subject)
            # Default: assume MCQ section + optional numerical
            subject_bp.sections.append(SectionBlueprint(
                name="MCQ Section",
                question_type="single_mcq",
                start_question=1,
                end_question=per_subject,
                question_count=per_subject,
            ))
            blueprint.subjects.append(subject_bp)
        
        blueprint.total_questions = total_q_count or expected_total
        
        return blueprint
    
    def _count_questions_regex(self, text: str) -> int:
        """Count questions using regex patterns"""
        patterns = [
            r'(?:^|\n)\s*Q\.?\s*\d+',
            r'(?:^|\n)\s*Question\s+\d+',
            r'(?:^|\n)\s*\d+[\.\)]\s+(?=[A-Z])',
        ]
        
        count = 0
        seen_positions = set()
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                pos = match.start()
                # Avoid double-counting at same position
                if not any(abs(pos - sp) < 20 for sp in seen_positions):
                    seen_positions.add(pos)
                    count += 1
        
        return count
    
    def _validate_against_pattern(self, blueprint: DocumentBlueprint, pattern) -> Dict:
        """Validate detected structure against the exam pattern"""
        issues = []
        
        pattern_sections = self._get_pattern_sections(pattern)
        pattern_subjects = self._get_pattern_subjects(pattern)
        detected_subjects = [s.name for s in blueprint.subjects]
        
        # Check subject matching
        matched = 0
        for ps in pattern_subjects:
            ps_lower = ps.lower()
            for ds in detected_subjects:
                if ps_lower == ds.lower() or ps_lower in ds.lower() or ds.lower() in ps_lower:
                    matched += 1
                    break
        
        subject_match_score = matched / len(pattern_subjects) if pattern_subjects else 0
        
        if subject_match_score < 0.5:
            issues.append(
                f"Subject mismatch: Pattern expects {pattern_subjects}, "
                f"found {detected_subjects}"
            )
        
        # Check total question count
        expected = pattern.total_questions
        detected = blueprint.total_questions
        if detected > 0 and abs(detected - expected) > expected * 0.2:
            issues.append(
                f"Question count mismatch: Pattern expects {expected}, "
                f"detected {detected}"
            )
        
        # Check section types match
        for subj_bp in blueprint.subjects:
            for sect_bp in subj_bp.sections:
                # Find matching pattern section
                matching = [
                    ps for ps in pattern_sections
                    if ps['subject'].lower() == subj_bp.name.lower()
                    and ps['question_type'] == sect_bp.question_type
                ]
                if not matching:
                    # Not necessarily an issue - AI might detect types differently
                    logger.debug(
                        f"No pattern section matches: {subj_bp.name} / {sect_bp.question_type}"
                    )
        
        matches_pattern = len(issues) == 0 and subject_match_score >= 0.5
        
        return {
            'matches_pattern': matches_pattern,
            'issues': issues,
            'subject_match_score': subject_match_score,
            'matched_subjects': matched,
            'total_pattern_subjects': len(pattern_subjects),
        }
    
    def _build_pattern_comparison(self, blueprint: DocumentBlueprint, pattern) -> Dict:
        """Build a detailed comparison between detected and expected structure"""
        pattern_sections = self._get_pattern_sections(pattern)
        
        expected = {}
        for ps in pattern_sections:
            key = f"{ps['subject']}_{ps['question_type']}"
            if key not in expected:
                expected[key] = {
                    'subject': ps['subject'],
                    'type': ps['question_type'],
                    'count': 0,
                }
            expected[key]['count'] += ps['question_count']
        
        detected = {}
        for subj in blueprint.subjects:
            for sect in subj.sections:
                key = f"{subj.name}_{sect.question_type}"
                if key not in detected:
                    detected[key] = {
                        'subject': subj.name,
                        'type': sect.question_type,
                        'count': 0,
                    }
                detected[key]['count'] += sect.question_count
        
        differences = []
        for key, exp in expected.items():
            det = detected.get(key, {'count': 0})
            if exp['count'] != det['count']:
                differences.append({
                    'subject': exp['subject'],
                    'type': exp['type'],
                    'expected': exp['count'],
                    'detected': det['count'],
                })
        
        return {
            'expected': expected,
            'detected': detected,
            'differences': differences,
        }
