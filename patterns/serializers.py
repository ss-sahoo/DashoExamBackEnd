from rest_framework import serializers
from .models import Subject, ExamPattern, PatternSection, PatternTemplate


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ['id', 'name', 'description', 'is_active', 'created_at', 'updated_at']


class PatternSectionSerializer(serializers.ModelSerializer):
    total_questions_in_section = serializers.ReadOnlyField()
    total_marks_in_section = serializers.ReadOnlyField()
    subject_name = serializers.ReadOnlyField(source='subject')
    marking_scheme = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PatternSection
        fields = [
            'id', 'name', 'subject', 'subject_name', 'question_type', 
            'start_question', 'end_question', 'marks_per_question', 'negative_marking', 
            'min_questions_to_attempt', 'is_compulsory', 'order', 
            'total_questions_in_section', 'total_marks_in_section', 'marking_scheme'
        ]

    def get_marking_scheme(self, obj):
        """Convert flat fields to marking_scheme object for frontend"""
        negative_marking_percentage = 0
        if obj.marks_per_question > 0 and obj.negative_marking > 0:
            negative_marking_percentage = (float(obj.negative_marking) / float(obj.marks_per_question)) * 100
        
        return {
            'max_marks': obj.marks_per_question,
            'negative_marking_percentage': round(negative_marking_percentage, 2),
            'partial_marking': obj.question_type == 'mcq',
            'marks_per_correct_option': 0,
            'tolerance_range': 0,
            'decimal_precision': 2,
            'manual_grading': obj.question_type == 'subjective'
        }

    def validate(self, attrs):
        if attrs.get('start_question', 0) >= attrs.get('end_question', 0):
            raise serializers.ValidationError("Start question must be less than end question")
        return attrs


class ExamPatternSerializer(serializers.ModelSerializer):
    sections = PatternSectionSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    institute_name = serializers.CharField(source='institute.name', read_only=True)

    class Meta:
        model = ExamPattern
        fields = [
            'id', 'name', 'description', 'institute', 'institute_name',
            'total_questions', 'total_duration', 'total_marks', 'is_active',
            'created_by', 'created_by_name', 'sections', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def validate(self, attrs):
        # Validate that sections don't overlap and cover all questions
        sections = self.initial_data.get('sections', [])
        if sections:
            total_questions = attrs.get('total_questions', 0)
            covered_questions = set()
            
            for section in sections:
                start = section['start_question']
                end = section['end_question']
                
                # Check for overlaps
                section_questions = set(range(start, end + 1))
                if covered_questions.intersection(section_questions):
                    raise serializers.ValidationError("Question ranges cannot overlap")
                
                covered_questions.update(section_questions)
            
            # Check if all questions are covered
            expected_questions = set(range(1, total_questions + 1))
            if covered_questions != expected_questions:
                raise serializers.ValidationError("All questions must be covered by sections")
        
        return attrs


class PatternSectionCreateSerializer(serializers.Serializer):
    """Serializer for creating sections with marking_scheme support"""
    name = serializers.CharField(max_length=100)
    subject = serializers.CharField(max_length=100)
    question_type = serializers.CharField(max_length=100)
    start_question = serializers.IntegerField(min_value=1)
    end_question = serializers.IntegerField(min_value=1)
    min_questions_to_attempt = serializers.IntegerField(default=0)
    is_compulsory = serializers.BooleanField(default=True)
    order = serializers.IntegerField(default=1)
    marking_scheme = serializers.DictField(required=False)
    # These will be populated from marking_scheme
    marks_per_question = serializers.IntegerField(required=False)
    negative_marking = serializers.DecimalField(max_digits=4, decimal_places=2, required=False)

    def validate_question_type(self, value):
        """Convert frontend question type names to backend format"""
        type_mapping = {
            'Single Correct MCQ': 'single_mcq',
            'Multiple Correct MCQ': 'multiple_mcq',
            'Numerical': 'numerical',
            'Subjective': 'subjective',
            'True/False': 'true_false',
            'Fill in the Blanks': 'fill_blank',
            'single_mcq': 'single_mcq',
            'multiple_mcq': 'multiple_mcq',
            'mcq': 'single_mcq',  # Default to single MCQ for backward compatibility
            'numerical': 'numerical',
            'subjective': 'subjective',
            'true_false': 'true_false',
            'fill_blank': 'fill_blank'
        }
        return type_mapping.get(value, 'single_mcq')

    def validate(self, attrs):
        # Extract marking scheme and convert to flat fields
        marking_scheme = attrs.pop('marking_scheme', None)
        
        if marking_scheme:
            max_marks = marking_scheme.get('max_marks', 4)
            negative_percentage = marking_scheme.get('negative_marking_percentage', 0)
            
            # Calculate negative marking from percentage
            negative_marking = (max_marks * negative_percentage) / 100 if negative_percentage > 0 else 0
            
            attrs['marks_per_question'] = max_marks
            attrs['negative_marking'] = round(negative_marking, 2)
        else:
            # Set defaults if not present
            if 'marks_per_question' not in attrs:
                attrs['marks_per_question'] = 4
            if 'negative_marking' not in attrs:
                attrs['negative_marking'] = 1.0

        # Subjective questions should have no negative marking
        if attrs.get('question_type') == 'subjective':
            attrs['negative_marking'] = 0
        
        # Validate question range
        if attrs.get('start_question', 0) >= attrs.get('end_question', 0):
            raise serializers.ValidationError("Start question must be less than end question")
        
        return attrs


class ExamPatternCreateSerializer(serializers.ModelSerializer):
    sections = PatternSectionCreateSerializer(many=True)

    class Meta:
        model = ExamPattern
        fields = [
            'name', 'description', 'total_questions', 'total_duration', 
            'total_marks', 'sections'
        ]

    def create(self, validated_data):
        sections_data = validated_data.pop('sections')
        pattern = ExamPattern.objects.create(**validated_data)
        
        for section_data in sections_data:
            PatternSection.objects.create(pattern=pattern, **section_data)
        
        return pattern


class PatternTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatternTemplate
        fields = '__all__'
