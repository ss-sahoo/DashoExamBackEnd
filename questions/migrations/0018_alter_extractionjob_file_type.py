# Generated migration to fix file_type max_length

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('questions', '0017_alter_questionembedding_combined_embedding_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='extractionjob',
            name='file_type',
            field=models.CharField(max_length=100, help_text='MIME type of uploaded file'),
        ),
    ]
