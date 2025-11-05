# Generated manually to migrate existing question types

from django.db import migrations


def migrate_question_types(apps, schema_editor):
    """Migrate existing 'mcq' to 'single_mcq' for backward compatibility"""
    Question = apps.get_model('questions', 'Question')
    QuestionTemplate = apps.get_model('questions', 'QuestionTemplate')
    
    # Update all existing 'mcq' to 'single_mcq'
    Question.objects.filter(question_type='mcq').update(question_type='single_mcq')
    QuestionTemplate.objects.filter(question_type='mcq').update(question_type='single_mcq')
    
    print("✅ Migrated Question and QuestionTemplate question types: mcq → single_mcq")


def reverse_migrate_question_types(apps, schema_editor):
    """Reverse migration: 'single_mcq' back to 'mcq'"""
    Question = apps.get_model('questions', 'Question')
    QuestionTemplate = apps.get_model('questions', 'QuestionTemplate')
    
    # Update all 'single_mcq' back to 'mcq'
    Question.objects.filter(question_type='single_mcq').update(question_type='mcq')
    QuestionTemplate.objects.filter(question_type='single_mcq').update(question_type='mcq')
    
    print("✅ Reversed Question and QuestionTemplate question types: single_mcq → mcq")


class Migration(migrations.Migration):

    dependencies = [
        ('questions', '0004_update_question_types'),
    ]

    operations = [
        migrations.RunPython(migrate_question_types, reverse_migrate_question_types),
    ]
