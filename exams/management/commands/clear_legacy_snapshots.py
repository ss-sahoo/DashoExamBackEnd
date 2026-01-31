from django.core.management.base import BaseCommand
from exams.models import ExamProctoring
import json

class Command(BaseCommand):
    help = 'Clears Base64 image data from legacy JSON proctoring snapshots to save database space'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Shows what would be cleared without actually doing it',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        proctoring_records = ExamProctoring.objects.all()
        
        total_records = proctoring_records.count()
        total_snapshots_processed = 0
        total_images_cleared = 0
        
        self.stdout.write(f"Processing {total_records} proctoring records...")
        
        for record in proctoring_records:
            modified = False
            snapshots = record.snapshots or []
            
            for snapshot in snapshots:
                total_snapshots_processed += 1
                if 'image_data' in snapshot:
                    if not dry_run:
                        del snapshot['image_data']
                        snapshot['cleared'] = True
                    total_images_cleared += 1
                    modified = True
            
            if modified and not dry_run:
                record.snapshots = snapshots
                record.save()
                
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"DRY RUN: Would have cleared {total_images_cleared} images from {total_snapshots_processed} snapshots across {total_records} records."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Successfully cleared {total_images_cleared} Base64 images from the database! Total storage saved estimated: {total_images_cleared * 0.1:.1f} MB (assuming 100KB per image)"))
