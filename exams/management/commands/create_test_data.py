from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
import random

from accounts.models import Institute
from patterns.models import Subject, ExamPattern, PatternSection
from questions.models import Question
from exams.models import Exam, ExamInvitation

User = get_user_model()


class Command(BaseCommand):
    help = 'Create test data for student exam functionality'

    def handle(self, *args, **options):
        self.stdout.write('Creating test data...')
        
        # Create Institute
        institute = self.create_institute()
        
        # Create Users
        admin_user = self.create_admin_user(institute)
        teacher_user = self.create_teacher_user(institute)
        student_user = self.create_student_user(institute)
        
        # Create Subjects
        subjects = self.create_subjects(institute)
        
        # Create Exam Patterns
        patterns = self.create_exam_patterns(subjects, institute, teacher_user)
        
        # Create Questions
        questions = self.create_questions(patterns)
        
        # Create Exams
        exams = self.create_exams(patterns, teacher_user, institute, student_user)
        
        # Create Exam Invitations
        self.create_exam_invitations(exams, student_user, teacher_user)
        
        self.stdout.write(
            self.style.SUCCESS('Successfully created test data!')
        )
        self.stdout.write('\nTest Users Created:')
        self.stdout.write(f'Admin: {admin_user.email} / password: admin123')
        self.stdout.write(f'Teacher: {teacher_user.email} / password: teacher123')
        self.stdout.write(f'Student: {student_user.email} / password: student123')
        self.stdout.write(f'\nInstitute: {institute.name}')
        self.stdout.write(f'Exams Created: {len(exams)}')
        self.stdout.write(f'Questions Created: {len(questions)}')

    def create_institute(self):
        institute, created = Institute.objects.get_or_create(
            name='Test University',
            defaults={
                'description': 'A test university for exam system',
                'address': '123 Test Street, Test City',
                'contact_phone': '+1-234-567-8900',
                'contact_email': 'admin@testuniversity.edu',
                'website': 'https://testuniversity.edu',
                'domain': 'testuniversity.edu'
            }
        )
        if created:
            self.stdout.write(f'Created institute: {institute.name}')
        return institute

    def create_admin_user(self, institute):
        user, created = User.objects.get_or_create(
            email='admin@testuniversity.edu',
            defaults={
                'username': 'admin',
                'first_name': 'Admin',
                'last_name': 'User',
                'role': 'super_admin',
                'institute': institute,
                'is_staff': True,
                'is_superuser': True
            }
        )
        if created:
            user.set_password('admin123')
            user.save()
            self.stdout.write(f'Created admin user: {user.email}')
        return user

    def create_teacher_user(self, institute):
        user, created = User.objects.get_or_create(
            email='teacher@testuniversity.edu',
            defaults={
                'username': 'teacher',
                'first_name': 'John',
                'last_name': 'Teacher',
                'role': 'teacher',
                'institute': institute
            }
        )
        if created:
            user.set_password('teacher123')
            user.save()
            self.stdout.write(f'Created teacher user: {user.email}')
        return user

    def create_student_user(self, institute):
        user, created = User.objects.get_or_create(
            email='student@testuniversity.edu',
            defaults={
                'username': 'student',
                'first_name': 'Jane',
                'last_name': 'Student',
                'role': 'student',
                'institute': institute
            }
        )
        if created:
            user.set_password('student123')
            user.save()
            self.stdout.write(f'Created student user: {user.email}')
        return user

    def create_subjects(self, institute):
        subjects_data = [
            {'name': 'Mathematics', 'description': 'Basic Mathematics'},
            {'name': 'Physics', 'description': 'Basic Physics'},
            {'name': 'Chemistry', 'description': 'Basic Chemistry'},
            {'name': 'Computer Science', 'description': 'Introduction to Computer Science'},
        ]
        
        subjects = []
        for subject_data in subjects_data:
            subject, created = Subject.objects.get_or_create(
                name=subject_data['name'],
                institute=institute,
                defaults=subject_data
            )
            if created:
                self.stdout.write(f'Created subject: {subject.name}')
            subjects.append(subject)
        
        return subjects

    def create_exam_patterns(self, subjects, institute, teacher_user):
        patterns_data = [
            {
                'name': 'Mathematics Midterm',
                'description': 'Midterm exam for Mathematics course',
                'total_marks': 100,
                'total_duration': 120,
                'total_questions': 20,
                'sections': [
                    {
                        'name': 'Algebra',
                        'subject': subjects[0],  # Mathematics
                        'question_type': 'single_mcq',
                        'start_question': 1,
                        'end_question': 10,
                        'marks_per_question': 2,
                        'total_marks': 20
                    },
                    {
                        'name': 'Calculus',
                        'subject': subjects[0],  # Mathematics
                        'question_type': 'numerical',
                        'start_question': 11,
                        'end_question': 15,
                        'marks_per_question': 4,
                        'total_marks': 20
                    },
                    {
                        'name': 'Geometry',
                        'subject': subjects[0],  # Mathematics
                        'question_type': 'subjective',
                        'start_question': 16,
                        'end_question': 20,
                        'marks_per_question': 6,
                        'total_marks': 30
                    }
                ]
            },
            {
                'name': 'Physics Final',
                'description': 'Final exam for Physics course',
                'total_marks': 100,
                'total_duration': 180,
                'total_questions': 25,
                'sections': [
                    {
                        'name': 'Mechanics',
                        'subject': subjects[1],  # Physics
                        'question_type': 'single_mcq',
                        'start_question': 1,
                        'end_question': 15,
                        'marks_per_question': 2,
                        'total_marks': 30
                    },
                    {
                        'name': 'Thermodynamics',
                        'subject': subjects[1],  # Physics
                        'question_type': 'numerical',
                        'start_question': 16,
                        'end_question': 20,
                        'marks_per_question': 5,
                        'total_marks': 25
                    },
                    {
                        'name': 'Electromagnetism',
                        'subject': subjects[1],  # Physics
                        'question_type': 'subjective',
                        'start_question': 21,
                        'end_question': 25,
                        'marks_per_question': 9,
                        'total_marks': 45
                    }
                ]
            }
        ]
        
        patterns = []
        for pattern_data in patterns_data:
            pattern, created = ExamPattern.objects.get_or_create(
                name=pattern_data['name'],
                institute=institute,
                defaults={
                    'description': pattern_data['description'],
                    'total_marks': pattern_data['total_marks'],
                    'total_duration': pattern_data['total_duration'],
                    'total_questions': pattern_data['total_questions'],
                    'created_by': teacher_user
                }
            )
            
            if created:
                self.stdout.write(f'Created pattern: {pattern.name}')
                
                # Create sections
                for i, section_data in enumerate(pattern_data['sections']):
                    PatternSection.objects.create(
                        pattern=pattern,
                        name=section_data['name'],
                        subject=section_data['subject'].name,  # Convert to string
                        question_type=section_data['question_type'],
                        start_question=section_data['start_question'],
                        end_question=section_data['end_question'],
                        marks_per_question=section_data['marks_per_question'],
                        order=i + 1
                    )
                    self.stdout.write(f'  Created section: {section_data["name"]}')
            
            patterns.append(pattern)
        
        return patterns

    def create_questions(self, patterns):
        questions = []
        
        # Mathematics questions
        math_pattern = patterns[0]
        math_sections = math_pattern.sections.all()
        
        # Algebra MCQ questions
        algebra_section = math_sections.filter(name='Algebra').first()
        if algebra_section:
            algebra_questions = [
                {
                    'question_text': 'What is the value of $x$ in the equation $2x + 5 = 13$?',
                    'question_type': 'mcq',
                    'options': [
                        {'text': '$x = 4$', 'is_correct': True},
                        {'text': '$x = 3$', 'is_correct': False},
                        {'text': '$x = 5$', 'is_correct': False},
                        {'text': '$x = 6$', 'is_correct': False}
                    ],
                    'correct_answer': '$x = 4$',
                    'explanation': 'Solving: $2x + 5 = 13$ → $2x = 8$ → $x = 4$',
                    'marks': 2
                },
                {
                    'question_text': 'Simplify the expression: $(x + 3)(x - 2)$',
                    'question_type': 'mcq',
                    'options': [
                        {'text': '$x^2 + x - 6$', 'is_correct': True},
                        {'text': '$x^2 - x - 6$', 'is_correct': False},
                        {'text': '$x^2 + 5x - 6$', 'is_correct': False},
                        {'text': '$x^2 - 5x - 6$', 'is_correct': False}
                    ],
                    'correct_answer': '$x^2 + x - 6$',
                    'explanation': 'Using FOIL: $(x + 3)(x - 2) = x^2 - 2x + 3x - 6 = x^2 + x - 6$',
                    'marks': 2
                }
            ]
            
            for i, q_data in enumerate(algebra_questions):
                question = Question.objects.create(
                    pattern_section=algebra_section,
                    question_number_in_pattern=algebra_section.start_question + i,
                    question_text=q_data['question_text'],
                    question_type=q_data['question_type'],
                    correct_answer=q_data['correct_answer'],
                    explanation=q_data['explanation'],
                    marks=q_data['marks'],
                    subject=algebra_section.subject,
                    institute=algebra_section.pattern.institute,
                    created_by=algebra_section.pattern.created_by,
                    options=q_data['options']  # Store options as JSON
                )
                
                questions.append(question)
                self.stdout.write(f'  Created algebra question {i+1}')

        # Calculus Numerical questions
        calculus_section = math_sections.filter(name='Calculus').first()
        if calculus_section:
            calculus_questions = [
                {
                    'question_text': 'Find the derivative of $f(x) = x^3 + 2x^2 - 5x + 1$',
                    'question_type': 'numerical',
                    'correct_answer': '$3x^2 + 4x - 5$',
                    'explanation': 'Using power rule: $\\frac{d}{dx}(x^3 + 2x^2 - 5x + 1) = 3x^2 + 4x - 5$',
                    'marks': 4
                },
                {
                    'question_text': 'Evaluate $\\int_0^2 (2x + 1) \\, dx$',
                    'question_type': 'numerical',
                    'correct_answer': '6',
                    'explanation': '$\\int_0^2 (2x + 1) \\, dx = [x^2 + x]_0^2 = (4 + 2) - (0 + 0) = 6$',
                    'marks': 4
                }
            ]
            
            for i, q_data in enumerate(calculus_questions):
                question = Question.objects.create(
                    pattern_section=calculus_section,
                    question_number_in_pattern=calculus_section.start_question + i,
                    question_text=q_data['question_text'],
                    question_type=q_data['question_type'],
                    correct_answer=q_data['correct_answer'],
                    explanation=q_data['explanation'],
                    marks=q_data['marks'],
                    subject=calculus_section.subject,
                    institute=calculus_section.pattern.institute,
                    created_by=calculus_section.pattern.created_by
                )
                questions.append(question)
                self.stdout.write(f'  Created calculus question {i+1}')

        # Physics questions
        physics_pattern = patterns[1]
        physics_sections = physics_pattern.sections.all()
        
        # Mechanics MCQ questions
        mechanics_section = physics_sections.filter(name='Mechanics').first()
        if mechanics_section:
            mechanics_questions = [
                {
                    'question_text': 'A ball is thrown vertically upward with an initial velocity of $20 \\text{ m/s}$. What is its maximum height? (Use $g = 10 \\text{ m/s}^2$)',
                    'question_type': 'mcq',
                    'options': [
                        {'text': '$20 \\text{ m}$', 'is_correct': True},
                        {'text': '$40 \\text{ m}$', 'is_correct': False},
                        {'text': '$10 \\text{ m}$', 'is_correct': False},
                        {'text': '$30 \\text{ m}$', 'is_correct': False}
                    ],
                    'correct_answer': '$20 \\text{ m}$',
                    'explanation': 'Using $v^2 = u^2 - 2gh$: $0 = 400 - 20h$ → $h = 20 \\text{ m}$',
                    'marks': 2
                },
                {
                    'question_text': 'What is the unit of force in the SI system?',
                    'question_type': 'mcq',
                    'options': [
                        {'text': 'Newton (N)', 'is_correct': True},
                        {'text': 'Joule (J)', 'is_correct': False},
                        {'text': 'Watt (W)', 'is_correct': False},
                        {'text': 'Pascal (Pa)', 'is_correct': False}
                    ],
                    'correct_answer': 'Newton (N)',
                    'explanation': 'Force is measured in Newtons (N) in the SI system.',
                    'marks': 2
                }
            ]
            
            for i, q_data in enumerate(mechanics_questions):
                question = Question.objects.create(
                    pattern_section=mechanics_section,
                    question_number_in_pattern=mechanics_section.start_question + i,
                    question_text=q_data['question_text'],
                    question_type=q_data['question_type'],
                    correct_answer=q_data['correct_answer'],
                    explanation=q_data['explanation'],
                    marks=q_data['marks'],
                    subject=mechanics_section.subject,
                    institute=mechanics_section.pattern.institute,
                    created_by=mechanics_section.pattern.created_by,
                    options=q_data['options']  # Store options as JSON
                )
                
                questions.append(question)
                self.stdout.write(f'  Created mechanics question {i+1}')

        return questions

    def create_exams(self, patterns, teacher_user, institute, student_user):
        now = timezone.now()
        
        exams_data = [
            {
                'title': 'Mathematics Midterm Exam',
                'description': 'Midterm examination for Mathematics 101 course',
                'pattern': patterns[0],
                'start_date': now - timedelta(hours=1),
                'end_date': now + timedelta(days=7),
                'duration_minutes': 120,
                'max_attempts': 2,
                'enable_webcam_proctoring': True,
                'require_fullscreen': True,
                'disable_copy_paste': True,
                'disable_right_click': True,
                'allow_tab_switching': False,
                'is_public': False
            },
            {
                'title': 'Physics Final Exam',
                'description': 'Final examination for Physics 101 course',
                'pattern': patterns[1],
                'start_date': now - timedelta(hours=2),
                'end_date': now + timedelta(days=10),
                'duration_minutes': 180,
                'max_attempts': 1,
                'enable_webcam_proctoring': True,
                'require_fullscreen': True,
                'disable_copy_paste': True,
                'disable_right_click': True,
                'allow_tab_switching': False,
                'is_public': True
            }
        ]
        
        exams = []
        for exam_data in exams_data:
            exam = Exam.objects.create(
                title=exam_data['title'],
                description=exam_data['description'],
                institute=institute,
                pattern=exam_data['pattern'],
                start_date=exam_data['start_date'],
                end_date=exam_data['end_date'],
                duration_minutes=exam_data['duration_minutes'],
                max_attempts=exam_data['max_attempts'],
                enable_webcam_proctoring=exam_data['enable_webcam_proctoring'],
                require_fullscreen=exam_data['require_fullscreen'],
                disable_copy_paste=exam_data['disable_copy_paste'],
                disable_right_click=exam_data['disable_right_click'],
                allow_tab_switching=exam_data['allow_tab_switching'],
                is_public=exam_data['is_public'],
                created_by=teacher_user,
                status='active'
            )
            
            # Add student to allowed users for the exam
            exam.allowed_users.add(student_user)
            
            exams.append(exam)
            self.stdout.write(f'Created exam: {exam.title}')
        
        return exams

    def create_exam_invitations(self, exams, student_user, teacher_user):
        for exam in exams:
            invitation, created = ExamInvitation.objects.get_or_create(
                exam=exam,
                user=student_user,
                defaults={
                    'invited_by': teacher_user,
                    'access_code': f'EXAM{exam.id:03d}',
                    'valid_from': exam.start_date,
                    'valid_until': exam.end_date,
                    'max_attempts': exam.max_attempts,
                    'is_active': True
                }
            )
            if created:
                self.stdout.write(f'Created invitation for {student_user.email} to {exam.title}')
                self.stdout.write(f'  Access code: {invitation.access_code}')
