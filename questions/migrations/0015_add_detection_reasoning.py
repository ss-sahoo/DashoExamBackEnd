# Generated migration for adding detection_reasoning field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('questions', '0014_add_extraction_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='extractedquestion',
            name='detection_reasoning',
            field=models.TextField(
                blank=True,
                null=True,
                default='',
                help_text='AI reasoning for subject detection'
            ),
        ),
        migrations.AddField(
            model_name='extractionjob',
            name='mismatch_analysis',
            field=models.JSONField(
                default=dict,
                blank=True,
                null=True,
                help_text='Analysis of overflow/shortage mismatches'
            ),
        ),
        migrations.AddField(
            model_name='extractionjob',
            name='subject_distribution',
            field=models.JSONField(
                default=dict,
                blank=True,
                null=True,
                help_text='Distribution of questions by subject'
            ),
        ),
    ]
