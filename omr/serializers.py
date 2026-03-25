"""
OMR App Serializers
"""
from rest_framework import serializers
from .models import OMRSheet, OMRSubmission, AnswerKey


class OMRSheetSerializer(serializers.ModelSerializer):
    """Serializer for OMR Sheet"""
    exam_title = serializers.CharField(source='exam.title', read_only=True)
    pdf_url = serializers.SerializerMethodField()
    
    class Meta:
        model = OMRSheet
        fields = [
            'id', 'sheet_id', 'exam', 'exam_title', 'pdf_file', 'pdf_url',
            'metadata', 'candidate_fields', 'question_config',
            'status', 'generation_error', 'is_primary',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'sheet_id', 'pdf_file', 'pdf_url', 'metadata',
            'status', 'generation_error', 'created_at', 'updated_at'
        ]
    
    def get_pdf_url(self, obj):
        if obj.pdf_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.pdf_file.url)
            return obj.pdf_file.url
        return None


class OMRSheetGenerateSerializer(serializers.Serializer):
    """Serializer for OMR sheet generation request"""
    candidate_fields = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        help_text="List of candidate field configurations"
    )
    
    def validate_candidate_fields(self, value):
        """Validate candidate field structure"""
        for field in value:
            if 'name' not in field:
                raise serializers.ValidationError("Each field must have a 'name'")
            if 'type' not in field:
                field['type'] = 'digits'  # Default type
            if field['type'] == 'digits' and 'digits' not in field:
                raise serializers.ValidationError(
                    f"Field '{field['name']}' of type 'digits' must specify 'digits' count"
                )
        return value


class OMRSubmissionSerializer(serializers.ModelSerializer):
    """Serializer for OMR Submission"""
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    student_email = serializers.CharField(source='student.email', read_only=True)
    exam_title = serializers.CharField(source='omr_sheet.exam.title', read_only=True)
    annotated_pdf_url = serializers.SerializerMethodField()
    
    class Meta:
        model = OMRSubmission
        fields = [
            'id', 'omr_sheet', 'attempt', 'student', 'student_name', 'student_email',
            'exam_title', 'scanned_files', 'status', 'evaluation_error',
            'extracted_responses', 'candidate_info', 'evaluation_results',
            'annotated_pdf', 'annotated_pdf_url', 'results_json',
            'score', 'max_score', 'percentage',
            'submitted_at', 'evaluated_at'
        ]
        read_only_fields = [
            'id', 'status', 'evaluation_error', 'extracted_responses',
            'candidate_info', 'evaluation_results', 'annotated_pdf',
            'annotated_pdf_url', 'results_json', 'score', 'max_score',
            'percentage', 'submitted_at', 'evaluated_at'
        ]
    
    def get_annotated_pdf_url(self, obj):
        if obj.annotated_pdf:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.annotated_pdf.url)
            return obj.annotated_pdf.url
        return None


class OMRSubmissionUploadSerializer(serializers.Serializer):
    """Serializer for uploading scanned OMR files"""
    files = serializers.ListField(
        child=serializers.FileField(),
        required=True,
        help_text="Scanned OMR sheet files (images or PDF)"
    )
    student_id = serializers.IntegerField(
        required=False,
        help_text="Student user ID (optional, defaults to current user)"
    )
    
    def validate_files(self, value):
        """Validate uploaded files"""
        allowed_extensions = ['pdf', 'png', 'jpg', 'jpeg', 'tiff', 'tif']
        for file in value:
            ext = file.name.split('.')[-1].lower()
            if ext not in allowed_extensions:
                raise serializers.ValidationError(
                    f"File '{file.name}' has unsupported extension. "
                    f"Allowed: {', '.join(allowed_extensions)}"
                )
        return value


class AnswerKeySerializer(serializers.ModelSerializer):
    """Serializer for Answer Key"""
    exam_title = serializers.CharField(source='exam.title', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    
    class Meta:
        model = AnswerKey
        fields = [
            'id', 'exam', 'exam_title', 'answers',
            'created_at', 'updated_at', 'created_by', 'created_by_name'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by', 'created_by_name']
    
    def validate_answers(self, value):
        """Validate answer key structure"""
        if not isinstance(value, dict):
            raise serializers.ValidationError("Answers must be a dictionary")
        
        for q_field, q_data in value.items():
            if not isinstance(q_data, dict):
                raise serializers.ValidationError(
                    f"Answer for '{q_field}' must be a dictionary"
                )
            if 'correct' not in q_data:
                raise serializers.ValidationError(
                    f"Answer for '{q_field}' must have 'correct' key"
                )
            if not isinstance(q_data['correct'], list):
                raise serializers.ValidationError(
                    f"'correct' for '{q_field}' must be a list"
                )
            if 'marks' not in q_data:
                q_data['marks'] = 1  # Default marks
            if 'negative' not in q_data:
                q_data['negative'] = 0  # Default no negative marking
        
        return value


class OMREvaluationResultSerializer(serializers.Serializer):
    """Serializer for OMR evaluation results summary"""
    total_questions = serializers.IntegerField()
    attempted = serializers.IntegerField()
    correct = serializers.IntegerField()
    incorrect = serializers.IntegerField()
    score = serializers.FloatField()
    max_score = serializers.FloatField()
    percentage = serializers.FloatField()
    pass_status = serializers.BooleanField(source='pass')
    details = serializers.ListField(child=serializers.DictField())
