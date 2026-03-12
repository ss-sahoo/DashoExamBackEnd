"""
RAG (Retrieval-Augmented Generation) utilities
Supports both OpenAI and Ollama (free local AI)
"""
import os
import json
import requests
from typing import List, Dict, Any
import numpy as np
from django.conf import settings
from .models import Question, QuestionEmbedding
# Google AI import - optional
try:
    import google.generativeai as genai
    GOOGLE_AI_AVAILABLE = True
except ImportError:
    genai = None
    GOOGLE_AI_AVAILABLE = False

# Check which AI backend to use
def get_use_ollama():
    """Check if we should use Ollama"""
    try:
        from config import USE_OLLAMA
        result = USE_OLLAMA.lower() == 'true' if isinstance(USE_OLLAMA, str) else USE_OLLAMA
        return result
    except Exception as e:
        print(f"Config import error: {e}")
        return os.getenv('USE_OLLAMA', 'true').lower() == 'true'

def get_ollama_url():
    """Get Ollama base URL"""
    try:
        from config import OLLAMA_BASE_URL
        return OLLAMA_BASE_URL
    except:
        return os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')

# Initialize AI clients lazily
_openai_client = None
_gemini_configured = False

def get_openai_client():
    """Get or create OpenAI client"""
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        from config import OPENAI_API_KEY
        
        api_key = OPENAI_API_KEY or os.getenv('OPENAI_API_KEY', '')
        if api_key:
            _openai_client = OpenAI(api_key=api_key)
        else:
            raise ValueError("OPENAI_API_KEY not configured")
    return _openai_client

def configure_gemini():
    """Configure Gemini API"""
    global _gemini_configured
    if not _gemini_configured:
        if not GOOGLE_AI_AVAILABLE or genai is None:
            print("❌ Gemini configuration skipped: google-generativeai is not installed")
            return False

        try:
            from config import GEMINI_API_KEY as CONFIG_GEMINI_API_KEY
            api_key = (CONFIG_GEMINI_API_KEY or "").strip()
            key_source = "config.GEMINI_API_KEY"

            if not api_key:
                google_key = (os.getenv('GOOGLE_GEMINI_API_KEY', '') or '').strip()
                legacy_key = (os.getenv('GEMINI_API_KEY', '') or '').strip()
                api_key = google_key or legacy_key
                if google_key:
                    key_source = "GOOGLE_GEMINI_API_KEY"
                elif legacy_key:
                    key_source = "GEMINI_API_KEY"

            if api_key:
                print(f"🔎 Gemini key source: {key_source}")
                genai.configure(api_key=api_key)
                _gemini_configured = True
                print(" Gemini configured successfully")
                return True
            print("❌ Gemini configuration failed: no API key found in GOOGLE_GEMINI_API_KEY or GEMINI_API_KEY")
        except Exception as e:
            print(f"❌ Gemini configuration error: {e}")
    return _gemini_configured


def check_ollama_running():
    """Check if Ollama service is running"""
    try:
        ollama_url = get_ollama_url()
        response = requests.get(f'{ollama_url}/api/tags', timeout=2)
        is_running = response.status_code == 200
        if not is_running:
            print(f"❌ Ollama check failed: status {response.status_code}")
        return is_running
    except Exception as e:
        print(f"❌ Ollama connection error: {e}")
        return False


def generate_embedding_gemini(text: str) -> List[float]:
    """Generate embedding using Google Gemini (FREE)"""
    try:
        if not configure_gemini():
            raise ValueError("Gemini not configured")
        
        cleaned_text = text.replace("\n", " ").strip()
        if not cleaned_text:
            return [0.0] * 768
        
        result = genai.embed_content(
            model="models/text-embedding-004",
            content=cleaned_text,
            task_type="retrieval_document"
        )
        
        embedding = result['embedding']
        # Pad to 768 dimensions (Gemini's native size)
        if len(embedding) < 768:
            embedding = embedding + [0.0] * (768 - len(embedding))
        return embedding[:768]
    except Exception as e:
        print(f"❌ Gemini embedding error: {e}")
        return [0.0] * 768


def generate_embedding_ollama(text: str) -> List[float]:
    """Generate embedding using Ollama (free local AI)"""
    try:
        cleaned_text = text.replace("\n", " ").strip()
        if not cleaned_text:
            return [0.0] * 1536
        
        ollama_url = get_ollama_url()
        response = requests.post(
            f'{ollama_url}/api/embeddings',
            json={
                'model': 'nomic-embed-text',
                'prompt': cleaned_text
            },
            timeout=30
        )
        
        if response.status_code == 200:
            embedding = response.json()['embedding']
            # Pad or truncate to 1536 dimensions to match OpenAI format
            if len(embedding) < 1536:
                embedding = embedding + [0.0] * (1536 - len(embedding))
            return embedding[:1536]
        else:
            print(f"Ollama embedding error: {response.text}")
            return [0.0] * 1536
    except Exception as e:
        print(f"Error generating Ollama embedding: {e}")
        return [0.0] * 1536


def generate_embedding(text: str, model: str = "text-embedding-ada-002") -> List[float]:
    """
    Generate embedding vector for text
    Uses Ollama (free) if available, falls back to OpenAI
    
    Args:
        text: Text to embed
        model: Model name (used for OpenAI)
    
    Returns:
        List of floats representing the embedding vector
    """
    # Try Gemini first (FREE with good quota)
    try:
        if configure_gemini():
            print(" Using Gemini for embeddings (FREE)")
            return generate_embedding_gemini(text)
    except Exception as e:
        print(f"Gemini not available: {e}")
    
    # Try Ollama if enabled
    use_ollama = get_use_ollama()
    if use_ollama and check_ollama_running():
        print(" Using Ollama for embeddings")
        return generate_embedding_ollama(text)
    
    # Fall back to OpenAI
    try:
        cleaned_text = text.replace("\n", " ").strip()
        if not cleaned_text:
            return [0.0] * 1536
        
        print("⚠️ Using OpenAI for embeddings (paid)")
        client = get_openai_client()
        response = client.embeddings.create(
            input=cleaned_text,
            model=model
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return [0.0] * 768


def embed_question(question: Question) -> QuestionEmbedding:
    """
    Generate and store embeddings for a question
    
    Args:
        question: Question object to embed
    
    Returns:
        QuestionEmbedding object
    """
    # Prepare text for embedding
    question_text = question.question_text
    
    # For MCQ, include options
    combined_text = question_text
    if question.question_type == 'mcq' and question.options:
        options_text = " | ".join(question.options) if isinstance(question.options, list) else str(question.options)
        combined_text = f"{question_text}\nOptions: {options_text}"
    
    # Add solution if available
    if question.solution:
        combined_text = f"{combined_text}\nSolution: {question.solution}"
    
    # Generate embeddings
    text_embedding = generate_embedding(question_text)
    combined_embedding = generate_embedding(combined_text)
    
    # Create or update embedding
    embedding, created = QuestionEmbedding.objects.update_or_create(
        question=question,
        defaults={
            'text_embedding': text_embedding,
            'combined_embedding': combined_embedding,
            'embedding_model': 'text-embedding-ada-002'
        }
    )
    
    return embedding


def semantic_search_questions(
    query: str,
    institute_id: int,
    limit: int = 10,
    similarity_threshold: float = 0.7,
    filters: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """
    Search questions using semantic similarity
    
    Args:
        query: Search query text
        institute_id: Institute ID to filter by
        limit: Maximum number of results
        similarity_threshold: Minimum similarity score (0-1)
        filters: Additional filters (subject, difficulty, etc.)
    
    Returns:
        List of questions with similarity scores
    """
    from django.db.models import F
    from pgvector.django import CosineDistance
    
    # Generate query embedding
    query_embedding = generate_embedding(query)
    
    # Base queryset
    queryset = Question.objects.filter(
        institute_id=institute_id,
        is_active=True
    ).annotate(
        similarity=1 - CosineDistance(F('embedding__text_embedding'), query_embedding)
    ).filter(
        similarity__gte=similarity_threshold
    )
    
    # Apply additional filters
    if filters:
        if filters.get('subject'):
            queryset = queryset.filter(subject__icontains=filters['subject'])
        if filters.get('difficulty'):
            queryset = queryset.filter(difficulty=filters['difficulty'])
        if filters.get('question_type'):
            queryset = queryset.filter(question_type=filters['question_type'])
    
    # Order by similarity and limit
    results = queryset.order_by('-similarity')[:limit]
    
    # Format results
    formatted_results = []
    for question in results:
        formatted_results.append({
            'id': question.id,
            'question_text': question.question_text,
            'question_type': question.question_type,
            'subject': question.subject,
            'difficulty': question.difficulty,
            'marks': question.marks,
            'solution': question.solution,
            'similarity_score': float(question.similarity),
        })
    
    return formatted_results


def generate_chat_response(
    user_query: str,
    context_questions: List[Dict[str, Any]],
    chat_history: List[Dict[str, str]] = None,
    system_prompt: str = None
) -> Dict[str, Any]:
    """
    Generate chatbot response using RAG
    
    Args:
        user_query: User's question/query
        context_questions: Retrieved questions for context
        chat_history: Previous chat messages
        system_prompt: Custom system prompt
    
    Returns:
        Dict with answer and metadata
    """
    if not system_prompt:
        system_prompt = """You are an AI tutor assistant for an exam preparation platform. 
You help students understand concepts, solve problems, and learn effectively.

Use the provided question bank context to give accurate, helpful answers.
If answering based on the context, cite the question number.
If the context doesn't contain relevant information, say so and provide general guidance.

Be encouraging, clear, and educational in your responses."""
    
    # Prepare context from retrieved questions
    context_text = "Relevant questions from the question bank:\n\n"
    for i, q in enumerate(context_questions[:5], 1):  # Limit to top 5
        context_text += f"Question {i} (ID: {q['id']}, Subject: {q['subject']}):\n"
        context_text += f"Q: {q['question_text']}\n"
        if q.get('solution'):
            context_text += f"Solution: {q['solution']}\n"
        context_text += f"Similarity: {q['similarity_score']:.2%}\n\n"
    
    # Prepare messages
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": f"Context:\n{context_text}"}
    ]
    
    # Add chat history
    if chat_history:
        messages.extend(chat_history[-6:])  # Last 3 exchanges
    
    # Add current query
    messages.append({"role": "user", "content": user_query})
    
    try:
        # Try Gemini first (FREE with good quota)
        if configure_gemini():
            print(" Using Gemini for chat (FREE)")
            try:
                # Format messages for Gemini
                chat_text = ""
                for msg in messages:
                    role = msg['role']
                    content = msg['content']
                    if role == 'system':
                        chat_text = content + "\n\n" + chat_text
                    elif role == 'user':
                        chat_text += f"User: {content}\n\n"
                    elif role == 'assistant':
                        chat_text += f"Assistant: {content}\n\n"
                
                model = genai.GenerativeModel('gemini-2.5-flash')
                response = model.generate_content(chat_text)
                answer = response.text
                
                return {
                    'answer': answer,
                    'sources': [q['id'] for q in context_questions[:5]],
                    'context_used': len(context_questions),
                    'model': 'Gemini 2.5 Flash (FREE)'
                }
            except Exception as e:
                print(f"Gemini chat error: {e}")
        
        # Try Ollama if available and enabled
        use_ollama = get_use_ollama()
        ollama_running = check_ollama_running()
        print(f"🤖 AI Backend Check: USE_OLLAMA={use_ollama}, Ollama Running={ollama_running}")
        
        if use_ollama and ollama_running:
            print(" Using Ollama (FREE local AI)")
            # Format messages for Ollama
            prompt = ""
            for msg in messages:
                role = msg['role']
                content = msg['content']
                if role == 'system':
                    prompt += f"System: {content}\n\n"
                elif role == 'user':
                    prompt += f"User: {content}\n\n"
                elif role == 'assistant':
                    prompt += f"Assistant: {content}\n\n"
            
            prompt += "Assistant: "
            
            ollama_url = get_ollama_url()
            response = requests.post(
                f'{ollama_url}/api/generate',
                json={
                    'model': 'llama3.2:1b',
                    'prompt': prompt,
                    'stream': False,
                    'options': {
                        'temperature': 0.7,
                        'num_predict': 800
                    }
                },
                timeout=60
            )
            
            if response.status_code == 200:
                answer = response.json()['response']
                return {
                    'answer': answer,
                    'sources': [q['id'] for q in context_questions[:5]],
                    'context_used': len(context_questions),
                    'model': 'llama3.2 (Local/Free)'
                }
        
        # Fall back to OpenAI
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=800
        )
        
        answer = response.choices[0].message.content
        
        return {
            'answer': answer,
            'sources': [q['id'] for q in context_questions[:5]],
            'context_used': len(context_questions),
            'model': 'gpt-4o-mini (OpenAI)'
        }
    except Exception as e:
        print(f"Error generating chat response: {e}")
        return {
            'answer': "I'm having trouble connecting to the AI service. Please check if Ollama is running or OpenAI credits are available.",
            'sources': [],
            'context_used': 0,
            'error': str(e)
        }


def bulk_embed_questions(institute_id: int, batch_size: int = 50):
    """
    Generate embeddings for all questions in an institute
    
    Args:
        institute_id: Institute ID
        batch_size: Number of questions to process at once
    
    Returns:
        Dict with success/failure counts
    """
    questions = Question.objects.filter(
        institute_id=institute_id,
        is_active=True
    ).exclude(
        id__in=QuestionEmbedding.objects.values_list('question_id', flat=True)
    )
    
    total = questions.count()
    success_count = 0
    error_count = 0
    
    for i in range(0, total, batch_size):
        batch = questions[i:i + batch_size]
        
        for question in batch:
            try:
                embed_question(question)
                success_count += 1
            except Exception as e:
                print(f"Failed to embed question {question.id}: {e}")
                error_count += 1
    
    return {
        'total': total,
        'success': success_count,
        'errors': error_count
    }


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors"""
    vec1_np = np.array(vec1)
    vec2_np = np.array(vec2)
    
    dot_product = np.dot(vec1_np, vec2_np)
    norm1 = np.linalg.norm(vec1_np)
    norm2 = np.linalg.norm(vec2_np)
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    return float(dot_product / (norm1 * norm2))
