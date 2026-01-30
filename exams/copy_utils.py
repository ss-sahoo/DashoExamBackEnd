from django.db import transaction
from patterns.models import ExamPattern, PatternSection
from questions.models import Question, ExamQuestion, QuestionImage

def clone_exam_assets(source_exam, target_exam, user=None):
    """
    Clones pattern, questions, and other assets from source_exam to target_exam.
    """
    with transaction.atomic():
        # 1. Clone the Pattern if it exists
        source_pattern = source_exam.pattern
        section_map = {} # Maps old section ID to new section object
        new_pattern = None

        if source_pattern:
            # We want to give it a unique name if possible to avoid conflicts
            new_pattern = ExamPattern.objects.create(
                name=f"{source_pattern.name} (Copy {target_exam.id})",
                description=source_pattern.description,
                institute=target_exam.institute,
                total_questions=source_pattern.total_questions,
                total_duration=source_pattern.total_duration,
                total_marks=source_pattern.total_marks,
                pattern_type=source_pattern.pattern_type,
                created_by=user or source_pattern.created_by
            )
            
            # Clone PatternSections
            for section in source_pattern.sections.all():
                new_section = PatternSection.objects.create(
                    pattern=new_pattern,
                    name=section.name,
                    subject=section.subject,
                    question_type=section.question_type,
                    start_question=section.start_question,
                    end_question=section.end_question,
                    marks_per_question=section.marks_per_question,
                    negative_marking=section.negative_marking,
                    min_questions_to_attempt=section.min_questions_to_attempt,
                    is_compulsory=section.is_compulsory,
                    order=section.order,
                    section_type=section.section_type,
                    selection_criteria=section.selection_criteria,
                    question_bank=section.question_bank
                )
                section_map[section.id] = new_section
            
            target_exam.pattern = new_pattern
            target_exam.save(update_fields=['pattern'])

        # 2. Clone Questions
        # Find all questions belonging to the source exam
        questions = Question.objects.filter(exam=source_exam, is_active=True)
        question_map = {} # Maps old question ID to new question ID
        
        for q in questions:
            old_id = q.id
            q.pk = None # Reset PK for cloning
            q.exam = target_exam
            
            # Update pattern_section_id if the pattern was cloned
            if q.pattern_section_id in section_map:
                new_sec = section_map[q.pattern_section_id]
                q.pattern_section_id = new_sec.id
                q.pattern_section_name = new_sec.name
            
            q.save()
            new_q = q
            question_map[old_id] = new_q
            
            # Clone QuestionImages
            for img in QuestionImage.objects.filter(question_id=old_id):
                img.pk = None
                img.question = new_q
                img.save()
                
        # 3. Clone ExamQuestion links
        # This ensures the exact mapping and marks from the source exam are preserved
        for eq in ExamQuestion.objects.filter(exam=source_exam):
            source_q_id = eq.question_id
            if source_q_id in question_map:
                ExamQuestion.objects.create(
                    exam=target_exam,
                    question=question_map[source_q_id],
                    question_number=eq.question_number,
                    section_name=eq.section_name,
                    marks=eq.marks,
                    negative_marks=eq.negative_marks,
                    order=eq.order
                )

        # 4. Update new PatternSections with cloned question IDs in fixed_questions
        if new_pattern:
            for old_section_id, new_section in section_map.items():
                old_section = PatternSection.objects.get(id=old_section_id)
                if old_section.fixed_questions:
                    new_fixed_questions = []
                    for old_qid in old_section.fixed_questions:
                        if old_qid in question_map:
                            new_fixed_questions.append(question_map[old_qid].id)
                        else:
                            # If it was a shared question from a bank, keep the original ID
                            new_fixed_questions.append(old_qid)
                    new_section.fixed_questions = new_fixed_questions
                    new_section.save(update_fields=['fixed_questions'])
                    
    return target_exam
