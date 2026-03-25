"""
Email invitation system for exams
"""
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.db import transaction
from django.utils import timezone
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.db.models import Q
from django.contrib.auth import get_user_model
import uuid
from datetime import timedelta

from .models import Exam, ExamInvitation, ExamReschedule
from .serializers import (
    ExamInvitationSerializer, ExamInvitationCreateSerializer,
    ExamInvitationBulkSerializer, EmailTemplateSerializer
)

User = get_user_model()


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def send_exam_invitations(request, exam_id):
    """Send email invitations to specific students for an exam"""
    try:
        exam = Exam.objects.get(id=exam_id)
        user = request.user
        
        if not user.can_manage_exams():
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        serializer = ExamInvitationBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        student_emails = serializer.validated_data['student_emails']
        custom_message = serializer.validated_data.get('custom_message', '')
        send_reminder = serializer.validated_data.get('send_reminder', False)
        
        created_invitations = []
        failed_invitations = []
        
        with transaction.atomic():
            for email in student_emails:
                try:
                    # Check if student exists
                    student = User.objects.filter(email=email, role__in=['student', 'STUDENT']).first()
                    if not student:
                        failed_invitations.append({
                            'email': email,
                            'error': 'Student not found'
                        })
                        continue
                    
                    # Check if invitation already exists
                    existing_invitation = ExamInvitation.objects.filter(
                        exam=exam, student=student
                    ).first()
                    
                    if existing_invitation:
                        if existing_invitation.status == 'pending':
                            failed_invitations.append({
                                'email': email,
                                'error': 'Invitation already sent'
                            })
                            continue
                        else:
                            # Update existing invitation
                            existing_invitation.status = 'pending'
                            existing_invitation.invited_by = user
                            existing_invitation.invited_at = timezone.now()
                            existing_invitation.custom_message = custom_message
                            existing_invitation.save()
                            invitation = existing_invitation
                    else:
                        # Create new invitation
                        invitation = ExamInvitation.objects.create(
                            exam=exam,
                            student=student,
                            invited_by=user,
                            custom_message=custom_message,
                            status='pending'
                        )
                    
                    # Send email invitation
                    success = send_invitation_email(invitation, custom_message)
                    if success:
                        created_invitations.append(ExamInvitationSerializer(invitation).data)
                    else:
                        failed_invitations.append({
                            'email': email,
                            'error': 'Failed to send email'
                        })
                        
                except Exception as e:
                    failed_invitations.append({
                        'email': email,
                        'error': str(e)
                    })
        
        return Response({
            'success': True,
            'created_count': len(created_invitations),
            'failed_count': len(failed_invitations),
            'created_invitations': created_invitations,
            'failed_invitations': failed_invitations
        })
        
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to send invitations: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def resend_invitation(request, invitation_id):
    """Resend an exam invitation email"""
    try:
        invitation = ExamInvitation.objects.get(id=invitation_id)
        user = request.user
        
        if not user.can_manage_exams() and invitation.invited_by != user:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        if invitation.status != 'pending':
            return Response({'error': 'Can only resend pending invitations'}, status=status.HTTP_400_BAD_REQUEST)
        
        success = send_invitation_email(invitation, invitation.custom_message)
        
        if success:
            invitation.invited_at = timezone.now()
            invitation.save()
            return Response({
                'success': True,
                'message': 'Invitation resent successfully'
            })
        else:
            return Response({
                'error': 'Failed to send email'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    except ExamInvitation.DoesNotExist:
        return Response({'error': 'Invitation not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to resend invitation: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def accept_invitation(request, invitation_id):
    """Student accepts an exam invitation"""
    try:
        invitation = ExamInvitation.objects.get(id=invitation_id)
        user = request.user
        
        if invitation.student != user:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        if invitation.status != 'pending':
            return Response({'error': 'Invitation is not pending'}, status=status.HTTP_400_BAD_REQUEST)
        
        invitation.status = 'accepted'
        invitation.accepted_at = timezone.now()
        invitation.save()
        
        # Send confirmation email to teacher
        send_acceptance_notification(invitation)
        
        return Response({
            'success': True,
            'message': 'Invitation accepted successfully',
            'invitation': ExamInvitationSerializer(invitation).data
        })
        
    except ExamInvitation.DoesNotExist:
        return Response({'error': 'Invitation not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to accept invitation: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def decline_invitation(request, invitation_id):
    """Student declines an exam invitation"""
    try:
        invitation = ExamInvitation.objects.get(id=invitation_id)
        user = request.user
        
        if invitation.student != user:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        if invitation.status != 'pending':
            return Response({'error': 'Invitation is not pending'}, status=status.HTTP_400_BAD_REQUEST)
        
        decline_reason = request.data.get('reason', '')
        
        invitation.status = 'declined'
        invitation.declined_at = timezone.now()
        invitation.decline_reason = decline_reason
        invitation.save()
        
        # Send notification to teacher
        send_decline_notification(invitation, decline_reason)
        
        return Response({
            'success': True,
            'message': 'Invitation declined successfully',
            'invitation': ExamInvitationSerializer(invitation).data
        })
        
    except ExamInvitation.DoesNotExist:
        return Response({'error': 'Invitation not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to decline invitation: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_student_invitations(request):
    """Get all invitations for the current student"""
    user = request.user
    if user.role not in ['student', 'STUDENT']:
        return Response({'error': 'Only students can view their invitations'}, status=status.HTTP_403_FORBIDDEN)
    
    invitations = ExamInvitation.objects.filter(student=user).select_related('exam', 'invited_by')
    serializer = ExamInvitationSerializer(invitations, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_exam_invitations(request, exam_id):
    """Get all invitations for a specific exam (for teachers/admins)"""
    try:
        exam = Exam.objects.get(id=exam_id)
        user = request.user
        
        if not user.can_manage_exams():
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        invitations = ExamInvitation.objects.filter(exam=exam).select_related('student', 'invited_by')
        serializer = ExamInvitationSerializer(invitations, many=True)
        return Response(serializer.data)
        
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to get invitations: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def send_reminder_emails(request, exam_id):
    """Send reminder emails to students who haven't responded to invitations"""
    try:
        exam = Exam.objects.get(id=exam_id)
        user = request.user
        
        if not user.can_manage_exams():
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        pending_invitations = ExamInvitation.objects.filter(
            exam=exam, status='pending'
        ).select_related('student')
        
        sent_count = 0
        failed_count = 0
        
        for invitation in pending_invitations:
            try:
                success = send_reminder_email(invitation)
                if success:
                    sent_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1
        
        return Response({
            'success': True,
            'sent_count': sent_count,
            'failed_count': failed_count,
            'message': f'Reminder emails sent to {sent_count} students'
        })
        
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to send reminders: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def send_invitation_email(invitation, custom_message=''):
    """Send exam invitation email to student"""
    try:
        exam = invitation.exam
        student = invitation.student
        
        # Generate unique invitation link
        invitation_token = str(uuid.uuid4())
        invitation.invitation_token = invitation_token
        invitation.save()
        
        invitation_url = f"{settings.FRONTEND_URL}/invitations/{invitation_token}"
        
        # Prepare email context
        context = {
            'student_name': student.get_full_name() or student.email,
            'exam_title': exam.title,
            'exam_description': exam.description,
            'start_date': exam.start_date,
            'end_date': exam.end_date,
            'duration_minutes': exam.duration_minutes,
            'invitation_url': invitation_url,
            'custom_message': custom_message,
            'teacher_name': invitation.invited_by.get_full_name() or invitation.invited_by.email,
        }
        
        # Render email templates
        subject = f"Exam Invitation: {exam.title}"
        text_content = render_to_string('emails/exam_invitation.txt', context)
        html_content = render_to_string('emails/exam_invitation.html', context)
        
        # Send email
        msg = EmailMultiAlternatives(subject, text_content, settings.DEFAULT_FROM_EMAIL, [student.email])
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        
        return True
        
    except Exception as e:
        print(f"Failed to send invitation email: {e}")
        return False


def send_reminder_email(invitation):
    """Send reminder email for pending invitation"""
    try:
        exam = invitation.exam
        student = invitation.student
        
        context = {
            'student_name': student.get_full_name() or student.email,
            'exam_title': exam.title,
            'start_date': exam.start_date,
            'end_date': exam.end_date,
            'invitation_url': f"{settings.FRONTEND_URL}/invitations/{invitation.invitation_token}",
        }
        
        subject = f"Reminder: Exam Invitation - {exam.title}"
        text_content = render_to_string('emails/exam_reminder.txt', context)
        html_content = render_to_string('emails/exam_reminder.html', context)
        
        msg = EmailMultiAlternatives(subject, text_content, settings.DEFAULT_FROM_EMAIL, [student.email])
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        
        return True
        
    except Exception as e:
        print(f"Failed to send reminder email: {e}")
        return False


def send_acceptance_notification(invitation):
    """Send notification to teacher when student accepts invitation"""
    try:
        exam = invitation.exam
        student = invitation.student
        teacher = invitation.invited_by
        
        context = {
            'teacher_name': teacher.get_full_name() or teacher.email,
            'student_name': student.get_full_name() or student.email,
            'exam_title': exam.title,
            'accepted_at': invitation.accepted_at,
        }
        
        subject = f"Student Accepted Exam Invitation: {exam.title}"
        text_content = render_to_string('emails/invitation_accepted.txt', context)
        html_content = render_to_string('emails/invitation_accepted.html', context)
        
        msg = EmailMultiAlternatives(subject, text_content, settings.DEFAULT_FROM_EMAIL, [teacher.email])
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        
        return True
        
    except Exception as e:
        print(f"Failed to send acceptance notification: {e}")
        return False


def send_decline_notification(invitation, reason=''):
    """Send notification to teacher when student declines invitation"""
    try:
        exam = invitation.exam
        student = invitation.student
        teacher = invitation.invited_by
        
        context = {
            'teacher_name': teacher.get_full_name() or teacher.email,
            'student_name': student.get_full_name() or student.email,
            'exam_title': exam.title,
            'decline_reason': reason,
            'declined_at': invitation.declined_at,
        }
        
        subject = f"Student Declined Exam Invitation: {exam.title}"
        text_content = render_to_string('emails/invitation_declined.txt', context)
        html_content = render_to_string('emails/invitation_declined.html', context)
        
        msg = EmailMultiAlternatives(subject, text_content, settings.DEFAULT_FROM_EMAIL, [teacher.email])
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        
        return True
        
    except Exception as e:
        print(f"Failed to send decline notification: {e}")
        return False
