from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from . import extraction_views
# Temporarily disabled AI/RAG features for deployment
# from . import rag_views

# Router for extraction viewsets
extraction_router = DefaultRouter()
extraction_router.register(r'extraction-jobs', extraction_views.ExtractionJobViewSet, basename='extraction-job')
extraction_router.register(r'extracted-questions', extraction_views.ExtractedQuestionViewSet, basename='extracted-question')

urlpatterns = [
    # Questions
    path('questions/', views.QuestionListView.as_view(), name='question-list'),
    path('questions/<int:pk>/', views.QuestionDetailView.as_view(), name='question-detail'),
    path('questions/<int:question_id>/verify/', views.verify_question, name='verify-question'),
    path('questions/<int:question_id>/comments/', views.add_question_comment, name='add-question-comment'),
    
    # Question banks
    path('question-banks/', views.QuestionBankListView.as_view(), name='question-bank-list'),
    path('question-banks/<int:pk>/', views.QuestionBankDetailView.as_view(), name='question-bank-detail'),
    
    # Exam questions
    path('exams/<int:exam_id>/questions/', views.ExamQuestionListView.as_view(), name='exam-question-list'),
    
    # Templates
    path('templates/', views.QuestionTemplateListView.as_view(), name='question-template-list'),
    path('templates/search/', views.search_templates, name='search-templates'),
    path('templates/categories/', views.get_template_categories, name='template-categories'),
    path('templates/<int:template_id>/use/', views.use_question_template, name='use-question-template'),
    
    # AI Generation
    path('ai/generate-question/', views.generate_ai_question, name='ai-generate-question'),
    
    # Bulk operations
    path('bulk-import/', views.bulk_import_questions, name='bulk-import-questions'),
    path('bulk-import-csv/', views.bulk_import_csv, name='bulk-import-csv'),
    path('bulk-import-excel/', views.bulk_import_excel, name='bulk-import-excel'),
    path('download-template/', views.download_import_template, name='download-import-template'),
    
    # Statistics
    path('statistics/', views.question_statistics, name='question-statistics'),
    
    # AI Question Extraction Endpoints
    path('bulk-extract/', extraction_views.ExtractionJobViewSet.as_view({'post': 'upload_file'}), name='bulk-extract'),
    path('extraction-status/<uuid:pk>/', extraction_views.ExtractionJobViewSet.as_view({'get': 'get_status'}), name='extraction-status'),
    path('extracted/<uuid:pk>/', extraction_views.ExtractionJobViewSet.as_view({'get': 'get_extracted_questions'}), name='extracted-questions'),
    path('bulk-import-extracted/', extraction_views.bulk_import_questions, name='bulk-import-extracted'),
    path('extraction-history/', extraction_views.extraction_history, name='extraction-history'),
    
    # Enhanced Extraction Endpoints
    path('pattern-structure/<int:pattern_id>/', extraction_views.get_pattern_structure, name='pattern-structure'),
    path('analyze-mismatches/', extraction_views.analyze_extraction_mismatches, name='analyze-mismatches'),
    
    # Include extraction router URLs
    path('', include(extraction_router.urls)),
    
    # AI & RAG Endpoints - Temporarily disabled for deployment
    # Uncomment these when you have more server resources and install AI packages
    # path('semantic-search/', rag_views.semantic_search_view, name='semantic-search'),
    # path('chatbot/', rag_views.chatbot_query_view, name='chatbot-query'),
    # path('chat-history/', rag_views.chat_history_view, name='chat-history'),
    # path('<int:question_id>/embed/', rag_views.embed_single_question_view, name='embed-question'),
    # path('bulk-embed/', rag_views.bulk_embed_questions_view, name='bulk-embed'),
    # path('embedding-stats/', rag_views.embedding_stats_view, name='embedding-stats'),
]
