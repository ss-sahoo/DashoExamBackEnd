from rest_framework import serializers
from .models import Question, QuestionBank, ExamQuestion, QuestionImage, QuestionComment, QuestionTemplate
from accounts.serializers import UserSerializer


class QuestionImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionImage
        fields = ['id', 'image', 'caption', 'order']


class QuestionCommentSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)

    class Meta:
        model = QuestionComment
        fields = ['id', 'user', 'user_name', 'comment', 'is_review', 'rating', 'created_at']
        read_only_fields = ['id', 'user', 'created_at']


class QuestionSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    verified_by_name = serializers.CharField(source='verified_by.get_full_name', read_only=True)
    images = QuestionImageSerializer(many=True, read_only=True)
    comments = QuestionCommentSerializer(many=True, read_only=True)
    exam_title = serializers.CharField(source='exam.title', read_only=True)

    class Meta:
        model = Question
        fields = [
            'id', 'question_text', 'question_type', 'difficulty', 'options', 'correct_answer',
            'solution', 'explanation', 'marks', 'negative_marks', 'subject', 'topic', 'subtopic',
            'tags', 'question_bank', 'exam', 'exam_title', 'question_number', 'question_number_in_pattern',
            'pattern_section_id', 'pattern_section_name', 'institute', 'created_by', 'created_by_name',
            'is_active', 'is_verified', 'verified_by', 'verified_by_name', 'verified_at',
            'usage_count', 'success_rate', 'images', 'comments', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'created_by', 'verified_by', 'verified_at', 'usage_count', 'success_rate',
            'created_at', 'updated_at'
        ]


class QuestionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = [
            'question_text', 'question_type', 'difficulty', 'options', 'correct_answer',
            'solution', 'explanation', 'marks', 'negative_marks', 'subject', 'topic',
            'subtopic', 'tags', 'question_bank', 'exam', 'question_number',
            'pattern_section_id', 'pattern_section_name', 'question_number_in_pattern'
        ]
        extra_kwargs = {
            'exam': {'required': False, 'allow_null': True, 'default': None},
            'question_number': {'required': False, 'allow_null': True},
            'pattern_section_id': {'required': False, 'allow_null': True},
            'pattern_section_name': {'required': False, 'allow_null': True},
            'question_number_in_pattern': {'required': False, 'allow_null': True},
        }
    
    def run_validators(self, value):
        """
        Override to skip unique_together validation - we handle duplicates in create()
        """
        # Get all validators except UniqueTogetherValidator
        for validator in self.validators:
            if hasattr(validator, 'requires_context'):
                # Skip UniqueTogetherValidator
                if 'UniqueTogetherValidator' in type(validator).__name__:
                    continue
            if hasattr(validator, 'set_context'):
                validator.set_context(self)
            try:
                validator(value)
            except serializers.ValidationError as exc:
                # Skip unique_together errors - we'll handle them in create()
                if 'unique set' in str(exc).lower():
                    continue
                raise

    def validate(self, data):
        initial = getattr(self, 'initial_data', {})

        exam = data.get('exam')
        pattern_section_id = data.get('pattern_section_id') or initial.get('pattern_section_id')

        # Allow pattern-only questions (no exam) but ensure at least one context is provided
        if not exam and not pattern_section_id:
            raise serializers.ValidationError({
                'exam': 'Provide an exam or pattern_section_id to associate this question.'
            })

        # Ensure question number exists (fallback to supplied question_number_in_pattern/current number)
        question_number = data.get('question_number')
        if question_number in (None, ''):
            fallback_number = initial.get('question_number') or initial.get('question_number_in_pattern')
            if fallback_number:
                data['question_number'] = fallback_number
            else:
                raise serializers.ValidationError({'question_number': 'Question number is required.'})

        # Store pattern-level question number if provided
        if 'question_number_in_pattern' not in data:
            fallback_pattern_number = initial.get('question_number_in_pattern') or data.get('question_number')
            data['question_number_in_pattern'] = fallback_pattern_number

        # Store and ensure pattern_section_id is in data
        data['pattern_section_id'] = pattern_section_id

        # Auto-populate pattern section name if missing
        if pattern_section_id:
            try:
                from patterns.models import PatternSection
                section = PatternSection.objects.get(id=pattern_section_id)
                data['pattern_section_name'] = section.name
            except PatternSection.DoesNotExist:
                data['pattern_section_name'] = ''
        else:
            data['pattern_section_name'] = ''
        
        # Validate options for MCQ
        question_type = data.get('question_type')
        options = data.get('options', [])
        if question_type in ['single_mcq', 'multiple_mcq'] and (not options or len(options) < 2):
            raise serializers.ValidationError({'options': 'MCQ questions must have at least 2 options'})
        
        return data
    
    def create(self, validated_data):
        """
        Create or update a question. If a question with the same exam, section and question_number
        already exists, update it instead of creating a duplicate.
        """
        exam = validated_data.get('exam')
        question_number = validated_data.get('question_number')
        pattern_section_id = validated_data.get('pattern_section_id')
        institute = validated_data.get('institute') or (self.context['request'].user.institute if 'request' in self.context else None)
        
        # Check for existing question with same exam, section and question_number
        if exam and question_number and institute:
            exam_id = exam.id if hasattr(exam, 'id') else exam
            existing_question = Question.objects.filter(
                exam_id=exam_id,
                pattern_section_id=pattern_section_id,
                question_number=question_number,
                institute=institute,
                is_active=True
            ).first()
            
            if existing_question:
                # Update existing question
                for field, value in validated_data.items():
                    if field not in ['institute', 'created_by', 'exam']:
                        setattr(existing_question, field, value)
                existing_question.save()
                return existing_question
        
        # Create new question
        return super().create(validated_data)


class QuestionBankSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    institute_name = serializers.CharField(source='institute.name', read_only=True)
    question_count = serializers.SerializerMethodField()

    class Meta:
        model = QuestionBank
        fields = [
            'id', 'name', 'description', 'institute', 'institute_name', 'is_public',
            'created_by', 'created_by_name', 'question_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def get_question_count(self, obj):
        return obj.questions.filter(is_active=True).count()


class ExamQuestionSerializer(serializers.ModelSerializer):
    question = QuestionSerializer(read_only=True)
    question_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = ExamQuestion
        fields = [
            'id', 'exam', 'question', 'question_id', 'question_number', 'section_name',
            'marks', 'negative_marks', 'order'
        ]
        read_only_fields = ['id']


class QuestionTemplateSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)

    class Meta:
        model = QuestionTemplate
        fields = [
            'id', 'name', 'description', 'question_type', 'template_data',
            'is_public', 'created_by', 'created_by_name', 'created_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at']


class QuestionSearchSerializer(serializers.Serializer):
    search = serializers.CharField(required=False)
    subject = serializers.CharField(required=False)
    topic = serializers.CharField(required=False)
    difficulty = serializers.ChoiceField(choices=Question.DIFFICULTY_CHOICES, required=False)
    question_type = serializers.ChoiceField(choices=Question.QUESTION_TYPE_CHOICES, required=False)
    tags = serializers.ListField(child=serializers.CharField(), required=False)
    question_bank = serializers.IntegerField(required=False)
    is_verified = serializers.BooleanField(required=False)
    created_by = serializers.IntegerField(required=False)


class BulkQuestionImportSerializer(serializers.Serializer):
    questions_data = serializers.JSONField()
    question_bank_id = serializers.IntegerField(required=False)
    subject = serializers.CharField(required=False)
    topic = serializers.CharField(required=False)

    def validate_questions_data(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Questions data must be a list")
        
        for i, question in enumerate(value):
            required_fields = ['question_text', 'question_type', 'correct_answer']
            for field in required_fields:
                if field not in question:
                    raise serializers.ValidationError(f"Question {i+1} missing required field: {field}")
        
        return value
