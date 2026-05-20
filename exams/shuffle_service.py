import random
import hashlib
from copy import deepcopy
from typing import List, Dict, Any, Optional


class ShuffleService:
    """
    Deterministic shuffling of questions and options for online exams.

    Uses a seed derived from student_id + exam_id so the same student
    always sees the same shuffled order for a given exam.
    """

    def __init__(self, exam, student):
        self.exam = exam
        self.student = student

    def _build_seed(self) -> int:
        """Build a deterministic seed from exam and student IDs."""
        if self.exam.shuffle_seed_per_student:
            raw = f"{self.student.id}-{self.exam.id}"
        else:
            # Same order for all students
            raw = f"{self.exam.id}"
        return int(hashlib.sha256(raw.encode()).hexdigest(), 16) % (2**32)

    def shuffle_questions(self, questions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Apply all configured shuffle settings to a list of question dicts.

        Returns a dict with:
          - 'questions': the shuffled list of question dicts (with options shuffled if enabled)
          - 'mapping': a serializable mapping for audit/reproducibility
        """
        seed = self._build_seed()
        rng = random.Random(seed)

        mapping = {
            'seed': seed,
            'question_order': [],   # list of original question IDs in new order
            'option_mappings': {},  # question_id -> list of original option indices in new order
        }

        shuffled = list(questions)

        if self.exam.shuffle_questions:
            shuffled = self._shuffle_question_order(shuffled, rng)

        # Record question order
        for q in shuffled:
            q_id = str(q.get('question_id') or q.get('id'))
            mapping['question_order'].append(q_id)

        if self.exam.shuffle_options:
            shuffled, option_mappings = self._shuffle_options(shuffled, rng)
            mapping['option_mappings'] = option_mappings

        return {'questions': shuffled, 'mapping': mapping}

    def _shuffle_question_order(self, questions: List[Dict], rng: random.Random) -> List[Dict]:
        """Shuffle question order respecting section/subject settings."""
        if self.exam.shuffle_within_sections and not self.exam.shuffle_sections:
            # Group by section, shuffle within each section, keep section order
            return self._shuffle_within_sections(questions, rng)
        elif self.exam.shuffle_sections:
            # Shuffle entire sections (and optionally within them)
            return self._shuffle_sections(questions, rng)
        else:
            # Simple full shuffle of all questions
            shuffled = list(questions)
            rng.shuffle(shuffled)
            return shuffled

    def _shuffle_within_sections(self, questions: List[Dict], rng: random.Random) -> List[Dict]:
        """Shuffle questions within each section, preserving section order."""
        sections = self._group_by_section(questions)
        result = []
        for section_name, section_questions in sections:
            group = list(section_questions)
            rng.shuffle(group)
            result.extend(group)
        return result

    def _shuffle_sections(self, questions: List[Dict], rng: random.Random) -> List[Dict]:
        """Shuffle the order of entire sections."""
        sections = self._group_by_section(questions)
        rng.shuffle(sections)

        result = []
        for section_name, section_questions in sections:
            group = list(section_questions)
            if self.exam.shuffle_within_sections:
                rng.shuffle(group)
            result.extend(group)
        return result

    def _group_by_section(self, questions: List[Dict]) -> List[tuple]:
        """Group questions by section_name, preserving encounter order."""
        from collections import OrderedDict
        groups = OrderedDict()
        for q in questions:
            section = q.get('section_name', 'General')
            if section not in groups:
                groups[section] = []
            groups[section].append(q)
        return list(groups.items())

    def _shuffle_options(self, questions: List[Dict], rng: random.Random):
        """Shuffle MCQ options for each question. Returns (questions, option_mappings)."""
        option_mappings = {}
        mcq_types = ('single_mcq', 'multiple_mcq')

        for q in questions:
            q_data = q.get('question') or q
            q_id = str(q.get('question_id') or q.get('id'))
            q_type = q_data.get('question_type', '')

            if q_type not in mcq_types:
                continue

            options = q_data.get('options')
            if not options or not isinstance(options, list) or len(options) <= 1:
                continue

            # Build index list and shuffle it
            indices = list(range(len(options)))
            rng.shuffle(indices)

            # Reorder options
            shuffled_options = [options[i] for i in indices]
            q_data['options'] = shuffled_options

            # Store mapping: new_index -> original_index
            option_mappings[q_id] = indices

        return questions, option_mappings
