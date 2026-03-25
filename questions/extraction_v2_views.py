import os
import logging
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from django.conf import settings
from django.utils import timezone
from .models import ExtractionJob
from .services.extraction_service_client import extraction_client

logger = logging.getLogger('extraction')

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def start_extraction_v2(request):
    """
    Start extraction using the decoupled microservice (V2)
    POST /api/questions/extract-v2/
    """
    try:
        file_obj = request.FILES.get('file')
        exam_id = request.data.get('exam_id')
        pattern_id = request.data.get('pattern_id')
        
        if not file_obj or not exam_id or not pattern_id:
            return Response(
                {'error': 'Missing file, exam_id, or pattern_id'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Save file to disk (shared storage or verify path accessible)
        # For local dev, absolute path works
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'extraction_uploads')
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, f"v2_{timezone.now().timestamp()}_{file_obj.name}")
        
        with open(file_path, 'wb+') as dest:
            for chunk in file_obj.chunks():
                dest.write(chunk)
                
        # Create Job Record in Django
        from exams.models import Exam
        from patterns.models import ExamPattern
        
        exam = Exam.objects.get(id=exam_id)
        pattern = ExamPattern.objects.get(id=pattern_id)
        
        job = ExtractionJob.objects.create(
            exam=exam,
            pattern=pattern,
            created_by=request.user,
            file_name=file_obj.name,
            file_path=file_path,
            file_size=file_obj.size,
            file_type=file_obj.content_type,
            status='processing',
            ai_model_used='extraction-service-v2'
        )
        
        # Prepare extraction context from pattern
        pattern_sections = pattern.sections.all()
        subjects = list(pattern_sections.values_list('subject', flat=True).distinct())
        total_expected_questions = pattern.total_questions
        
        # Submit to Microservice
        try:
            # We pass the absolute path. Ensure service can read it!
            # In docker, we need shared volume. Localhost is fine.
            resp = extraction_client.submit_extraction(
                os.path.abspath(file_path), 
                {
                    "pattern_id": str(pattern_id),
                    "expected_question_count": total_expected_questions,
                    "subjects": subjects,
                    "job_id": str(job.id)
                }
            )
            
            # The service returns the same job_id we passed
            microservice_job_id = resp.get("job_id")
            # We don't need to save task_id since it matches job.id
            
            return Response({
                "job_id": str(job.id),
                "service_job_id": microservice_job_id,
                "status": "processing",
                "message": "Extraction started in background service"
            })
            
        except Exception as e:
            job.status = 'failed'
            job.error_message = str(e)
            job.save()
            raise e

    except Exception as e:
        logger.error(f"Extraction V2 failed: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_extraction_status_v2(request, job_id):
    """
    Check status via microservice
    GET /api/questions/extract-v2/<job_id>/status/
    """
    try:
        job = ExtractionJob.objects.get(id=job_id)
        
        # Poll service using same ID
        service_resp = extraction_client.get_status(str(job.id))
        service_status = service_resp.get("status")
        
        # Sync status
        if service_status == "completed" and job.status != "completed":
            # Here we should fetch results and likely save them to DB
            # For now, just update status
            job.status = "completed"
            job.save()
            
            # In a real impl, we'd parse service_resp['result'] and save ExtractedQuestions
            
        elif service_status == "failed":
            job.status = "failed"
            job.error_message = service_resp.get("error", "Unknown service error")
            job.save()
            
        return Response({
            "job_id": str(job.id),
            "status": job.status,
            "error": job.error_message,
            "service_status": service_status,
            "result_summary": service_resp.get("result", {}).get("metadata", {})
        })
        
    except ExtractionJob.DoesNotExist:
        return Response({'error': 'Job not found'}, status=404)
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return Response({'error': str(e)}, status=500)
