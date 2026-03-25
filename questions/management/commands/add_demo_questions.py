from django.core.management.base import BaseCommand
from accounts.models import Institute, User
from patterns.models import ExamPattern, PatternSection
from questions.models import Question


class Command(BaseCommand):
    help = 'Add demo physics questions for AI chatbot testing'

    def handle(self, *args, **options):
        # Get institute and user
        institute = Institute.objects.first()
        if not institute:
            self.stdout.write(self.style.ERROR('No institute found!'))
            return

        user = User.objects.filter(institute=institute).first()
        if not user:
            self.stdout.write(self.style.ERROR('No user found!'))
            return

        self.stdout.write(f"🏢 Institute: {institute.name}")
        self.stdout.write(f"👤 User: {user.email}\n")

        # Create pattern and section
        pattern, _ = ExamPattern.objects.get_or_create(
            name="JEE Physics Demo",
            institute=institute,
            defaults={
                'description': 'AI Chatbot Demo Pattern',
                'total_questions': 10,
                'total_duration': 180,
                'total_marks': 100,
                'created_by': user
            }
        )

        # Get or create section - use first existing or create new
        section = PatternSection.objects.filter(pattern=pattern).first()
        if not section:
            section = PatternSection.objects.create(
                pattern=pattern,
                name="Physics",
                subject="Physics",
                start_question=1,
                end_question=10,
                question_type='mcq',
                marks_per_question=4,
                negative_marking=1.0
            )

        # Demo questions (MCQ only for simplicity)
        questions = [
            {
                'text': "A block of mass 5 kg is placed on a smooth horizontal surface. A horizontal force of 20 N is applied on it. What is the acceleration of the block?",
                'topic': "Newton's Laws of Motion",
                'opts': ['2 m/s²', '4 m/s²', '5 m/s²', '10 m/s²'],
                'ans': '4 m/s²',
                'sol': "Using Newton's second law: F = ma\nGiven: F = 20 N, m = 5 kg\nTherefore, a = F/m = 20/5 = 4 m/s²",
                'subject': 'Physics'
            },
            {
                'text': "Two blocks of masses 2 kg and 3 kg are connected by a light string on a frictionless surface. A force of 10 N is applied to the 3 kg block. What is the tension in the string?",
                'topic': "Newton's Laws - Connected Bodies",
                'opts': ['2 N', '4 N', '6 N', '8 N'],
                'ans': '4 N',
                'sol': "Total mass = 5 kg. System acceleration a = 10/5 = 2 m/s². For 2kg block: T = m×a = 2×2 = 4 N",
                'subject': 'Physics'
            },
            {
                'text': "A ball of mass 2 kg is thrown vertically upward with an initial velocity of 20 m/s. What is the maximum height reached? (g = 10 m/s²)",
                'topic': 'Work, Energy and Power',
                'opts': ['10 m', '20 m', '30 m', '40 m'],
                'ans': '20 m',
                'sol': "At max height, v=0. Using v²=u²-2gh: 0=(20)²-2(10)h → h=20 m",
                'subject': 'Physics'
            },
            {
                'text': "A car moves in a circular path of radius 100 m with a constant speed of 20 m/s. What is the centripetal acceleration?",
                'topic': 'Circular Motion',
                'opts': ['2 m/s²', '4 m/s²', '8 m/s²', '10 m/s²'],
                'ans': '4 m/s²',
                'sol': "Centripetal acceleration a_c = v²/r = (20)²/100 = 400/100 = 4 m/s²",
                'subject': 'Physics'
            },
            {
                'text': "An ideal gas undergoes isothermal expansion at 300 K. If the volume doubles, what happens to the pressure?",
                'topic': 'Thermodynamics',
                'opts': ['Pressure doubles', 'Pressure halves', 'Pressure remains constant', 'Pressure becomes 1/4'],
                'ans': 'Pressure halves',
                'sol': "For isothermal process: PV = constant. If V₂ = 2V₁, then P₁V₁ = P₂(2V₁) → P₂ = P₁/2",
                'subject': 'Physics'
            },
            {
                'text': "What is the escape velocity from Earth's surface? (Take g = 10 m/s², R = 6400 km)",
                'topic': 'Gravitation',
                'opts': ['8 km/s', '11.2 km/s', '15 km/s', '20 km/s'],
                'ans': '11.2 km/s',
                'sol': "Escape velocity v_e = √(2gR) = √(2×10×6.4×10⁶) ≈ 11.2 km/s",
                'subject': 'Physics'
            },
            {
                'text': "Two point charges +3 μC and -3 μC are separated by 10 cm. What is the nature of this system?",
                'topic': 'Electrostatics',
                'opts': ['Electric monopole', 'Electric dipole', 'Electric quadrupole', 'Neutral system'],
                'ans': 'Electric dipole',
                'sol': "Two equal and opposite charges separated by a distance form an electric dipole. Dipole moment p = q×d",
                'subject': 'Physics'
            },
        ]

        created = 0
        for q in questions:
            _, is_new = Question.objects.get_or_create(
                question_text=q['text'],
                institute=institute,
                defaults={
                    'pattern_section': section,
                    'created_by': user,
                    'topic': q['topic'],
                    'subject': q['subject'],
                    'question_type': 'mcq',
                    'options': q['opts'],
                    'correct_answer': q['ans'],
                    'solution': q['sol']
                }
            )

            if is_new:
                created += 1
                self.stdout.write(self.style.SUCCESS(f" {q['topic']}"))

        total = Question.objects.filter(institute=institute).count()
        self.stdout.write(self.style.SUCCESS(f"\n📊 Created: {created} new questions"))
        self.stdout.write(self.style.SUCCESS(f"📚 Total: {total} questions in database"))
        self.stdout.write(self.style.SUCCESS("\n Demo questions ready for AI chatbot!"))
