"""
OMR App Views
API endpoints for OMR sheet generation and evaluation
"""
import os
from django.shortcuts import get_object_or_404
from django.core.files.storage import default_storage
from rest_framework import status, viewsets, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser

from exams.models import Exam
from .models import OMRSheet, OMRSubmission, AnswerKey
from .serializers import (
    OMRSheetSerializer,
    OMRSheetGenerateSerializer,
    OMRSubmissionSerializer,
    OMRSubmissionUploadSerializer,
    AnswerKeySerializer,
)
from .services.generator import OMRGeneratorService
from .services.evaluator import OMREvaluatorService


class OMRSheetViewSet(viewsets.ModelViewSet):
    """
    ViewSet for OMR Sheet management.
    """
    serializer_class = OMRSheetSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filter OMR sheets by user's institute"""
        user = self.request.user
        if user.role == 'super_admin':
            return OMRSheet.objects.all()
        return OMRSheet.objects.filter(exam__institute=user.institute)
    
    @action(detail=False, methods=['post'], url_path='generate/(?P<exam_id>[^/.]+)')
    def generate_for_exam(self, request, exam_id=None):
        """
        Generate OMR sheet for an exam.
        
        POST /api/omr/sheets/generate/{exam_id}/
        """
        exam = get_object_or_404(Exam, id=exam_id)
        
        # Validate exam mode
        if exam.exam_mode != 'offline_omr':
            return Response(
                {'error': 'Exam mode must be "offline_omr" to generate OMR sheet'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate request data
        serializer = OMRSheetGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Create OMR sheet record
        omr_sheet = OMRSheet.objects.create(
            exam=exam,
            candidate_fields=serializer.validated_data.get('candidate_fields', []),
        )
        
        try:
            # Generate the OMR sheet
            generator = OMRGeneratorService(exam)
            generator.generate_and_save(
                omr_sheet,
                candidate_fields=serializer.validated_data.get('candidate_fields'),
            )
            
            # Update exam flags
            exam.omr_sheet_generated = True
            if omr_sheet.pdf_file:
                exam.omr_sheet_file = omr_sheet.pdf_file
            exam.omr_config = {
                'candidate_fields': omr_sheet.candidate_fields,
                'question_config': omr_sheet.question_config,
            }
            exam.omr_metadata = omr_sheet.metadata
            exam.save()
            
            return Response(
                OMRSheetSerializer(omr_sheet, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            return Response(
                {'error': str(e), 'omr_sheet': OMRSheetSerializer(omr_sheet).data},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """
        Get download URL for OMR sheet PDF.
        
        GET /api/omr/sheets/{id}/download/
        """
        omr_sheet = self.get_object()
        
        if not omr_sheet.pdf_file:
            return Response(
                {'error': 'OMR sheet PDF not available'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response({
            'pdf_url': request.build_absolute_uri(omr_sheet.pdf_file.url),
            'metadata': omr_sheet.metadata,
        })


class OMRSubmissionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for OMR Submission management.
    """
    serializer_class = OMRSubmissionSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_queryset(self):
        """Filter submissions based on user role"""
        user = self.request.user
        if user.role == 'super_admin':
            return OMRSubmission.objects.all()
        elif user.role in ['institute_admin', 'exam_admin', 'teacher']:
            return OMRSubmission.objects.filter(omr_sheet__exam__institute=user.institute)
        else:
            return OMRSubmission.objects.filter(student=user)
    
    @action(detail=False, methods=['post'], url_path='upload/(?P<exam_id>[^/.]+)')
    def upload_for_exam(self, request, exam_id=None):
        """
        Upload scanned OMR sheets for evaluation.
        
        POST /api/omr/submissions/upload/{exam_id}/
        """
        exam = get_object_or_404(Exam, id=exam_id)
        
        # Validate exam mode
        if exam.exam_mode != 'offline_omr':
            return Response(
                {'error': 'Exam mode must be "offline_omr" to upload OMR sheets'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get primary OMR sheet
        omr_sheet = OMRSheet.objects.filter(exam=exam, is_primary=True).first()
        if not omr_sheet:
            return Response(
                {'error': 'No OMR sheet found for this exam. Generate one first.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Handle file uploads
        files = request.FILES.getlist('files')
        if not files:
            return Response(
                {'error': 'No files uploaded'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Save uploaded files
        saved_paths = []
        for file in files:
            file_path = f"omr_uploads/{exam.id}/{file.name}"
            saved_path = default_storage.save(file_path, file)
            saved_paths.append(default_storage.path(saved_path))
        
        # Determine student
        student_id = request.data.get('student_id')
        if student_id:
            from accounts.models import User
            student = get_object_or_404(User, id=student_id)
        else:
            student = request.user
        
        # Create submission
        submission = OMRSubmission.objects.create(
            omr_sheet=omr_sheet,
            student=student,
            scanned_files=saved_paths,
        )
        
        # Evaluate if auto_evaluate is requested
        if request.data.get('auto_evaluate', True):
            try:
                evaluator = OMREvaluatorService(submission)
                evaluator.evaluate_and_save()
            except Exception as e:
                # Submission is saved but evaluation failed
                pass
        
        return Response(
            OMRSubmissionSerializer(submission, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=True, methods=['post'])
    def evaluate(self, request, pk=None):
        """
        Trigger evaluation for a submission.
        
        POST /api/omr/submissions/{id}/evaluate/
        """
        submission = self.get_object()
        
        if submission.status == 'evaluated':
            return Response(
                {'warning': 'Submission already evaluated', 'results': submission.evaluation_results},
                status=status.HTTP_200_OK
            )
        
        try:
            evaluator = OMREvaluatorService(submission)
            evaluator.evaluate_and_save()
            
            return Response(
                OMRSubmissionSerializer(submission, context={'request': request}).data,
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'])
    def results(self, request, pk=None):
        """
        Get detailed evaluation results.
        
        GET /api/omr/submissions/{id}/results/
        """
        submission = self.get_object()
        
        if submission.status != 'evaluated':
            return Response(
                {'error': f'Submission not yet evaluated. Status: {submission.status}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return Response({
            'candidate_info': submission.candidate_info,
            'score': float(submission.score) if submission.score else 0,
            'max_score': float(submission.max_score) if submission.max_score else 0,
            'percentage': float(submission.percentage) if submission.percentage else 0,
            'evaluation': submission.evaluation_results,
            'annotated_pdf_url': request.build_absolute_uri(submission.annotated_pdf.url) if submission.annotated_pdf else None,
        })


class AnswerKeyViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Answer Key management.
    """
    serializer_class = AnswerKeySerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filter answer keys by user's institute"""
        user = self.request.user
        if user.role == 'super_admin':
            return AnswerKey.objects.all()
        return AnswerKey.objects.filter(exam__institute=user.institute)
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
    
    @action(detail=False, methods=['get', 'post'], url_path='exam/(?P<exam_id>[^/.]+)')
    def by_exam(self, request, exam_id=None):
        """
        Get or create answer key for an exam.
        
        GET /api/omr/answer-keys/exam/{exam_id}/ - Get answer key
        POST /api/omr/answer-keys/exam/{exam_id}/ - Create/update answer key
        """
        exam = get_object_or_404(Exam, id=exam_id)
        
        if request.method == 'GET':
            try:
                answer_key = AnswerKey.objects.get(exam=exam)
                return Response(AnswerKeySerializer(answer_key).data)
            except AnswerKey.DoesNotExist:
                return Response(
                    {'error': 'No answer key found for this exam'},
                    status=status.HTTP_404_NOT_FOUND
                )
        
        else:  # POST
            answers = request.data.get('answers', {})
            
            answer_key, created = AnswerKey.objects.update_or_create(
                exam=exam,
                defaults={
                    'answers': answers,
                    'created_by': request.user,
                }
            )
            
            return Response(
                AnswerKeySerializer(answer_key).data,
                status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
            )


# Convenience API endpoints
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def exam_omr_status(request, exam_id):
    """
    Get OMR status for an exam.
    
    GET /api/omr/exam/{exam_id}/status/
    """
    exam = get_object_or_404(Exam, id=exam_id)
    
    omr_sheet = OMRSheet.objects.filter(exam=exam, is_primary=True).first()
    answer_key = AnswerKey.objects.filter(exam=exam).exists()
    submissions_count = OMRSubmission.objects.filter(omr_sheet__exam=exam).count()
    evaluated_count = OMRSubmission.objects.filter(
        omr_sheet__exam=exam, status='evaluated'
    ).count()
    
    return Response({
        'exam_id': exam.id,
        'exam_mode': exam.exam_mode,
        'omr_sheet_generated': omr_sheet is not None and omr_sheet.status == 'generated',
        'omr_sheet_id': omr_sheet.id if omr_sheet else None,
        'pdf_url': request.build_absolute_uri(omr_sheet.pdf_file.url) if omr_sheet and omr_sheet.pdf_file else None,
        'answer_key_exists': answer_key,
        'submissions_count': submissions_count,
        'evaluated_count': evaluated_count,
    })
