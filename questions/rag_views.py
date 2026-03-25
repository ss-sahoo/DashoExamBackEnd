"""
RAG-powered API endpoints for semantic search and chatbot
"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from .models import Question, ChatHistory, QuestionEmbedding
from .rag_utils import (
    semantic_search_questions,
    generate_chat_response,
    embed_question,
    bulk_embed_questions
)
from .serializers import QuestionSerializer


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def semantic_search_view(request):
    """
    Semantic search for questions using vector similarity
    
    POST /api/questions/semantic-search/
    {
        "query": "questions about motion and velocity",
        "subject": "Physics",  // optional
        "difficulty": "medium",  // optional
        "question_type": "mcq",  // optional
        "limit": 10  // optional, default 10
    }
    """
    query = request.data.get('query')
    if not query:
        return Response(
            {'error': 'Query parameter is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    limit = request.data.get('limit', 10)
    similarity_threshold = request.data.get('similarity_threshold', 0.6)
    
    filters = {}
    if request.data.get('subject'):
        filters['subject'] = request.data['subject']
    if request.data.get('difficulty'):
        filters['difficulty'] = request.data['difficulty']
    if request.data.get('question_type'):
        filters['question_type'] = request.data['question_type']
    
    try:
        results = semantic_search_questions(
            query=query,
            institute_id=request.user.institute.id if request.user.institute else None,
            limit=limit,
            similarity_threshold=similarity_threshold,
            filters=filters
        )
        
        return Response({
            'query': query,
            'results': results,
            'count': len(results)
        })
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chatbot_query_view(request):
    """
    AI chatbot with RAG for exam assistance
    
    POST /api/questions/chatbot/
    {
        "query": "Explain Newton's first law",
        "session_id": "unique-session-id",  // optional
        "include_history": true  // optional, default false
    }
    """
    user_query = request.data.get('query')
    if not user_query:
        return Response(
            {'error': 'Query parameter is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    session_id = request.data.get('session_id', f'session_{request.user.id}_{int(request._request.time.time() if hasattr(request._request, "time") else 0)}')
    include_history = request.data.get('include_history', False)
    
    try:
        # 1. Retrieve relevant questions using semantic search
        relevant_questions = semantic_search_questions(
            query=user_query,
            institute_id=request.user.institute.id if request.user.institute else None,
            limit=5,
            similarity_threshold=0.5
        )
        
        # 2. Get chat history if requested
        chat_history = []
        if include_history:
            history_records = ChatHistory.objects.filter(
                user=request.user,
                session_id=session_id
            ).order_by('-created_at')[:6]  # Last 3 exchanges
            
            chat_history = [
                {"role": record.role, "content": record.content}
                for record in reversed(history_records)
            ]
        
        # 3. Generate response using RAG
        response_data = generate_chat_response(
            user_query=user_query,
            context_questions=relevant_questions,
            chat_history=chat_history
        )
        
        # 4. Save chat history
        with transaction.atomic():
            # Save user message
            ChatHistory.objects.create(
                user=request.user,
                session_id=session_id,
                role='user',
                content=user_query
            )
            
            # Save assistant response
            ChatHistory.objects.create(
                user=request.user,
                session_id=session_id,
                role='assistant',
                content=response_data['answer'],
                metadata={
                    'sources': response_data.get('sources', []),
                    'model': response_data.get('model', 'unknown')
                }
            )
        
        return Response({
            'answer': response_data['answer'],
            'sources': relevant_questions,
            'session_id': session_id,
            'model': response_data.get('model', 'gpt-4o-mini')
        })
    
    except Exception as e:
        return Response(
            {'error': str(e), 'answer': 'Sorry, I encountered an error. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def chat_history_view(request):
    """
    Get chat history for a session
    
    GET /api/questions/chat-history/?session_id=xxx
    """
    session_id = request.query_params.get('session_id')
    if not session_id:
        return Response(
            {'error': 'session_id parameter is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    history = ChatHistory.objects.filter(
        user=request.user,
        session_id=session_id
    ).order_by('created_at')
    
    return Response({
        'session_id': session_id,
        'messages': [
            {
                'role': msg.role,
                'content': msg.content,
                'metadata': msg.metadata,
                'created_at': msg.created_at
            }
            for msg in history
        ]
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def embed_single_question_view(request, question_id):
    """
    Generate embedding for a single question
    
    POST /api/questions/{id}/embed/
    """
    if not request.user.can_manage_exams():
        return Response(
            {'error': 'Permission denied'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        question = Question.objects.get(
            id=question_id,
            institute=request.user.institute
        )
    except Question.DoesNotExist:
        return Response(
            {'error': 'Question not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    try:
        embedding = embed_question(question)
        return Response({
            'message': 'Embedding generated successfully',
            'question_id': question.id,
            'embedding_id': embedding.question_id
        })
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_embed_questions_view(request):
    """
    Generate embeddings for all questions in the institute
    
    POST /api/questions/bulk-embed/
    {
        "batch_size": 50  // optional
    }
    """
    if not request.user.can_manage_exams():
        return Response(
            {'error': 'Permission denied'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    batch_size = request.data.get('batch_size', 50)
    
    try:
        result = bulk_embed_questions(
            institute_id=request.user.institute.id,
            batch_size=batch_size
        )
        
        return Response({
            'message': 'Bulk embedding completed',
            'total_questions': result['total'],
            'successful': result['success'],
            'failed': result['errors']
        })
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def embedding_stats_view(request):
    """
    Get embedding statistics for the institute
    
    GET /api/questions/embedding-stats/
    """
    if not request.user.institute:
        return Response(
            {'error': 'User not associated with any institute'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    total_questions = Question.objects.filter(
        institute=request.user.institute,
        is_active=True
    ).count()
    
    embedded_questions = QuestionEmbedding.objects.filter(
        question__institute=request.user.institute
    ).count()
    
    pending = total_questions - embedded_questions
    percentage = (embedded_questions / total_questions * 100) if total_questions > 0 else 0
    
    return Response({
        'total_questions': total_questions,
        'embedded': embedded_questions,
        'pending': pending,
        'percentage': round(percentage, 2)
    })

