"""
API views for question extraction
"""
import os
import logging
from uuid import UUID
from django.conf import settings
from django.core.files.storage import default_storage
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser

from questions.models import ExtractionJob, ExtractedQuestion
from questions.extraction_serializers import (
    ExtractionJobSerializer,
    ExtractedQuestionSerializer,
    ExtractionJobCreateSerializer,
    BulkImportSerializer,
    ExtractionStatusSerializer,
)
from questions.tasks import extract_questions_task
from questions.services.bulk_import import BulkImportService, BulkImportError

logger = logging.getLogger('extraction')


class ExtractionJobViewSet(viewsets.ModelViewSet):
    """ViewSet for managing extraction jobs"""
    
    serializer_class = ExtractionJobSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_queryset(self):
        """Get extraction jobs for current user"""
        user = self.request.user
        
        # Filter by user's institute
        queryset = ExtractionJob.objects.filter(
            exam__institute=user.institute
        ).select_related('exam', 'pattern', 'created_by')
        
        # Filter by status if provided
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Filter by exam if provided
        exam_id = self.request.query_params.get('exam_id')
        if exam_id:
            queryset = queryset.filter(exam_id=exam_id)
        
        return queryset.order_by('-created_at')
    
    @action(detail=False, methods=['post'], url_path='upload')
    def upload_file(self, request):
        """
        Upload file and create extraction job
        
        POST /api/questions/extraction-jobs/upload/
        """
        serializer = ExtractionJobCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            # Get validated data
            uploaded_file = serializer.validated_data['file']
            exam_id = serializer.validated_data['exam_id']
            pattern_id = serializer.validated_data['pattern_id']
            subject = serializer.validated_data.get('subject', '')
            
            # Get exam and pattern
            from exams.models import Exam
            from patterns.models import ExamPattern
            
            exam = Exam.objects.get(id=exam_id)
            pattern = ExamPattern.objects.get(id=pattern_id)
            
            # Check permissions
            if exam.institute != request.user.institute:
                return Response(
                    {'error': 'You do not have permission to upload files for this exam'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Save uploaded file
            upload_dir = os.path.join(settings.MEDIA_ROOT, 'extraction_uploads')
            os.makedirs(upload_dir, exist_ok=True)
            
            file_path = os.path.join(upload_dir, f"{timezone.now().timestamp()}_{uploaded_file.name}")
            
            with open(file_path, 'wb+') as destination:
                for chunk in uploaded_file.chunks():
                    destination.write(chunk)
            
            # Create extraction job
            job = ExtractionJob.objects.create(
                exam=exam,
                pattern=pattern,
                created_by=request.user,
                file_name=uploaded_file.name,
                file_type=uploaded_file.content_type,
                file_size=uploaded_file.size,
                file_path=file_path,
                status='pending',
            )
            
            # Trigger async extraction task
            extract_questions_task.delay(str(job.id))
            
            logger.info(
                f"Created extraction job {job.id} for file {uploaded_file.name} "
                f"by user {request.user.email}"
            )
            
            return Response(
                {
                    'job_id': str(job.id),
                    'status': job.status,
                    'message': 'File uploaded successfully. Extraction started.'
                },
                status=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            logger.error(f"File upload failed: {str(e)}", exc_info=True)
            return Response(
                {'error': f'Failed to upload file: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'], url_path='status')
    def get_status(self, request, pk=None):
        """
        Get extraction job status
        
        GET /api/questions/extraction-jobs/{job_id}/status/
        """
        try:
            job = self.get_object()
            
            # Calculate estimated time remaining
            estimated_time = None
            if job.status == 'processing' and job.processing_time_seconds:
                # Rough estimate based on progress
                if job.progress_percent > 0:
                    elapsed = job.processing_time_seconds
                    total_estimated = (elapsed / job.progress_percent) * 100
                    estimated_time = int(total_estimated - elapsed)
            
            serializer = ExtractionStatusSerializer({
                'job_id': job.id,
                'status': job.status,
                'progress_percent': job.progress_percent,
                'total_questions_found': job.total_questions_found,
                'questions_extracted': job.questions_extracted,
                'estimated_time_remaining': estimated_time,
                'error_message': job.error_message,
            })
            
            return Response(serializer.data)
            
        except Exception as e:
            logger.error(f"Failed to get job status: {str(e)}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'], url_path='questions')
    def get_extracted_questions(self, request, pk=None):
        """
        Get extracted questions for a job
        
        GET /api/questions/extraction-jobs/{job_id}/questions/
        """
        try:
            job = self.get_object()
            
            # Get extracted questions
            questions = ExtractedQuestion.objects.filter(job=job).order_by('id')
            
            # Filter by review status if requested
            requires_review = request.query_params.get('requires_review')
            if requires_review is not None:
                requires_review_bool = requires_review.lower() in ['true', '1', 'yes']
                questions = questions.filter(requires_review=requires_review_bool)
            
            # Filter by import status
            is_imported = request.query_params.get('is_imported')
            if is_imported is not None:
                is_imported_bool = is_imported.lower() in ['true', '1', 'yes']
                questions = questions.filter(is_imported=is_imported_bool)
            
            serializer = ExtractedQuestionSerializer(questions, many=True)
            
            return Response({
                'job_id': str(job.id),
                'status': job.status,
                'total_questions': questions.count(),
                'questions': serializer.data
            })
            
        except Exception as e:
            logger.error(f"Failed to get extracted questions: {str(e)}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ExtractedQuestionViewSet(viewsets.ModelViewSet):
    """ViewSet for managing extracted questions"""
    
    serializer_class = ExtractedQuestionSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get extracted questions for current user's institute"""
        user = self.request.user
        
        queryset = ExtractedQuestion.objects.filter(
            job__exam__institute=user.institute
        ).select_related('job', 'imported_question')
        
        # Filter by job if provided
        job_id = self.request.query_params.get('job_id')
        if job_id:
            queryset = queryset.filter(job_id=job_id)
        
        return queryset.order_by('id')
    
    def update(self, request, *args, **kwargs):
        """Update extracted question"""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        
        # Don't allow updating if already imported
        if instance.is_imported:
            return Response(
                {'error': 'Cannot update question that has already been imported'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        
        # Re-validate after update
        instance.validate()
        
        return Response(serializer.data)
    
    def destroy(self, request, *args, **kwargs):
        """Delete extracted question"""
        instance = self.get_object()
        
        # Don't allow deleting if already imported
        if instance.is_imported:
            return Response(
                {'error': 'Cannot delete question that has already been imported'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_import_questions(request):
    """
    Bulk import extracted questions into exam
    
    POST /api/questions/bulk-import/
    """
    serializer = BulkImportSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    try:
        job_id = serializer.validated_data['job_id']
        question_ids = serializer.validated_data['question_ids']
        mappings = serializer.validated_data['mappings']
        
        # Check permissions
        job = ExtractionJob.objects.get(id=job_id)
        if job.exam.institute != request.user.institute:
            return Response(
                {'error': 'You do not have permission to import questions for this exam'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Import questions
        import_service = BulkImportService()
        result = import_service.import_questions(job_id, mappings)
        
        return Response(result, status=status.HTTP_200_OK)
        
    except ExtractionJob.DoesNotExist:
        return Response(
            {'error': f'Extraction job not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except BulkImportError as e:
        logger.error(f"Bulk import failed: {str(e)}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.error(f"Bulk import failed: {str(e)}", exc_info=True)
        return Response(
            {'error': f'Failed to import questions: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def extraction_history(request):
    """
    Get extraction history for current user
    
    GET /api/questions/extraction-history/
    """
    try:
        user = request.user
        
        # Get extraction jobs
        jobs = ExtractionJob.objects.filter(
            exam__institute=user.institute
        ).select_related('exam', 'pattern', 'created_by').order_by('-created_at')
        
        # Pagination
        page_size = int(request.query_params.get('page_size', 20))
        page = int(request.query_params.get('page', 1))
        
        start = (page - 1) * page_size
        end = start + page_size
        
        total_count = jobs.count()
        jobs_page = jobs[start:end]
        
        serializer = ExtractionJobSerializer(jobs_page, many=True)
        
        return Response({
            'count': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': (total_count + page_size - 1) // page_size,
            'results': serializer.data
        })
        
    except Exception as e:
        logger.error(f"Failed to get extraction history: {str(e)}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_pattern_structure(request, pattern_id):
    """
    Get full pattern structure with capacity information
    
    GET /api/questions/pattern-structure/<pattern_id>/?exam_id=<exam_id>
    
    Returns:
    {
        "pattern_id": 31,
        "pattern_name": "JEE Main 2024",
        "total_required": 90,
        "total_filled": 65,
        "total_remaining": 25,
        "subjects": {
            "physics": {
                "total_required": 30,
                "total_filled": 20,
                "sections": [
                    {
                        "section_id": 5,
                        "section_name": "Section A",
                        "question_type": "single_mcq",
                        "required": 20,
                        "current": 15,
                        "remaining": 5,
                        "status": "incomplete"
                    }
                ]
            }
        }
    }
    """
    try:
        from questions.services.capacity_calculator import CapacityCalculator
        from patterns.models import ExamPattern
        
        exam_id = request.query_params.get('exam_id')
        if not exam_id:
            return Response(
                {'error': 'exam_id parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify pattern exists and user has access
        try:
            pattern = ExamPattern.objects.get(id=pattern_id)
        except ExamPattern.DoesNotExist:
            return Response(
                {'error': 'Pattern not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Calculate capacity
        calculator = CapacityCalculator()
        capacity_data = calculator.calculate_pattern_capacity(int(exam_id), int(pattern_id))
        
        return Response(capacity_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error getting pattern structure: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def analyze_extraction_mismatches(request):
    """
    Analyze mismatches between extracted questions and pattern requirements
    
    POST /api/questions/analyze-mismatches/
    
    Request:
    {
        "job_id": "uuid-here",
        "exam_id": 44,
        "pattern_id": 31
    }
    
    Returns:
    {
        "mismatches": [
            {
                "subject": "physics",
                "section_id": 5,
                "question_type": "single_mcq",
                "required": 20,
                "extracted": 25,
                "status": "overflow",
                "excess": 5
            }
        ],
        "summary": {
            "total_overflow": 10,
            "total_shortage": 5
        }
    }
    """
    try:
        from questions.services.capacity_calculator import CapacityCalculator
        
        job_id = request.data.get('job_id')
        exam_id = request.data.get('exam_id')
        pattern_id = request.data.get('pattern_id')
        
        if not all([job_id, exam_id, pattern_id]):
            return Response(
                {'error': 'job_id, exam_id, and pattern_id are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get extraction job
        try:
            job = ExtractionJob.objects.get(id=job_id)
        except ExtractionJob.DoesNotExist:
            return Response(
                {'error': 'Extraction job not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get extracted questions grouped by subject
        extracted_questions = ExtractedQuestion.objects.filter(job=job)
        
        # Group by subject
        subjects_data = {}
        for eq in extracted_questions:
            subject = eq.suggested_subject or eq.assigned_subject or 'ambiguous'
            if subject not in subjects_data:
                subjects_data[subject] = []
            
            subjects_data[subject].append({
                'question_type': eq.question_type,
                'subject': subject
            })
        
        grouped_data = {'subjects': subjects_data}
        
        # Analyze mismatches
        calculator = CapacityCalculator()
        mismatch_analysis = calculator.analyze_extraction_mismatches(
            int(exam_id),
            int(pattern_id),
            grouped_data
        )
        
        return Response(mismatch_analysis, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error analyzing mismatches: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
