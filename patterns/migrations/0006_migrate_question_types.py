# Generated manually to migrate existing question types

from django.db import migrations


def migrate_question_types(apps, schema_editor):
    """Migrate existing 'mcq' to 'single_mcq' for backward compatibility"""
    PatternSection = apps.get_model('patterns', 'PatternSection')
    
    # Update all existing 'mcq' to 'single_mcq'
    PatternSection.objects.filter(question_type='mcq').update(question_type='single_mcq')
    
    print("✅ Migrated PatternSection question types: mcq → single_mcq")


def reverse_migrate_question_types(apps, schema_editor):
    """Reverse migration: 'single_mcq' back to 'mcq'"""
    PatternSection = apps.get_model('patterns', 'PatternSection')
    
    # Update all 'single_mcq' back to 'mcq'
    PatternSection.objects.filter(question_type='single_mcq').update(question_type='mcq')
    
    print("✅ Reversed PatternSection question types: single_mcq → mcq")


class Migration(migrations.Migration):

    dependencies = [
        ('patterns', '0005_update_question_types'),
    ]

    operations = [
        migrations.RunPython(migrate_question_types, reverse_migrate_question_types),
    ]
