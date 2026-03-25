from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from questions.models import QuestionTemplate
from accounts.models import Institute

User = get_user_model()

class Command(BaseCommand):
    help = 'Populate question templates with default data'

    def handle(self, *args, **options):
        # Get or create a default institute
        institute, created = Institute.objects.get_or_create(
            name="Default Institute",
            defaults={
                'domain': 'example.com',
                'description': 'Default institute for templates'
            }
        )
        
        # Get or create a superuser for templates
        superuser, created = User.objects.get_or_create(
            email='admin@example.com',
            defaults={
                'first_name': 'Admin',
                'last_name': 'User',
                'role': 'super_admin',
                'institute': institute,
                'is_staff': True,
                'is_superuser': True
            }
        )

        templates_data = [
            # Mathematics Templates
            {
                'name': 'Basic Algebra Equation',
                'description': 'Template for simple linear equations in one variable',
                'category': 'mathematics',
                'question_type': 'numerical',
                'difficulty': 'easy',
                'subject': 'Mathematics',
                'topic': 'Algebra',
                'template_data': {
                    'question_format': 'Solve for x: {coefficient}x + {constant} = {result}',
                    'variables': ['coefficient', 'constant', 'result'],
                    'solution_format': 'x = {answer}',
                    'explanation_template': 'Step 1: Subtract {constant} from both sides\\nStep 2: Divide by {coefficient}\\nAnswer: x = {answer}'
                },
                'example_question': 'Solve for x: 2x + 5 = 15',
                'tags': ['algebra', 'equation', 'linear', 'basic'],
                'is_featured': True
            },
            {
                'name': 'Quadratic Equation',
                'description': 'Template for quadratic equations',
                'category': 'mathematics',
                'question_type': 'numerical',
                'difficulty': 'medium',
                'subject': 'Mathematics',
                'topic': 'Algebra',
                'template_data': {
                    'question_format': 'Solve the quadratic equation: {a}x² + {b}x + {c} = 0',
                    'variables': ['a', 'b', 'c'],
                    'solution_format': 'x = {x1} or x = {x2}',
                    'explanation_template': 'Using the quadratic formula: x = (-b ± √(b²-4ac)) / 2a'
                },
                'example_question': 'Solve: x² - 5x + 6 = 0',
                'tags': ['quadratic', 'equation', 'algebra', 'intermediate'],
                'is_featured': True
            },
            
            # Science Templates
            {
                'name': 'Physics Problem - Motion',
                'description': 'Template for basic motion problems',
                'category': 'science',
                'question_type': 'numerical',
                'difficulty': 'medium',
                'subject': 'Physics',
                'topic': 'Mechanics',
                'template_data': {
                    'question_format': 'A {object} travels {distance} meters in {time} seconds. What is its {quantity}?',
                    'variables': ['object', 'distance', 'time', 'quantity'],
                    'solution_format': '{quantity} = {answer} {unit}',
                    'explanation_template': 'Using the formula: {formula}\\nSubstitute the given values and solve.'
                },
                'example_question': 'A car travels 100 meters in 10 seconds. What is its speed?',
                'tags': ['physics', 'motion', 'speed', 'mechanics'],
                'is_featured': True
            },
            
            # Language Learning Templates
            {
                'name': 'Vocabulary MCQ',
                'description': 'Template for vocabulary multiple choice questions',
                'category': 'language',
                'question_type': 'single_mcq',
                'difficulty': 'easy',
                'subject': 'English',
                'topic': 'Vocabulary',
                'template_data': {
                    'question_format': 'What is the meaning of "{word}"?',
                    'variables': ['word'],
                    'options_format': ['{correct_answer}', '{wrong1}', '{wrong2}', '{wrong3}'],
                    'explanation_template': 'The word "{word}" means {correct_answer}.'
                },
                'example_question': 'What is the meaning of "serendipity"?',
                'tags': ['vocabulary', 'english', 'language', 'mcq'],
                'is_featured': True
            },
            
            # Technical Templates
            {
                'name': 'Programming Algorithm',
                'description': 'Template for programming algorithm questions',
                'category': 'technical',
                'question_type': 'subjective',
                'difficulty': 'hard',
                'subject': 'Computer Science',
                'topic': 'Algorithms',
                'template_data': {
                    'question_format': 'Write a {language} function to {task}. The function should {requirements}.',
                    'variables': ['language', 'task', 'requirements'],
                    'solution_format': '```{language}\\n{code}\\n```',
                    'explanation_template': 'This algorithm uses {approach} with time complexity O({complexity}).'
                },
                'example_question': 'Write a Python function to find the maximum element in a list.',
                'tags': ['programming', 'algorithm', 'python', 'coding'],
                'is_featured': True
            },
            
            # General Knowledge Templates
            {
                'name': 'Capital Cities',
                'description': 'Template for capital city questions',
                'category': 'general',
                'question_type': 'single_mcq',
                'difficulty': 'easy',
                'subject': 'Geography',
                'topic': 'World Capitals',
                'template_data': {
                    'question_format': 'What is the capital of {country}?',
                    'variables': ['country'],
                    'options_format': ['{capital}', '{wrong1}', '{wrong2}', '{wrong3}'],
                    'explanation_template': 'The capital of {country} is {capital}.'
                },
                'example_question': 'What is the capital of France?',
                'tags': ['geography', 'capitals', 'world', 'general'],
                'is_featured': True
            },
            
            # Competitive Exam Templates
            {
                'name': 'Quantitative Aptitude',
                'description': 'Template for quantitative reasoning questions',
                'category': 'competitive',
                'question_type': 'numerical',
                'difficulty': 'medium',
                'subject': 'Quantitative Aptitude',
                'topic': 'Percentage',
                'template_data': {
                    'question_format': 'If {value1} is {percentage}% of {value2}, what is {value2}?',
                    'variables': ['value1', 'percentage', 'value2'],
                    'solution_format': '{value2} = {answer}',
                    'explanation_template': 'Using the formula: {value2} = ({value1} × 100) / {percentage}'
                },
                'example_question': 'If 25 is 20% of a number, what is the number?',
                'tags': ['quantitative', 'percentage', 'aptitude', 'competitive'],
                'is_featured': True
            },
            
            # True/False Templates
            {
                'name': 'Science Facts',
                'description': 'Template for science true/false questions',
                'category': 'science',
                'question_type': 'true_false',
                'difficulty': 'easy',
                'subject': 'Science',
                'topic': 'General Science',
                'template_data': {
                    'question_format': 'True or False: {statement}',
                    'variables': ['statement'],
                    'solution_format': '{answer}',
                    'explanation_template': 'This statement is {answer} because {reason}.'
                },
                'example_question': 'True or False: The Earth revolves around the Sun.',
                'tags': ['science', 'facts', 'true-false', 'general'],
                'is_featured': True
            }
        ]

        created_count = 0
        for template_data in templates_data:
            template, created = QuestionTemplate.objects.get_or_create(
                name=template_data['name'],
                defaults={
                    **template_data,
                    'created_by': superuser,
                    'institute': institute
                }
            )
            if created:
                created_count += 1
                self.stdout.write(f'Created template: {template.name}')
            else:
                self.stdout.write(f'Template already exists: {template.name}')

        self.stdout.write(
            self.style.SUCCESS(f'Successfully created {created_count} question templates')
        )
