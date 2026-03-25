# Generated manually for adding detected_sections_per_subject field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('questions', '0023_alter_question_unique_together_question_structure'),
    ]

    operations = [
        migrations.AddField(
            model_name='preanalysisjob',
            name='detected_sections_per_subject',
            field=models.JSONField(blank=True, default=dict, help_text='Detected sections for each subject, cached to avoid re-detecting during extraction'),
        ),
    ]
