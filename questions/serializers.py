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

    class Meta:
        model = Question
        fields = [
            'id', 'question_text', 'question_type', 'difficulty', 'options', 'correct_answer',
            'solution', 'explanation', 'marks', 'negative_marks', 'subject', 'topic', 'subtopic',
            'tags', 'question_bank', 'pattern_section', 'question_number_in_pattern', 'institute', 'created_by', 'created_by_name',
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
            'subtopic', 'tags', 'question_bank', 'pattern_section', 'question_number_in_pattern'
        ]

    def validate_options(self, value):
        question_type = self.initial_data.get('question_type')
        if question_type == 'mcq' and (not value or len(value) < 2):
            raise serializers.ValidationError("MCQ questions must have at least 2 options")
        return value


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
