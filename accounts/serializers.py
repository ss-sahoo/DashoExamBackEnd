from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from datetime import timedelta
from .models import User, Institute, UserPermission, InstituteSettings, InstituteInvitation


class InstituteSerializer(serializers.ModelSerializer):
    user_count = serializers.SerializerMethodField()
    active_user_count = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Institute
        fields = [
            'id', 'name', 'domain', 'description', 'address', 'contact_email', 
            'contact_phone', 'website', 'logo', 'is_active', 'is_verified',
            'created_by', 'created_by_name', 'user_count', 'active_user_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'user_count', 'active_user_count', 'created_by_name']
    
    def get_user_count(self, obj):
        return obj.get_user_count()
    
    def get_active_user_count(self, obj):
        return obj.get_active_user_count()
    
    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else None


class InstituteCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new institutes"""
    class Meta:
        model = Institute
        fields = [
            'name', 'domain', 'description', 'address', 'contact_email',
            'contact_phone', 'website', 'logo'
        ]
    
    def validate_domain(self, value):
        """Validate that domain is unique if provided"""
        if value and Institute.objects.filter(domain=value).exists():
            raise serializers.ValidationError("An institute with this domain already exists.")
        return value.lower() if value else None
    
    def create(self, validated_data):
        """Create institute and set the creator as super_admin"""
        user = self.context['request'].user
        validated_data['created_by'] = user
        validated_data['is_verified'] = True  # Auto-verify user-created institutes
        institute = Institute.objects.create(**validated_data)
        
        # Update user's institute and role - make them super_admin
        user.institute = institute
        user.role = 'super_admin'
        user.is_staff = True  # Give staff access
        user.save()
        
        return institute


class InstituteInvitationSerializer(serializers.ModelSerializer):
    institute_name = serializers.CharField(source='institute.name', read_only=True)
    invited_by_name = serializers.CharField(source='invited_by.get_full_name', read_only=True)
    is_expired = serializers.SerializerMethodField()
    
    class Meta:
        model = InstituteInvitation
        fields = [
            'id', 'institute', 'institute_name', 'email', 'role', 'invited_by',
            'invited_by_name', 'status', 'message', 'expires_at', 'is_expired',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'invited_by', 'status', 'created_at', 'updated_at']
        extra_kwargs = {
            'expires_at': {'required': False, 'allow_null': True}
        }
    
    def get_is_expired(self, obj):
        return obj.is_expired()
    
    def create(self, validated_data):
        """Create invitation with default 7-day expiration"""
        validated_data['invited_by'] = self.context['request'].user
        if not validated_data.get('expires_at'):
            validated_data['expires_at'] = timezone.now() + timedelta(days=7)
        return super().create(validated_data)


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = [
            'email', 'username', 'first_name', 'last_name', 'password', 
            'password_confirm', 'phone'
        ]

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError("Passwords don't match")
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        # Users register without institute initially
        user = User.objects.create_user(**validated_data)
        return user


class UserSerializer(serializers.ModelSerializer):
    institute = InstituteSerializer(read_only=True)
    institute_id = serializers.IntegerField(read_only=True)  # Add institute_id for frontend
    full_name = serializers.CharField(source='get_full_name', read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'email', 'username', 'first_name', 'last_name', 'full_name',
            'role', 'institute', 'institute_id', 'phone', 'profile_picture', 'is_verified',
            'is_active', 'created_at'
        ]
        read_only_fields = ['id', 'email', 'created_at', 'institute_id']


class UserLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        if email and password:
            user = authenticate(username=email, password=password)
            if not user:
                raise serializers.ValidationError('Invalid credentials')
            if not user.is_active:
                raise serializers.ValidationError('User account is disabled')
            attrs['user'] = user
        else:
            raise serializers.ValidationError('Must include email and password')

        return attrs


class UserPermissionSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    granted_by = UserSerializer(read_only=True)

    class Meta:
        model = UserPermission
        fields = ['id', 'user', 'permission_type', 'granted_by', 'granted_at', 'expires_at', 'is_active']


class InstituteSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = InstituteSettings
        fields = '__all__'
        read_only_fields = ['institute']


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField(validators=[validate_password])
    new_password_confirm = serializers.CharField()

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError("New passwords don't match")
        return attrs

    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect")
        return value
