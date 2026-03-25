"""
AI Evaluation Views
API endpoints for AI-powered grading of subjective exams
"""
import os
import tempfile
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.core.files.storage import default_storage
from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser

from .models import Exam, ExamAttempt
from .ai_evaluation_service import (
    AIEvaluationService,
    convert_pdf_to_images,
    evaluate_subjective_submission,
)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_answer_sheet(request, exam_id):
    """
    Upload a student answer sheet for AI evaluation.
    
    POST /api/exams/{exam_id}/upload-answer-sheet/
    
    Request:
        - file: PDF or image file of the answer sheet
        - student_id: (optional) Student user ID
        - auto_evaluate: (optional) Boolean, default True
    
    Returns:
        - Evaluation results if auto_evaluate is True
        - Upload confirmation otherwise
    """
    exam = get_object_or_404(Exam, id=exam_id)
    
    # Validate exam mode
    if exam.exam_mode != 'offline_subjective':
        return Response(
            {'error': 'Exam mode must be "offline_subjective" for AI evaluation'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validate AI evaluation is enabled
    if not exam.ai_evaluation_enabled:
        return Response(
            {'error': 'AI evaluation is not enabled for this exam'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validate all questions have answers/solutions before evaluation
    from questions.models import Question
    questions = Question.objects.filter(exam_id=exam_id, is_active=True).order_by('question_number')
    missing_answers = []
    for q in questions:
        has_answer = False
        if q.question_type == 'subjective':
            if (q.solution and q.solution.strip()) or (q.correct_answer and q.correct_answer.strip()):
                has_answer = True
        elif q.question_type in ['multiple_mcq', 'multiple correct mcq']:
            if q.correct_answer and len(q.correct_answer) > 0:
                has_answer = True
        else:
            if q.correct_answer and str(q.correct_answer).strip():
                has_answer = True
        if not has_answer:
            missing_answers.append({
                'question_number': q.question_number,
                'question_type': q.question_type,
                'subject': q.subject or '',
            })
    
    if missing_answers:
        missing_nums = ', '.join([f"Q{m['question_number']}" for m in missing_answers])
        return Response({
            'error': f'Cannot evaluate: {len(missing_answers)} question(s) are missing answers/solutions ({missing_nums}). Please add answers before evaluation.',
            'missing_answers': missing_answers,
            'code': 'MISSING_ANSWERS'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Get uploaded file
    uploaded_file = request.FILES.get('file')
    if not uploaded_file:
        return Response(
            {'error': 'No file uploaded'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validate file type
    allowed_extensions = ['pdf', 'png', 'jpg', 'jpeg']
    ext = uploaded_file.name.split('.')[-1].lower()
    if ext not in allowed_extensions:
        return Response(
            {'error': f'File type not supported. Allowed: {", ".join(allowed_extensions)}'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Determine student
    student_id = request.data.get('student_id')
    if student_id:
        from accounts.models import User
        student = get_object_or_404(User, id=student_id)
    else:
        student = request.user
    
    # Save uploaded file permanently
    file_path = f"ai_eval_uploads/{exam.id}/{uploaded_file.name}"
    saved_path = default_storage.save(file_path, uploaded_file)
    
    auto_evaluate = request.data.get('auto_evaluate', 'true').lower() == 'true'
    
    if auto_evaluate:
        # Always create a temp file for processing since we need a local path
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            # Re-read the uploaded file from storage or use original
            try:
                # Try to open from storage
                with default_storage.open(saved_path, 'rb') as stored_file:
                    tmp.write(stored_file.read())
            except:
                # Fallback: use original uploaded file
                uploaded_file.seek(0)
                for chunk in uploaded_file.chunks():
                    tmp.write(chunk)
            pdf_path_to_use = tmp.name

        try:
            # Run AI evaluation
            marking_strictness = exam.marking_strictness or 'moderate'
            result = evaluate_subjective_submission(
                exam_id=exam.id,
                pdf_path=pdf_path_to_use,
                marking_strictness=marking_strictness
            )
            
            if result.get('success'):
                # Create or update exam attempt
                attempt, created = ExamAttempt.objects.update_or_create(
                    exam=exam,
                    student=student,
                    defaults={
                        'status': 'completed',
                        'score': result.get('total_marks', 0),
                        'percentage': result.get('percentage', 0),
                        'answers': {
                            'ai_evaluation': {
                                'grades': result.get('grades', []),
                                'student_name': result.get('student_name'),
                                'report': result.get('report'),
                                'max_marks': result.get('max_marks'),
                                'file_path': saved_path,
                            }
                        },
                        'submitted_at': timezone.now() if not ExamAttempt.objects.filter(exam=exam, student=student).exists() else None
                    }
                )
                
                return Response({
                    'success': True,
                    'attempt_id': attempt.id,
                    'student_name': result.get('student_name'),
                    'total_marks': result.get('total_marks'),
                    'max_marks': result.get('max_marks'),
                    'percentage': result.get('percentage'),
                    'grades': result.get('grades'),
                    'report': result.get('report'),
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': False,
                    'error': result.get('error', 'Unknown error'),
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        finally:
            # Always cleanup temp file
            if os.path.exists(pdf_path_to_use):
                os.remove(pdf_path_to_use)
    
    else:
        # Just save the file for later processing
        return Response({
            'success': True,
            'message': 'File uploaded successfully',
            'file_path': saved_path,
            'student_id': student.id,
        }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def evaluate_answer_sheet(request, exam_id):
    """
    Manually trigger AI evaluation of an already uploaded answer sheet.
    
    POST /api/exams/{exam_id}/evaluate-answer-sheet/
    
    Request:
        - file_path: Path to the uploaded file
        - student_id: Student user ID
    """
    exam = get_object_or_404(Exam, id=exam_id)
    
    file_path = request.data.get('file_path')
    student_id = request.data.get('student_id')
    
    if not file_path:
        return Response(
            {'error': 'file_path is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not student_id:
        return Response(
            {'error': 'student_id is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    from accounts.models import User
    student = get_object_or_404(User, id=student_id)
    
    try:
        # Download file to local temp path
        with tempfile.NamedTemporaryFile(suffix=f".{file_path.split('.')[-1]}", delete=False) as tmp:
            with default_storage.open(file_path, 'rb') as f:
                tmp.write(f.read())
            tmp_path = tmp.name

        marking_strictness = exam.marking_strictness or 'moderate'
        
        result = evaluate_subjective_submission(
            exam_id=exam.id,
            pdf_path=tmp_path,
            marking_strictness=marking_strictness
        )
        
        if result.get('success'):
            # Create or update exam attempt
            attempt, created = ExamAttempt.objects.update_or_create(
                exam=exam,
                student=student,
                defaults={
                    'status': 'completed',
                    'score': result.get('total_marks', 0),
                    'percentage': result.get('percentage', 0),
                    'answers': {
                        'ai_evaluation': {
                            'grades': result.get('grades', []),
                            'student_name': result.get('student_name'),
                            'report': result.get('report'),
                            'max_marks': result.get('max_marks'),
                            'file_path': file_path,
                        }
                    },
                }
            )
            
            return Response({
                'success': True,
                'attempt_id': attempt.id,
                'student_name': result.get('student_name'),
                'total_marks': result.get('total_marks'),
                'max_marks': result.get('max_marks'),
                'percentage': result.get('percentage'),
                'grades': result.get('grades'),
                'report': result.get('report'),
            })
        else:
            return Response({
                'success': False,
                'error': result.get('error'),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e),
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        # Cleanup temp local file
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.remove(tmp_path)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def ai_evaluation_status(request, exam_id):
    """
    Get AI evaluation configuration and status for an exam.
    
    GET /api/exams/{exam_id}/ai-evaluation-status/
    """
    exam = get_object_or_404(Exam, id=exam_id)
    
    # Count evaluations
    total_attempts = ExamAttempt.objects.filter(exam=exam).count()
    ai_evaluated = ExamAttempt.objects.filter(
        exam=exam,
        answers__has_key='ai_evaluation'
    ).count()
    
    return Response({
        'exam_id': exam.id,
        'exam_mode': exam.exam_mode,
        'ai_evaluation_enabled': exam.ai_evaluation_enabled,
        'marking_strictness': exam.marking_strictness,
        'total_attempts': total_attempts,
        'ai_evaluated_count': ai_evaluated,
        'pending_count': total_attempts - ai_evaluated,
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def test_ai_evaluation(request):
    """
    Test AI evaluation with sample data.
    
    POST /api/exams/test-ai-evaluation/
    
    Request:
        - exam_id: Exam ID
        - test_text: Sample text to evaluate
        - question_number: Question number to evaluate against
    """
    exam_id = request.data.get('exam_id')
    test_text = request.data.get('test_text', '')
    question_number = request.data.get('question_number', 1)
    
    if not exam_id:
        return Response(
            {'error': 'exam_id is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    exam = get_object_or_404(Exam, id=exam_id)
    
    try:
        service = AIEvaluationService(exam, exam.marking_strictness or 'moderate')
        
        # Find the question
        question_data = None
        for q in service.question_bank:
            if q['Q.No.'] == question_number:
                question_data = q
                break
        
        if not question_data:
            return Response({
                'error': f'Question {question_number} not found in exam'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Create mock student response
        student_response = {
            'Q.No.': question_number,
            'Is_multipart': question_data.get('is_multi_part_question', False),
            'Part.No.': None,
            'Answer_text_written': test_text,
            'diagram_available': 0,
        }
        
        # Grade the answer
        result = service.grade_answer(
            question_data=question_data,
            student_response=student_response
        )
        
        return Response({
            'success': True,
            'question': question_data.get('Question'),
            'correct_answer': question_data.get('Answer'),
            'student_answer': test_text,
            'max_marks': question_data.get('mark'),
            'result': result,
        })
        
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e),
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def list_submissions(request, exam_id):
    """
    List past AI evaluation submissions for an exam.
    """
    exam = get_object_or_404(Exam, id=exam_id)
    
    if request.user.role.lower() == 'student':
        attempts = ExamAttempt.objects.filter(
            exam=exam,
            student=request.user,
            answers__has_key='ai_evaluation'
        ).select_related('student').order_by('-submitted_at')
    else:
        attempts = ExamAttempt.objects.filter(
            exam=exam,
            answers__has_key='ai_evaluation'
        ).select_related('student').order_by('-submitted_at')
    
    submissions = []
    for attempt in attempts:
        ai_data = attempt.answers.get('ai_evaluation', {})
        submissions.append({
            'id': attempt.id,
            'exam': exam.id,
            'student_id': attempt.student.id,
            'student_name': attempt.student.get_full_name() or attempt.student.username,
            'status': 'evaluated',
            'score': attempt.score,
            'percentage': attempt.percentage,
            'evaluation_result': {
                'student_name': ai_data.get('student_name'),
                'total_score': float(attempt.score) if attempt.score else 0,
                'max_score': float(ai_data.get('max_marks')) if ai_data.get('max_marks') is not None else round(float(attempt.score * 100 / attempt.percentage), 1) if attempt.percentage and attempt.score else 0,
                'percentage': float(attempt.percentage) if attempt.percentage else 0,
                'grades': ai_data.get('grades', []),
                'report': ai_data.get('report', ''),
            },
            'created_at': attempt.submitted_at or attempt.created_at,
            'file_path': ai_data.get('file_path', ''),
        })
    
    return Response(submissions)
    
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def update_submission_mark(request, exam_id, attempt_id):
    """
    Update a specific question mark and reasoning in an AI evaluation.
    
    POST /api/exams/{exam_id}/submissions/{attempt_id}/update-mark/
    
    Request:
        - question_no: int or str (e.g., 6)
        - part_no: str or null (e.g., "i")
        - mark: float
        - reasoning: str (optional)
    """
    exam = get_object_or_404(Exam, id=exam_id)
    attempt = get_object_or_404(ExamAttempt, id=attempt_id, exam=exam)
    
    # Check permissions
    if not request.user.can_manage_exams():
        return Response(
            {'error': 'Permission denied. Only teachers and admins can modify marks.'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    if 'ai_evaluation' not in attempt.answers:
        return Response(
            {'error': 'No AI evaluation data found for this attempt'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    question_no = request.data.get('question_no')
    part_no = request.data.get('part_no')
    new_mark = request.data.get('mark')
    new_reasoning = request.data.get('reasoning')
    
    if question_no is None or new_mark is None:
        return Response(
            {'error': 'question_no and mark are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    ai_data = attempt.answers['ai_evaluation']
    grades = ai_data.get('grades', [])
    
    updated = False
    for grade in grades:
        # Match by question_no and part_no
        # Using string comparison for Q.No. to handle both int and str
        if str(grade.get('Q.No.')) == str(question_no) and grade.get('Part.No.') == part_no:
            try:
                grade['mark'] = float(new_mark)
            except (ValueError, TypeError):
                return Response({'error': 'Invalid mark value'}, status=status.HTTP_400_BAD_REQUEST)
                
            if new_reasoning is not None:
                grade['reasoning'] = new_reasoning
            updated = True
            break
            
    if not updated:
        return Response(
            {'error': f'Question {question_no} (part {part_no}) not found in evaluation results'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Recalculate totals
    total_marks = sum(g.get("mark", 0) for g in grades if isinstance(g.get("mark"), (int, float)))
    
    # Get max_marks from stored data or attempt to recalculate
    max_marks = float(ai_data.get('max_marks', 0))
    if max_marks == 0 and attempt.percentage and attempt.score:
        max_marks = float(attempt.score * 100 / attempt.percentage)
    
    # Update AI data
    ai_data['grades'] = grades
    ai_data['total_marks'] = total_marks
    
    # Regenerate report
    service = AIEvaluationService(exam)
    student_name = ai_data.get('student_name', attempt.student.get_full_name() or attempt.student.username)
    ai_data['report'] = service.generate_report(grades, student_name)
    
    # Update attempt score and percentage
    attempt.score = total_marks
    if max_marks > 0:
        attempt.percentage = (total_marks / max_marks * 100)
    else:
        attempt.percentage = 0
    
    # Save attempt
    attempt.answers['ai_evaluation'] = ai_data
    attempt.save()
    
    return Response({
        'success': True,
        'message': 'Mark updated successfully',
        'total_score': attempt.score,
        'percentage': attempt.percentage,
        'report': ai_data['report'],
        'grades': grades
    })
