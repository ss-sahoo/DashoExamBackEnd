"""
Stage 5: Validator
Validates extracted questions for completeness, quality, and correctness.
Implements a retry loop for missing questions.
"""
import re
import json
import logging
import time
from typing import Dict, List, Optional, Tuple
from django.conf import settings

from .prompts import VALIDATION_RETRY_PROMPT

logger = logging.getLogger('extraction')


class ValidationError(Exception):
    """Raised when validation encounters a critical error"""
    pass


class QuestionValidator:
    """
    Stage 5 of the extraction pipeline.
    
    Validates extracted questions for:
    - Completeness (did we get all expected questions?)
    - Quality (do questions have required fields?)
    - Correctness (do answers match question types?)
    
    If questions are missing, re-runs extraction on just the missing range.
    This retry loop is a KEY IMPROVEMENT — the old system either got all
    questions or gave up entirely.
    """
    
    MAX_VALIDATION_RETRIES = 2
    COMPLETENESS_THRESHOLD = 0.90  # Accept if 90%+ extracted
    
    def __init__(self):
        self._client = None
        self._model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash')
    
    @property
    def client(self):
        """Lazy-initialize Gemini client"""
        if self._client is None:
            api_key = getattr(settings, 'GEMINI_API_KEY', None)
            if not api_key:
                raise ValidationError("GEMINI_API_KEY not configured")
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                self._client = genai.GenerativeModel(self._model_name)
            except ImportError:
                raise ValidationError("google-generativeai not installed")
        return self._client
    
    def validate_and_fix(
        self,
        questions: List[Dict],
        chunks: list,
        blueprint,
    ) -> Dict:
        """
        Validate extracted questions and attempt to fill gaps.
        
        Args:
            questions: All extracted questions from Stage 4
            chunks: Original document chunks from Stage 3
            blueprint: Document blueprint from Stage 2
            
        Returns:
            {
                'questions': List[Dict],          # Final validated questions
                'validation_report': {
                    'total_expected': int,
                    'total_extracted': int,
                    'total_after_retry': int,
                    'completeness_score': float,
                    'quality_scores': {...},
                    'issues': [...],
                    'retries_performed': int,
                },
                'per_subject': {
                    'Physics': {'expected': 25, 'extracted': 23, ...},
                    ...
                }
            }
        """
        logger.info(f"[Stage 5] Validating {len(questions)} extracted questions...")
        
        total_expected = blueprint.total_questions
        issues = []
        retries_performed = 0
        
        # Step 1: Individual question quality validation
        validated_questions, quality_issues = self._validate_quality(questions)
        issues.extend(quality_issues)
        
        # Step 2: Completeness check per subject/section
        completeness_result = self._check_completeness(validated_questions, blueprint)
        
        # Step 3: Retry extraction for missing questions
        if completeness_result['missing_sections']:
            logger.info(
                f"[Stage 5] Missing questions detected in "
                f"{len(completeness_result['missing_sections'])} sections. "
                f"Attempting retry extraction..."
            )
            
            for retry in range(self.MAX_VALIDATION_RETRIES):
                missing = completeness_result['missing_sections']
                if not missing:
                    break
                
                retries_performed += 1
                
                recovered = self._retry_missing(
                    missing, chunks, validated_questions
                )
                
                if recovered:
                    validated_questions.extend(recovered)
                    logger.info(
                        f"[Stage 5] Retry {retry + 1}: recovered "
                        f"{len(recovered)} questions"
                    )
                
                # Re-check completeness
                completeness_result = self._check_completeness(
                    validated_questions, blueprint
                )
        
        # Step 4: Deduplicate
        validated_questions = self._deduplicate(validated_questions)
        
        # Step 5: Build final report
        total_extracted = len(validated_questions)
        completeness_score = total_extracted / total_expected if total_expected > 0 else 0
        
        per_subject = self._build_per_subject_report(validated_questions, blueprint)
        
        report = {
            'total_expected': total_expected,
            'total_extracted': total_extracted,
            'total_after_retry': total_extracted,
            'completeness_score': completeness_score,
            'quality_scores': self._compute_quality_scores(validated_questions),
            'issues': issues + completeness_result.get('issues', []),
            'retries_performed': retries_performed,
        }
        
        logger.info(
            f"[Stage 5] Validation complete: {total_extracted}/{total_expected} "
            f"({completeness_score:.0%}), retries={retries_performed}"
        )
        
        return {
            'questions': validated_questions,
            'validation_report': report,
            'per_subject': per_subject,
        }
    
    def _validate_quality(self, questions: List[Dict]) -> Tuple[List[Dict], List[str]]:
        """Validate individual question quality for ALL question types"""
        validated = []
        issues = []
        
        for i, q in enumerate(questions):
            q_issues = []
            q_num = q.get('question_number', '?')
            
            # Check required fields
            if not str(q.get('question_text') or '').strip():
                q_issues.append(f"Q{q_num}: Empty question text")
                continue  # Skip empty questions
            
            q_type = q.get('question_type', '')
            
            # ── single_mcq validation ──
            if q_type == 'single_mcq':
                options = q.get('options', [])
                if not options or len(options) < 2:
                    q_issues.append(f"Q{q_num}: MCQ has {len(options)} options (need ≥2)")
                    q['requires_review'] = True
                
                answer = str(q.get('correct_answer', '')).strip().upper()
                if answer:
                    if len(answer) != 1 or answer not in 'ABCDE':
                        # Maybe it's actually multiple_mcq
                        if ',' in answer or len(answer) > 1:
                            q['question_type'] = 'multiple_mcq'
                            q_issues.append(f"Q{q_num}: Reclassified single_mcq → multiple_mcq (answer: '{answer}')")
                        else:
                            q_issues.append(f"Q{q_num}: Invalid single MCQ answer '{answer}'")
                            q['requires_review'] = True
            
            # ── multiple_mcq validation ──
            elif q_type == 'multiple_mcq':
                options = q.get('options', [])
                if not options or len(options) < 2:
                    q_issues.append(f"Q{q_num}: MCQ has {len(options)} options (need ≥2)")
                    q['requires_review'] = True
                
                answer = str(q.get('correct_answer', '')).strip().upper()
                if answer:
                    # Normalize: extract all valid letters
                    import re as _re
                    letters = _re.findall(r'[A-E]', answer)
                    if letters:
                        q['correct_answer'] = ','.join(sorted(set(letters)))
                    else:
                        q_issues.append(f"Q{q_num}: Invalid multiple MCQ answer '{answer}'")
                        q['requires_review'] = True
                    
                    # If only 1 letter, might actually be single_mcq
                    if len(set(letters)) == 1:
                        q_issues.append(f"Q{q_num}: multiple_mcq has only 1 answer letter — may be single_mcq")
            
            # ── numerical validation ──
            elif q_type == 'numerical':
                answer = str(q.get('correct_answer', '')).strip()
                if answer:
                    try:
                        float(answer)
                    except ValueError:
                        # Try to extract number from answer text
                        num_match = re.search(r'[-+]?\d*\.?\d+', answer)
                        if num_match:
                            q['correct_answer'] = num_match.group(0)
                        else:
                            q_issues.append(f"Q{q_num}: Non-numeric answer '{answer}'")
                            q['requires_review'] = True
                
                # Numerical should never have options
                if q.get('options'):
                    q['options'] = []
            
            # ── true_false validation ──
            elif q_type == 'true_false':
                # Ensure options are [True, False]
                q['options'] = ['True', 'False']
                
                answer = str(q.get('correct_answer', '')).strip()
                if answer:
                    normalized = answer.lower()
                    if normalized in ('true', 't', 'yes', 'correct', '1'):
                        q['correct_answer'] = 'True'
                    elif normalized in ('false', 'f', 'no', 'incorrect', '0'):
                        q['correct_answer'] = 'False'
                    else:
                        q_issues.append(f"Q{q_num}: Invalid true_false answer '{answer}'")
                        q['requires_review'] = True
            
            # ── fill_blank validation ──
            elif q_type == 'fill_blank':
                answer = str(q.get('correct_answer', '')).strip()
                if not answer:
                    q_issues.append(f"Q{q_num}: Fill-in-the-blank has empty answer")
                    q['requires_review'] = True
                
                # Check that question text has a blank marker
                text = q.get('question_text', '')
                has_blank = bool(re.search(r'_{2,}|\.{3,}|\-{3,}|\[blank\]|\<blank\>', text, re.IGNORECASE))
                if not has_blank:
                    q_issues.append(f"Q{q_num}: fill_blank question has no blank marker in text")
            
            # ── subjective validation ──
            elif q_type == 'subjective':
                # Subjective questions are harder to validate
                # Check for substantial text OR nested structure
                text = str(q.get('question_text') or '').strip()
                structure = q.get('structure', {})
                parts = structure.get('parts', [])
                
                if len(text) < 15 and not parts:
                    q_issues.append(f"Q{q_num}: Subjective question text too short and no sub-parts found")
                    q['requires_review'] = True
                
                q['options'] = []  # Never has options
            
            # Mark confidence based on issues
            if q_issues:
                q['confidence_score'] = max(0.3, q.get('confidence_score', 0.5) - 0.2)
            else:
                q['confidence_score'] = q.get('confidence_score', 0.85)
            
            validated.append(q)
            issues.extend(q_issues)
        
        return validated, issues
    
    def _check_completeness(self, questions: List[Dict], blueprint) -> Dict:
        """Check completeness per subject/section"""
        missing_sections = []
        issues = []
        
        # Group extracted questions by source subject
        by_subject = {}
        for q in questions:
            source = q.get('_source', {})
            subj = source.get('subject', 'Unknown')
            if subj not in by_subject:
                by_subject[subj] = []
            by_subject[subj].append(q)
        
        # Check each subject/section in blueprint
        for subj_bp in blueprint.subjects:
            subj_questions = by_subject.get(subj_bp.name, [])
            
            for sect_bp in subj_bp.sections:
                expected = sect_bp.question_count
                
                # Count questions matching this section range
                extracted_in_range = [
                    q for q in subj_questions
                    if sect_bp.start_question <= q.get('question_number', 0) <= sect_bp.end_question
                ]
                
                actual = len(extracted_in_range) if extracted_in_range else 0
                
                # If we can't match by number, use count from source metadata
                if actual == 0:
                    actual = len([
                        q for q in subj_questions
                        if q.get('_source', {}).get('section_name') == sect_bp.name
                    ])
                
                if actual < expected * self.COMPLETENESS_THRESHOLD:
                    missing_count = expected - actual
                    missing_sections.append({
                        'subject': subj_bp.name,
                        'section_name': sect_bp.name,
                        'question_type': sect_bp.question_type,
                        'start_question': sect_bp.start_question,
                        'end_question': sect_bp.end_question,
                        'expected': expected,
                        'extracted': actual,
                        'missing': missing_count,
                        'extracted_numbers': [
                            q.get('question_number', 0) 
                            for q in extracted_in_range
                        ],
                    })
                    issues.append(
                        f"{subj_bp.name}/{sect_bp.name}: "
                        f"extracted {actual}/{expected} questions "
                        f"(missing ~{missing_count})"
                    )
        
        return {
            'missing_sections': missing_sections,
            'issues': issues,
        }
    
    def _retry_missing(
        self,
        missing_sections: List[Dict],
        chunks: list,
        existing_questions: List[Dict]
    ) -> List[Dict]:
        """Re-extract missing questions using validation retry prompt"""
        recovered = []
        
        for missing in missing_sections:
            # Find the chunk that contains this section
            matching_chunk = None
            for chunk in chunks:
                if (chunk.subject == missing['subject'] and
                        chunk.section_name == missing['section_name']):
                    matching_chunk = chunk
                    break
            
            if not matching_chunk:
                logger.warning(
                    f"[Stage 5] No matching chunk for "
                    f"{missing['subject']}/{missing['section_name']}"
                )
                continue
            
            # Build retry prompt
            prompt = VALIDATION_RETRY_PROMPT.format(
                expected_count=missing['expected'],
                extracted_count=missing['extracted'],
                missing_count=missing['missing'],
                subject=missing['subject'],
                section_name=missing['section_name'],
                question_type=missing['question_type'],
                start_q=missing['start_question'],
                end_q=missing['end_question'],
                extracted_numbers=str(missing.get('extracted_numbers', [])),
                chunk_text=matching_chunk.text,
            )
            
            try:
                response = self.client.generate_content(
                    prompt,
                    generation_config={
                        'temperature': 0.3,
                        'top_p': 0.95,
                        'max_output_tokens': 32768,
                    }
                )
                
                response_text = response.text
                
                # Parse response
                json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_match = re.search(r'\[\s*\{.*\}\s*\]', response_text, re.DOTALL)
                    json_str = json_match.group(0) if json_match else response_text
                
                new_questions = json.loads(json_str)
                
                if isinstance(new_questions, list):
                    for q in new_questions:
                        q['_source'] = {
                            'subject': missing['subject'],
                            'section_name': missing['section_name'],
                            'question_type': missing['question_type'],
                            'chunk_index': matching_chunk.chunk_index,
                            'marks_per_question': matching_chunk.marks_per_question,
                            'negative_marking': matching_chunk.negative_marking,
                            'from_retry': True,
                        }
                        q['confidence_score'] = 0.65  # Lower confidence for retries
                    
                    recovered.extend(new_questions)
                    
            except Exception as e:
                logger.warning(
                    f"[Stage 5] Retry extraction failed for "
                    f"{missing['subject']}/{missing['section_name']}: {e}"
                )
            
            # Small delay between retries
            time.sleep(1)
        
        return recovered
    
    def _deduplicate(self, questions: List[Dict]) -> List[Dict]:
        """Remove duplicate questions by question_number + subject"""
        seen = set()
        unique = []
        
        for q in questions:
            source = q.get('_source', {})
            key = (
                source.get('subject', ''),
                q.get('question_number', 0),
                q.get('question_text', '')[:50],  # First 50 chars
            )
            
            if key not in seen:
                seen.add(key)
                unique.append(q)
            else:
                logger.debug(
                    f"[Stage 5] Duplicate removed: Q{q.get('question_number')} "
                    f"({source.get('subject', 'Unknown')})"
                )
        
        return unique
    
    def _compute_quality_scores(self, questions: List[Dict]) -> Dict:
        """Compute aggregate quality metrics"""
        if not questions:
            return {
                'avg_confidence': 0,
                'has_answer_pct': 0,
                'has_solution_pct': 0,
                'needs_review_pct': 0,
            }
        
        total = len(questions)
        
        avg_confidence = sum(
            q.get('confidence_score', 0.5) for q in questions
        ) / total
        
        has_answer = sum(
            1 for q in questions if str(q.get('correct_answer') or '').strip()
        )
        
        has_solution = sum(
            1 for q in questions if str(q.get('solution') or '').strip()
        )
        
        needs_review = sum(
            1 for q in questions if q.get('requires_review', False)
        )
        
        return {
            'avg_confidence': round(avg_confidence, 3),
            'has_answer_pct': round(has_answer / total, 3),
            'has_solution_pct': round(has_solution / total, 3),
            'needs_review_pct': round(needs_review / total, 3),
        }
    
    def _build_per_subject_report(self, questions: List[Dict], blueprint) -> Dict:
        """Build per-subject extraction report"""
        report = {}
        
        for subj_bp in blueprint.subjects:
            subj_questions = [
                q for q in questions
                if q.get('_source', {}).get('subject', '') == subj_bp.name
            ]
            
            report[subj_bp.name] = {
                'expected': subj_bp.total_questions,
                'extracted': len(subj_questions),
                'sections': {}
            }
            
            for sect_bp in subj_bp.sections:
                sect_questions = [
                    q for q in subj_questions
                    if q.get('_source', {}).get('section_name') == sect_bp.name
                ]
                report[subj_bp.name]['sections'][sect_bp.name] = {
                    'expected': sect_bp.question_count,
                    'extracted': len(sect_questions),
                    'type': sect_bp.question_type,
                }
        
        return report
