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
        # Use .only() to fetch only what we need and .iterator() to avoid loading all into RAM
        proctoring_records = ExamProctoring.objects.only('id', 'snapshots').all()
        
        total_records = proctoring_records.count()
        total_snapshots_processed = 0
        total_images_cleared = 0
        processed_count = 0
        
        self.stdout.write(f"Processing {total_records} proctoring records in memory-safe mode...")
        
        for record in proctoring_records.iterator():
            modified = False
            snapshots = record.snapshots or []
            processed_count += 1
            
            if processed_count % 5 == 0:
                self.stdout.write(f"  Progress: {processed_count}/{total_records} records...")
            
            for snapshot in snapshots:
                total_snapshots_processed += 1
                if 'image_data' in snapshot:
                    if not dry_run:
                        del snapshot['image_data']
                    total_images_cleared += 1
                    modified = True
            
            if modified and not dry_run:
                record.snapshots = snapshots
                # Use update instead of save(force_update=True) to be even lighter
                ExamProctoring.objects.filter(id=record.id).update(snapshots=snapshots)
                
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"DRY RUN: Would have cleared {total_images_cleared} images from {total_snapshots_processed} snapshots across {total_records} records."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Successfully cleared {total_images_cleared} Base64 images from the database! Total storage saved estimated: {total_images_cleared * 0.1:.1f} MB (assuming 100KB per image)"))
