from django.db import migrations, models, connection
import django.db.models.deletion
import django.core.validators


def ensure_question_columns(apps, schema_editor):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'questions_question' AND column_name = 'exam_id'
                ) THEN
                    ALTER TABLE questions_question ADD COLUMN exam_id INTEGER;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'questions_question' AND column_name = 'question_number'
                ) THEN
                    ALTER TABLE questions_question ADD COLUMN question_number INTEGER;
                END IF;
            END;
            $$;
            """
        )


class Migration(migrations.Migration):

    dependencies = [
        ('questions', '0010_refactor_questions_to_exams'),
        ('exams', '0011_exam_public_access_token_and_more'),
    ]

    operations = [
        migrations.RunPython(ensure_question_columns, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='question',
            name='exam',
            field=models.ForeignKey(
                blank=True,
                help_text='Exam this question belongs to',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='questions',
                to='exams.exam'
            ),
        ),
        migrations.AlterField(
            model_name='question',
            name='question_number',
            field=models.IntegerField(
                blank=True,
                help_text='Question number in the exam',
                null=True,
                validators=[django.core.validators.MinValueValidator(1)]
            ),
        ),
        migrations.AlterModelOptions(
            name='question',
            options={'ordering': ['question_number', 'created_at']},
        ),
    ]
