"""
Celery tasks for question extraction
"""
import logging
from uuid import UUID
from celery import shared_task
from django.core.cache import cache

from questions.services.extraction_pipeline import ExtractionPipeline
from questions.models import ExtractionJob

logger = logging.getLogger('extraction')


@shared_task(
    bind=True,
    name='questions.extract_questions',
    max_retries=3,
    default_retry_delay=60,  # 1 minute
    time_limit=1800,  # 30 minutes
    soft_time_limit=1700,  # 28 minutes (soft limit before hard limit)
)
def extract_questions_task(self, job_id: str):
    """
    Celery task to extract questions from uploaded file
    
    Args:
        job_id: UUID string of the extraction job
        
    Returns:
        Dictionary with extraction results
    """
    job_uuid = UUID(job_id)
    
    try:
        logger.info(f"Starting extraction task for job {job_id}")
        
        # Create pipeline and process file
        pipeline = ExtractionPipeline()
        pipeline.process_file(job_uuid)
        
        # Get final job status
        job = ExtractionJob.objects.get(id=job_uuid)
        
        result = {
            'success': True,
            'job_id': str(job.id),
            'status': job.status,
            'questions_extracted': job.questions_extracted,
            'questions_failed': job.questions_failed,
        }
        
        logger.info(f"Extraction task completed for job {job_id}: {result}")
        return result
        
    except ExtractionJob.DoesNotExist:
        error_msg = f"Extraction job {job_id} not found"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg
        }
    
    except Exception as exc:
        logger.error(f"Extraction task failed for job {job_id}: {str(exc)}", exc_info=True)
        
        # Retry with exponential backoff
        try:
            job = ExtractionJob.objects.get(id=job_uuid)
            
            # Check if we should retry
            if job.retry_count < 3:
                # Calculate exponential backoff: 2^retry_count minutes
                countdown = (2 ** job.retry_count) * 60
                
                logger.info(
                    f"Retrying extraction job {job_id} in {countdown} seconds "
                    f"(attempt {job.retry_count + 1}/3)"
                )
                
                # Update retry count
                job.retry_count += 1
                job.save(update_fields=['retry_count'])
                
                # Retry the task
                raise self.retry(exc=exc, countdown=countdown)
            else:
                # Max retries reached
                logger.error(f"Max retries reached for job {job_id}")
                job.mark_failed(f"Max retries reached: {str(exc)}")
                
        except ExtractionJob.DoesNotExist:
            pass
        
        return {
            'success': False,
            'error': str(exc)
        }


@shared_task(name='questions.cleanup_old_extraction_jobs')
def cleanup_old_extraction_jobs():
    """
    Periodic task to clean up old extraction jobs and files
    
    This should be run daily via Celery Beat
    """
    from datetime import timedelta
    from django.utils import timezone
    import os
    
    try:
        # Delete extraction jobs older than 30 days
        cutoff_date = timezone.now() - timedelta(days=30)
        
        old_jobs = ExtractionJob.objects.filter(
            created_at__lt=cutoff_date,
            status__in=['completed', 'failed']
        )
        
        deleted_count = 0
        for job in old_jobs:
            # Delete associated file if it exists
            if job.file_path and os.path.exists(job.file_path):
                try:
                    os.remove(job.file_path)
                    logger.info(f"Deleted file: {job.file_path}")
                except Exception as e:
                    logger.error(f"Failed to delete file {job.file_path}: {e}")
            
            # Delete job and related extracted questions (cascade)
            job.delete()
            deleted_count += 1
        
        logger.info(f"Cleaned up {deleted_count} old extraction jobs")
        
        return {
            'success': True,
            'deleted_count': deleted_count
        }
        
    except Exception as e:
        logger.error(f"Cleanup task failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


@shared_task(name='questions.update_extraction_metrics')
def update_extraction_metrics():
    """
    Periodic task to update extraction metrics and statistics
    
    This should be run hourly via Celery Beat
    """
    try:
        from django.db.models import Count, Avg, Sum
        from datetime import timedelta
        from django.utils import timezone
        
        # Calculate metrics for last 24 hours
        since = timezone.now() - timedelta(hours=24)
        
        metrics = ExtractionJob.objects.filter(
            created_at__gte=since
        ).aggregate(
            total_jobs=Count('id'),
            completed_jobs=Count('id', filter=models.Q(status='completed')),
            failed_jobs=Count('id', filter=models.Q(status='failed')),
            avg_processing_time=Avg('processing_time_seconds'),
            total_questions_extracted=Sum('questions_extracted'),
            total_tokens_used=Sum('tokens_used'),
        )
        
        # Store in cache for dashboard
        cache.set('extraction_metrics_24h', metrics, timeout=3600)  # 1 hour
        
        logger.info(f"Updated extraction metrics: {metrics}")
        
        return {
            'success': True,
            'metrics': metrics
        }
        
    except Exception as e:
        logger.error(f"Metrics update task failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }
