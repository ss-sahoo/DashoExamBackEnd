"""
Management command to fix question_number_in_pattern for existing questions.

This command will:
1. Find all questions that have pattern_section_id but no question_number_in_pattern
2. Calculate the correct question_number_in_pattern based on their position in the section
3. Update the questions with the correct values

Usage:
    python manage.py fix_question_numbers
    python manage.py fix_question_numbers --dry-run  # Preview changes without applying
    python manage.py fix_question_numbers --exam-id=62  # Fix only for specific exam
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from questions.models import Question
from patterns.models import PatternSection


class Command(BaseCommand):
    help = 'Fix question_number_in_pattern for existing questions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without applying them',
        )
        parser.add_argument(
            '--exam-id',
            type=int,
            help='Fix only questions for a specific exam',
        )
        parser.add_argument(
            '--pattern-id',
            type=int,
            help='Fix only questions for a specific pattern',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        exam_id = options.get('exam_id')
        pattern_id = options.get('pattern_id')

        self.stdout.write(self.style.NOTICE('Starting question number fix...'))
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))

        # Build base queryset
        questions_qs = Question.objects.filter(
            pattern_section_id__isnull=False,
            is_active=True
        )

        if exam_id:
            questions_qs = questions_qs.filter(exam_id=exam_id)
            self.stdout.write(f'Filtering by exam_id={exam_id}')

        if pattern_id:
            # Get section IDs for this pattern
            section_ids = list(PatternSection.objects.filter(
                pattern_id=pattern_id
            ).values_list('id', flat=True))
            questions_qs = questions_qs.filter(pattern_section_id__in=section_ids)
            self.stdout.write(f'Filtering by pattern_id={pattern_id}')

        # Group questions by section
        section_ids = questions_qs.values_list('pattern_section_id', flat=True).distinct()
        
        total_fixed = 0
        total_skipped = 0

        for section_id in section_ids:
            try:
                section = PatternSection.objects.get(id=section_id)
            except PatternSection.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f'Section {section_id} not found, skipping...'
                ))
                continue

            self.stdout.write(f'\nProcessing section: {section.name} (ID: {section_id})')
            self.stdout.write(f'  Subject: {section.subject}')
            self.stdout.write(f'  Range: Q{section.start_question}-{section.end_question}')

            # Get questions for this section, ordered by question_number or id
            section_questions = questions_qs.filter(
                pattern_section_id=section_id
            ).order_by('question_number', 'id')

            questions_to_update = []
            
            for idx, question in enumerate(section_questions):
                # Calculate the expected question_number_in_pattern
                # This is 1-indexed position within the section
                expected_number = idx + 1
                
                current_number = question.question_number_in_pattern
                
                if current_number != expected_number:
                    self.stdout.write(
                        f'  Q{question.id}: {current_number} -> {expected_number}'
                    )
                    question.question_number_in_pattern = expected_number
                    questions_to_update.append(question)
                else:
                    total_skipped += 1

            if questions_to_update:
                if not dry_run:
                    with transaction.atomic():
                        Question.objects.bulk_update(
                            questions_to_update,
                            ['question_number_in_pattern'],
                            batch_size=100
                        )
                    self.stdout.write(self.style.SUCCESS(
                        f'  Updated {len(questions_to_update)} questions'
                    ))
                else:
                    self.stdout.write(self.style.WARNING(
                        f'  Would update {len(questions_to_update)} questions'
                    ))
                total_fixed += len(questions_to_update)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Total fixed: {total_fixed}'))
        self.stdout.write(f'Total skipped (already correct): {total_skipped}')
        
        if dry_run:
            self.stdout.write(self.style.WARNING(
                '\nThis was a dry run. Run without --dry-run to apply changes.'
            ))
