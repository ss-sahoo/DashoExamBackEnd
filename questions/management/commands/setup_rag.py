"""
Management command to setup RAG system and generate embeddings
"""
from django.core.management.base import BaseCommand
from django.db import connection
from questions.models import Question
from questions.rag_utils import bulk_embed_questions
from accounts.models import Institute


class Command(BaseCommand):
    help = 'Setup RAG system and generate embeddings for questions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--institute-id',
            type=int,
            help='Institute ID to generate embeddings for (if not provided, does all)'
        )
        parser.add_argument(
            '--check-only',
            action='store_true',
            help='Only check if pgvector is installed, don\'t generate embeddings'
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('🚀 RAG System Setup'))
        self.stdout.write('')
        
        # Check if pgvector extension is installed
        self.stdout.write('📊 Checking pgvector extension...')
        with connection.cursor() as cursor:
            cursor.execute("SELECT extname FROM pg_extension WHERE extname = 'vector';")
            result = cursor.fetchone()
            
            if result:
                self.stdout.write(self.style.SUCCESS('  ✅ pgvector extension is installed'))
            else:
                self.stdout.write(self.style.ERROR('  ❌ pgvector extension is NOT installed'))
                self.stdout.write('')
                self.stdout.write(self.style.WARNING('  Please install pgvector:'))
                self.stdout.write('    sudo apt-get install postgresql-14-pgvector')
                self.stdout.write('    sudo -u postgres psql exam_flow_db -c "CREATE EXTENSION vector;"')
                return
        
        if options['check_only']:
            return
        
        self.stdout.write('')
        
        # Generate embeddings
        institute_id = options.get('institute_id')
        
        if institute_id:
            try:
                institute = Institute.objects.get(id=institute_id)
                self.stdout.write(f'📚 Generating embeddings for: {institute.name}')
            except Institute.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'❌ Institute with ID {institute_id} not found'))
                return
            
            institutes = [institute]
        else:
            institutes = Institute.objects.all()
            self.stdout.write(f'📚 Generating embeddings for all institutes ({institutes.count()})')
        
        self.stdout.write('')
        
        total_success = 0
        total_errors = 0
        
        for institute in institutes:
            self.stdout.write(f'Processing: {institute.name}...')
            
            question_count = Question.objects.filter(
                institute=institute,
                is_active=True
            ).count()
            
            if question_count == 0:
                self.stdout.write(self.style.WARNING(f'  ⚠️  No questions found'))
                continue
            
            result = bulk_embed_questions(institute.id)
            
            total_success += result['success']
            total_errors += result['errors']
            
            self.stdout.write(self.style.SUCCESS(
                f"  ✅ Success: {result['success']}/{result['total']}"
            ))
            if result['errors'] > 0:
                self.stdout.write(self.style.ERROR(
                    f"  ❌ Errors: {result['errors']}"
                ))
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('✅ RAG Setup Complete!'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write('')
        self.stdout.write(f'  Total Embedded: {total_success}')
        if total_errors > 0:
            self.stdout.write(f'  Total Errors: {total_errors}')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('🎯 Next Steps:'))
        self.stdout.write('  1. Test semantic search: POST /api/questions/semantic-search/')
        self.stdout.write('  2. Test chatbot: POST /api/questions/chatbot/')
        self.stdout.write('  3. Check stats: GET /api/questions/embedding-stats/')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('💡 Tip: New questions will auto-generate embeddings on creation'))
        self.stdout.write('')

