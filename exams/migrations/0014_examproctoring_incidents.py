from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0013_examattempt_answer_sheet_generated_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='examproctoring',
            name='incidents',
            field=models.JSONField(default=list, help_text='Client-side proctoring incidents'),
        ),
    ]

