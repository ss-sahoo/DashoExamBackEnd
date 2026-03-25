from django.db.models.signals import post_save
from django.dispatch import receiver
from exams.models import Exam
from .models import OMRSheet
from .services.generator import OMRGeneratorService
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Exam)
def auto_generate_omr_sheet(sender, instance, created, **kwargs):
    """
    Automatically generate OMR sheet when an exam is published
    and its mode is offline_omr.
    """
    # Check if exam is published and in offline_omr mode
    if instance.status == 'published' and instance.exam_mode == 'offline_omr':
        # Check if it was already generated to avoid redundant generation
        if instance.omr_sheet_generated and instance.omr_sheet_file:
            return

        logger.info(f"Auto-generating OMR sheet for published exam: {instance.id}")

        # Get candidate fields from exam config
        candidate_fields = []
        if isinstance(instance.omr_config, dict):
            candidate_fields = instance.omr_config.get('candidate_fields', [])
        
        try:
            # Create or get the primary OMR sheet for this exam
            omr_sheet, _ = OMRSheet.objects.get_or_create(
                exam=instance,
                is_primary=True,
                defaults={'candidate_fields': candidate_fields}
            )
            
            # Skip if already being generated or already generated
            if omr_sheet.status not in ['generated', 'generating']:
                generator = OMRGeneratorService(instance)
                generator.generate_and_save(omr_sheet, candidate_fields=candidate_fields)
                
                # Update the exam model fields
                # We use instance.save() with update_fields to avoid full save,
                # but it still triggers the signal. The check at the top will prevent infinite loop.
                instance.omr_sheet_generated = True
                instance.omr_sheet_file = omr_sheet.pdf_file
                instance.omr_metadata = omr_sheet.metadata
                instance.save(update_fields=['omr_sheet_generated', 'omr_sheet_file', 'omr_metadata'])
                
                logger.info(f"Successfully auto-generated OMR sheet for exam {instance.id}")
        except Exception as e:
            logger.error(f"Auto OMR generation failed for exam {instance.id}: {str(e)}")
