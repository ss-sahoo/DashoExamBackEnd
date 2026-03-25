# Generated migration for refactoring questions to belong to exams

from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('questions', '0008_alter_questiontemplate_options_and_more'),
        ('exams', '0009_examattempt_answers'),
    ]

    operations = [
        # Add exam foreign key
        migrations.AddField(
            model_name='question',
            name='exam',
            field=models.ForeignKey(
                help_text='Exam this question belongs to',
                on_delete=django.db.models.deletion.CASCADE,
                related_name='questions',
                to='exams.exam',
                null=True  # Temporarily allow null for migration
            ),
        ),

        # Remove old pattern_section foreign key first (drops pattern_section_id column)
        migrations.RemoveField(
            model_name='question',
            name='pattern_section',
        ),

        # Remove old question_number_in_pattern field (will be re-added later in 0012)
        migrations.RemoveField(
            model_name='question',
            name='question_number_in_pattern',
        ),

        # Add pattern section reference fields (not foreign keys)
        migrations.AddField(
            model_name='question',
            name='pattern_section_id',
            field=models.IntegerField(
                blank=True,
                help_text='Reference to pattern section for organization',
                null=True
            ),
        ),
        migrations.AddField(
            model_name='question',
            name='pattern_section_name',
            field=models.CharField(
                blank=True,
                help_text='Name of the pattern section',
                max_length=200
            ),
        ),

        # Add question_number field
        migrations.AddField(
            model_name='question',
            name='question_number',
            field=models.IntegerField(
                help_text='Question number in the exam',
                validators=[django.core.validators.MinValueValidator(1)],
                null=True  # Temporarily allow null for migration
            ),
        ),

        # Update Meta
        migrations.AlterUniqueTogether(
            name='question',
            unique_together={('exam', 'question_number')},
        ),
        migrations.AlterModelOptions(
            name='question',
            options={'ordering': ['exam', 'question_number']},
        ),
    ]

