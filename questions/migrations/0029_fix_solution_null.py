# Generated migration to fix solution field null constraint

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('questions', '0028_alter_extractedquestion_solution'),
    ]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE questions_extractedquestion ALTER COLUMN solution DROP NOT NULL;',
            reverse_sql='ALTER TABLE questions_extractedquestion ALTER COLUMN solution SET NOT NULL;',
        ),
    ]
