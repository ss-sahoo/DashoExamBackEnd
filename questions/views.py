from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
import pandas as pd
import io
import csv
import json
from .models import Question, QuestionBank, ExamQuestion, QuestionImage, QuestionComment, QuestionTemplate
from .serializers import (
    QuestionSerializer, QuestionCreateSerializer, QuestionBankSerializer,
    ExamQuestionSerializer, QuestionTemplateSerializer, QuestionSearchSerializer,
    BulkQuestionImportSerializer
)


class QuestionListView(generics.ListCreateAPIView):
    """List and create questions"""
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return QuestionCreateSerializer
        return QuestionSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = Question.objects.filter(institute=user.institute, is_active=True)
        
        # Apply filters
        search = self.request.query_params.get('search')
        subject = self.request.query_params.get('subject')
        topic = self.request.query_params.get('topic')
        difficulty = self.request.query_params.get('difficulty')
        question_type = self.request.query_params.get('question_type')
        question_bank = self.request.query_params.get('question_bank')
        is_verified = self.request.query_params.get('is_verified')
        
        if search:
            queryset = queryset.filter(
                Q(question_text__icontains=search) |
                Q(subject__icontains=search) |
                Q(topic__icontains=search)
            )
        
        if subject:
            queryset = queryset.filter(subject__icontains=subject)
        
        if topic:
            queryset = queryset.filter(topic__icontains=topic)
        
        if difficulty:
            queryset = queryset.filter(difficulty=difficulty)
        
        if question_type:
            queryset = queryset.filter(question_type=question_type)
        
        if question_bank:
            queryset = queryset.filter(question_bank_id=question_bank)
        
        if is_verified is not None:
            queryset = queryset.filter(is_verified=is_verified.lower() == 'true')
        
        # Filter by pattern section
        pattern_section = self.request.query_params.get('pattern_section')
        if pattern_section:
            queryset = queryset.filter(pattern_section_id=pattern_section)
        
        # Filter by absolute question number within pattern
        question_number = self.request.query_params.get('question_number')
        if question_number:
            queryset = queryset.filter(question_number_in_pattern=question_number)
        
        return queryset.order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(
            institute=self.request.user.institute,
            created_by=self.request.user
        )


class QuestionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Get, update, and delete questions"""
    serializer_class = QuestionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.can_manage_exams():
            return Question.objects.filter(institute=user.institute)
        return Question.objects.filter(institute=user.institute, is_active=True)


class QuestionBankListView(generics.ListCreateAPIView):
    """List and create question banks"""
    serializer_class = QuestionBankSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = QuestionBank.objects.filter(institute=user.institute)
        
        # Show public banks from other institutes
        if user.can_manage_exams():
            public_banks = QuestionBank.objects.filter(is_public=True).exclude(institute=user.institute)
            queryset = queryset.union(public_banks)
        
        return queryset.order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(
            institute=self.request.user.institute,
            created_by=self.request.user
        )


class QuestionBankDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Get, update, and delete question banks"""
    serializer_class = QuestionBankSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.can_manage_exams():
            return QuestionBank.objects.filter(institute=user.institute)
        return QuestionBank.objects.filter(
            Q(institute=user.institute) | Q(is_public=True)
        )


class ExamQuestionListView(generics.ListCreateAPIView):
    """List and create exam questions"""
    serializer_class = ExamQuestionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        exam_id = self.kwargs.get('exam_id')
        return ExamQuestion.objects.filter(exam_id=exam_id).order_by('question_number')

    def perform_create(self, serializer):
        exam_id = self.kwargs.get('exam_id')
        user = self.request.user
        
        # Check permissions
        try:
            from exams.models import Exam
            exam = Exam.objects.get(id=exam_id)
            if not user.can_manage_exams() or exam.institute != user.institute:
                raise permissions.PermissionDenied("You don't have permission to add questions to this exam")
        except Exam.DoesNotExist:
            raise permissions.PermissionDenied("Exam not found")
        
        serializer.save(exam_id=exam_id)


class QuestionTemplateListView(generics.ListAPIView):
    """List question templates"""
    queryset = QuestionTemplate.objects.filter(is_public=True)
    serializer_class = QuestionTemplateSerializer
    permission_classes = [permissions.IsAuthenticated]


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def bulk_import_questions(request):
    """Bulk import questions from JSON data"""
    serializer = BulkQuestionImportSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    user = request.user
    if not user.can_manage_exams():
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    
    questions_data = serializer.validated_data['questions_data']
    question_bank_id = serializer.validated_data.get('question_bank_id')
    subject = serializer.validated_data.get('subject')
    topic = serializer.validated_data.get('topic')
    
    created_questions = []
    errors = []
    
    with transaction.atomic():
        for i, question_data in enumerate(questions_data):
            try:
                # Set default values
                question_data['institute'] = user.institute
                question_data['created_by'] = user
                
                if question_bank_id:
                    question_data['question_bank_id'] = question_bank_id
                
                if subject:
                    question_data['subject'] = subject
                
                if topic:
                    question_data['topic'] = topic
                
                question = Question.objects.create(**question_data)
                created_questions.append(QuestionSerializer(question).data)
                
            except Exception as e:
                errors.append(f"Question {i+1}: {str(e)}")
    
    return Response({
        'success': True,
        'created_count': len(created_questions),
        'error_count': len(errors),
        'created_questions': created_questions,
        'errors': errors
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def bulk_import_csv(request):
    """Bulk import questions from CSV file"""
    user = request.user
    if not user.can_manage_exams():
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    
    if 'file' not in request.FILES:
        return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)
    
    file = request.FILES['file']
    question_bank_id = request.data.get('question_bank_id')
    subject = request.data.get('subject', '')
    topic = request.data.get('topic', '')
    
    if not file.name.endswith('.csv'):
        return Response({'error': 'File must be a CSV'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        # Read CSV file
        csv_data = file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_data))
        
        created_questions = []
        errors = []
        
        with transaction.atomic():
            for i, row in enumerate(csv_reader):
                try:
                    # Map CSV columns to question fields
                    question_data = {
                        'question_text': row.get('question_text', ''),
                        'question_type': row.get('question_type', 'single_mcq'),
                        'difficulty': row.get('difficulty', 'medium'),
                        'correct_answer': row.get('correct_answer', ''),
                        'solution': row.get('solution', ''),
                        'explanation': row.get('explanation', ''),
                        'marks': int(row.get('marks', 1)),
                        'negative_marks': float(row.get('negative_marks', 0.25)),
                        'subject': row.get('subject', subject),
                        'topic': row.get('topic', topic),
                        'subtopic': row.get('subtopic', ''),
                        'institute': user.institute,
                        'created_by': user,
                    }
                    
                    # Handle options for MCQ questions
                    if question_data['question_type'] in ['single_mcq', 'multiple_mcq']:
                        options = []
                        for j in range(1, 6):  # Support up to 5 options
                            option = row.get(f'option_{j}', '').strip()
                            if option:
                                options.append(option)
                        question_data['options'] = options
                    
                    # Handle tags
                    tags_str = row.get('tags', '')
                    if tags_str:
                        question_data['tags'] = [tag.strip() for tag in tags_str.split(',')]
                    
                    if question_bank_id:
                        question_data['question_bank_id'] = question_bank_id
                    
                    question = Question.objects.create(**question_data)
                    created_questions.append(QuestionSerializer(question).data)
                    
                except Exception as e:
                    errors.append(f"Row {i+2}: {str(e)}")
        
        return Response({
            'success': True,
            'created_count': len(created_questions),
            'error_count': len(errors),
            'created_questions': created_questions,
            'errors': errors
        })
        
    except Exception as e:
        return Response({'error': f'Failed to process CSV: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def bulk_import_excel(request):
    """Bulk import questions from Excel file"""
    user = request.user
    if not user.can_manage_exams():
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    
    if 'file' not in request.FILES:
        return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)
    
    file = request.FILES['file']
    question_bank_id = request.data.get('question_bank_id')
    subject = request.data.get('subject', '')
    topic = request.data.get('topic', '')
    
    if not (file.name.endswith('.xlsx') or file.name.endswith('.xls')):
        return Response({'error': 'File must be an Excel file (.xlsx or .xls)'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        # Read Excel file
        df = pd.read_excel(file)
        
        created_questions = []
        errors = []
        
        with transaction.atomic():
            for i, row in df.iterrows():
                try:
                    # Map Excel columns to question fields
                    question_data = {
                        'question_text': str(row.get('question_text', '')),
                        'question_type': str(row.get('question_type', 'single_mcq')),
                        'difficulty': str(row.get('difficulty', 'medium')),
                        'correct_answer': str(row.get('correct_answer', '')),
                        'solution': str(row.get('solution', '')),
                        'explanation': str(row.get('explanation', '')),
                        'marks': int(row.get('marks', 1)),
                        'negative_marks': float(row.get('negative_marks', 0.25)),
                        'subject': str(row.get('subject', subject)),
                        'topic': str(row.get('topic', topic)),
                        'subtopic': str(row.get('subtopic', '')),
                        'institute': user.institute,
                        'created_by': user,
                    }
                    
                    # Handle options for MCQ questions
                    if question_data['question_type'] in ['single_mcq', 'multiple_mcq']:
                        options = []
                        for j in range(1, 6):  # Support up to 5 options
                            option = str(row.get(f'option_{j}', '')).strip()
                            if option and option != 'nan':
                                options.append(option)
                        question_data['options'] = options
                    
                    # Handle tags
                    tags_str = str(row.get('tags', ''))
                    if tags_str and tags_str != 'nan':
                        question_data['tags'] = [tag.strip() for tag in tags_str.split(',')]
                    
                    if question_bank_id:
                        question_data['question_bank_id'] = question_bank_id
                    
                    question = Question.objects.create(**question_data)
                    created_questions.append(QuestionSerializer(question).data)
                    
                except Exception as e:
                    errors.append(f"Row {i+2}: {str(e)}")
        
        return Response({
            'success': True,
            'created_count': len(created_questions),
            'error_count': len(errors),
            'created_questions': created_questions,
            'errors': errors
        })
        
    except Exception as e:
        return Response({'error': f'Failed to process Excel: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def download_import_template(request):
    """Download CSV template for question import"""
    user = request.user
    if not user.can_manage_exams():
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    
    # Create CSV template
    template_data = [
        {
            'question_text': 'What is the capital of France?',
            'question_type': 'single_mcq',
            'difficulty': 'easy',
            'option_1': 'London',
            'option_2': 'Berlin',
            'option_3': 'Paris',
            'option_4': 'Madrid',
            'option_5': '',
            'correct_answer': 'Paris',
            'solution': 'Paris is the capital of France',
            'explanation': 'France is a country in Europe with Paris as its capital city',
            'marks': '1',
            'negative_marks': '0.25',
            'subject': 'Geography',
            'topic': 'European Capitals',
            'subtopic': 'Western Europe',
            'tags': 'capital, europe, france'
        },
        {
            'question_text': 'Solve: 2x + 5 = 15',
            'question_type': 'numerical',
            'difficulty': 'medium',
            'option_1': '',
            'option_2': '',
            'option_3': '',
            'option_4': '',
            'option_5': '',
            'correct_answer': '5',
            'solution': '2x = 15 - 5 = 10, x = 5',
            'explanation': 'Subtract 5 from both sides, then divide by 2',
            'marks': '2',
            'negative_marks': '0.5',
            'subject': 'Mathematics',
            'topic': 'Algebra',
            'subtopic': 'Linear Equations',
            'tags': 'algebra, equation, linear'
        }
    ]
    
    response = JsonResponse(template_data, safe=False)
    response['Content-Disposition'] = 'attachment; filename="question_import_template.csv"'
    response['Content-Type'] = 'text/csv'
    
    return response


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def use_question_template(request, template_id):
    """Use a question template to create a new question"""
    try:
        template = QuestionTemplate.objects.get(id=template_id)
    except QuestionTemplate.DoesNotExist:
        return Response({'error': 'Template not found'}, status=status.HTTP_404_NOT_FOUND)
    
    user = request.user
    if not user.can_manage_exams():
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    
    # Get template variables from request
    template_variables = request.data.get('variables', {})
    
    # Generate question from template
    try:
        question_data = generate_question_from_template(template, template_variables)
        
        # Set user and institute
        question_data['institute'] = user.institute
        question_data['created_by'] = user
        
        # Create the question
        question = Question.objects.create(**question_data)
        
        # Increment template usage
        template.increment_usage()
        
        return Response({
            'success': True,
            'question': QuestionSerializer(question).data,
            'message': f'Question created successfully using template "{template.name}"'
        })
        
    except Exception as e:
        return Response({
            'error': f'Failed to generate question from template: {str(e)}'
        }, status=status.HTTP_400_BAD_REQUEST)


def generate_question_from_template(template, variables):
    """Generate question data from template and variables"""
    template_data = template.template_data
    question_data = {
        'question_text': template.example_question,
        'question_type': template.question_type,
        'difficulty': template.difficulty,
        'subject': template.subject or variables.get('subject', ''),
        'topic': template.topic or variables.get('topic', ''),
        'tags': template.tags,
        'marks': variables.get('marks', 1),
        'negative_marks': variables.get('negative_marks', 0.25),
    }
    
    # Generate question text from template format
    if 'question_format' in template_data:
        question_text = template_data['question_format']
        for var, value in variables.items():
            question_text = question_text.replace(f'{{{var}}}', str(value))
        question_data['question_text'] = question_text
    
    # Generate options for MCQ questions
    if template.question_type in ['single_mcq', 'multiple_mcq'] and 'options_format' in template_data:
        options = []
        for option_template in template_data['options_format']:
            option_text = option_template
            for var, value in variables.items():
                option_text = option_text.replace(f'{{{var}}}', str(value))
            if option_text.strip():
                options.append(option_text)
        question_data['options'] = options
    
    # Generate correct answer
    if 'solution_format' in template_data:
        correct_answer = template_data['solution_format']
        for var, value in variables.items():
            correct_answer = correct_answer.replace(f'{{{var}}}', str(value))
        question_data['correct_answer'] = correct_answer
    else:
        question_data['correct_answer'] = variables.get('correct_answer', '')
    
    # Generate solution
    if 'explanation_template' in template_data:
        solution = template_data['explanation_template']
        for var, value in variables.items():
            solution = solution.replace(f'{{{var}}}', str(value))
        question_data['solution'] = solution
    else:
        question_data['solution'] = variables.get('solution', '')
    
    # Generate explanation
    question_data['explanation'] = variables.get('explanation', question_data.get('solution', ''))
    
    return question_data


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_template_categories(request):
    """Get all available template categories"""
    categories = [
        {'value': choice[0], 'label': choice[1]} 
        for choice in QuestionTemplate.TEMPLATE_CATEGORIES
    ]
    return Response(categories)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def search_templates(request):
    """Search question templates with filters"""
    user = request.user
    
    # Base queryset
    queryset = QuestionTemplate.objects.filter(is_public=True)
    
    # Apply filters
    category = request.GET.get('category')
    if category:
        queryset = queryset.filter(category=category)
    
    question_type = request.GET.get('question_type')
    if question_type:
        queryset = queryset.filter(question_type=question_type)
    
    difficulty = request.GET.get('difficulty')
    if difficulty:
        queryset = queryset.filter(difficulty=difficulty)
    
    subject = request.GET.get('subject')
    if subject:
        queryset = queryset.filter(subject__icontains=subject)
    
    search = request.GET.get('search')
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search) | 
            Q(description__icontains=search) |
            Q(tags__icontains=search)
        )
    
    # Order by featured first, then usage count
    queryset = queryset.order_by('-is_featured', '-usage_count', 'name')
    
    # Serialize results
    templates = []
    for template in queryset:
        templates.append({
            'id': template.id,
            'name': template.name,
            'description': template.description,
            'category': template.category,
            'question_type': template.question_type,
            'difficulty': template.difficulty,
            'subject': template.subject,
            'topic': template.topic,
            'example_question': template.example_question,
            'tags': template.tags,
            'usage_count': template.usage_count,
            'is_featured': template.is_featured,
            'created_at': template.created_at,
        })
    
    return Response({
        'templates': templates,
        'total': len(templates)
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def verify_question(request, question_id):
    """Verify a question"""
    try:
        question = Question.objects.get(id=question_id, institute=request.user.institute)
    except Question.DoesNotExist:
        return Response({'error': 'Question not found'}, status=status.HTTP_404_NOT_FOUND)
    
    user = request.user
    if not user.can_manage_exams():
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    
    question.is_verified = True
    question.verified_by = user
    question.save()
    
    return Response({'message': 'Question verified successfully'})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def add_question_comment(request, question_id):
    """Add a comment to a question"""
    try:
        question = Question.objects.get(id=question_id, institute=request.user.institute)
    except Question.DoesNotExist:
        return Response({'error': 'Question not found'}, status=status.HTTP_404_NOT_FOUND)
    
    comment_text = request.data.get('comment')
    rating = request.data.get('rating')
    is_review = request.data.get('is_review', False)
    
    if not comment_text:
        return Response({'error': 'Comment is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    comment = QuestionComment.objects.create(
        question=question,
        user=request.user,
        comment=comment_text,
        rating=rating,
        is_review=is_review
    )
    
    return Response({
        'comment': {
            'id': comment.id,
            'comment': comment.comment,
            'rating': comment.rating,
            'is_review': comment.is_review,
            'user_name': comment.user.get_full_name(),
            'created_at': comment.created_at
        }
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def question_statistics(request):
    """Get question statistics for the institute"""
    user = request.user
    if not user.can_manage_exams():
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    
    institute = user.institute
    
    stats = {
        'total_questions': Question.objects.filter(institute=institute).count(),
        'verified_questions': Question.objects.filter(institute=institute, is_verified=True).count(),
        'questions_by_type': {},
        'questions_by_difficulty': {},
        'questions_by_subject': {},
        'recent_questions': []
    }
    
    # Questions by type
    for question_type, _ in Question.QUESTION_TYPE_CHOICES:
        count = Question.objects.filter(institute=institute, question_type=question_type).count()
        stats['questions_by_type'][question_type] = count
    
    # Questions by difficulty
    for difficulty, _ in Question.DIFFICULTY_CHOICES:
        count = Question.objects.filter(institute=institute, difficulty=difficulty).count()
        stats['questions_by_difficulty'][difficulty] = count
    
    # Questions by subject
    subjects = Question.objects.filter(institute=institute).values_list('subject', flat=True).distinct()
    for subject in subjects:
        count = Question.objects.filter(institute=institute, subject=subject).count()
        stats['questions_by_subject'][subject] = count
    
    # Recent questions
    recent_questions = Question.objects.filter(institute=institute).order_by('-created_at')[:10]
    stats['recent_questions'] = QuestionSerializer(recent_questions, many=True).data
    
    return Response(stats)