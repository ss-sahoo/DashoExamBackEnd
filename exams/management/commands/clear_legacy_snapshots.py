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
        import gc
        dry_run = options['dry_run']
        
        # 1. Get IDs first - very light on memory
        record_ids = list(ExamProctoring.objects.values_list('id', flat=True))
        total_records = len(record_ids)
        
        total_snapshots_processed = 0
        total_images_cleared = 0
        processed_count = 0
        
        self.stdout.write(f"Processing {total_records} proctoring records in ULTRA-SAFE mode...")
        
        for rid in record_ids:
            # 2. Fetch only one record at a time by ID
            record = ExamProctoring.objects.filter(id=rid).only('snapshots').first()
            if not record:
                continue
                
            modified = False
            snapshots = record.snapshots or []
            
            for snapshot in snapshots:
                total_snapshots_processed += 1
                if 'image_data' in snapshot:
                    if not dry_run:
                        # Directly remove the large key
                        snapshot.pop('image_data', None)
                    total_images_cleared += 1
                    modified = True
            
            if modified and not dry_run:
                # 3. Update only the single record
                ExamProctoring.objects.filter(id=rid).update(snapshots=snapshots)
            
            processed_count += 1
            if processed_count % 5 == 0:
                self.stdout.write(f"  Progress: {processed_count}/{total_records} records (Cleared {total_images_cleared} images)...")
                # 4. Force clear memory
                del record
                del snapshots
                gc.collect()
                
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"DRY RUN: Would have cleared {total_images_cleared} images from {total_snapshots_processed} snapshots across {total_records} records."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Successfully cleared {total_images_cleared} Base64 images!"))
