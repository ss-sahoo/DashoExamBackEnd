import os
import django
from django.conf import settings

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from questions.models import ExtractionJob
from questions.services.agent_extraction_service import AgentExtractionService

def debug_job(job_id, subject):
    try:
        job = ExtractionJob.objects.get(id=job_id)
        print(f"Debugging Job: {job.id}")
        
        # Get separated content
        separated_content = None
        if job.pre_analysis_job and job.pre_analysis_job.subject_separated_content:
            raw_content = job.pre_analysis_job.subject_separated_content
            separated_content = {}
            for s, data in raw_content.items():
                if isinstance(data, dict):
                    separated_content[s] = data.get('content', '')
                else:
                    separated_content[s] = str(data)
            print(f"Found separated content for: {list(separated_content.keys())}")
        
        service = AgentExtractionService(
            gemini_key=getattr(settings, 'GEMINI_API_KEY', ''),
            mathpix_id=getattr(settings, 'MATHPIX_APP_ID', ''),
            mathpix_key=getattr(settings, 'MATHPIX_APP_KEY', '')
        )
        
        print(f"Starting extraction for {subject}...")
        all_questions = service.run_full_pipeline(
            job.file_path, 
            subjects_to_process=[subject],
            separated_content=separated_content
        )
        
        print(f"Extracted {len(all_questions)} questions.")
        for i, q in enumerate(all_questions[:2]):
            print(f"Q{i+1}: {q.get('question_text', '')[:50]}...")
            
    except Exception as e:
        print(f"Error during debug: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_job("0bb54e87-786c-482a-b4d8-c97f661246c3", "Mathematics")
