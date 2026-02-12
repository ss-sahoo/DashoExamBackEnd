# Generated manually to fix program_id NOT NULL constraint in production

from django.db import migrations


class Migration(migrations.Migration):
    """
    Fix the program_id column in accounts_batch table to be nullable.
    
    This migration explicitly drops the NOT NULL constraint that was 
    incorrectly applied to the program_id column. The Django model has
    null=True, blank=True but the database constraint wasn't properly
    updated in previous migrations (0007_make_batch_program_optional).
    
    This uses RunSQL with state_operations=None so it won't fail if 
    the constraint is already dropped (idempotent).
    """

    dependencies = [
        ('accounts', '0011_make_program_institute_required'),
    ]

    operations = [
        migrations.RunSQL(
            # Forward SQL: Drop the NOT NULL constraint (idempotent)
            sql='''
                DO $$
                BEGIN
                    -- Check if the column is currently NOT NULL and alter it
                    IF EXISTS (
                        SELECT 1 
                        FROM information_schema.columns 
                        WHERE table_name = 'accounts_batch' 
                        AND column_name = 'program_id' 
                        AND is_nullable = 'NO'
                    ) THEN
                        ALTER TABLE accounts_batch ALTER COLUMN program_id DROP NOT NULL;
                    END IF;
                END $$;
            ''',
            # Reverse SQL: No-op since we don't want to restore NOT NULL
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
