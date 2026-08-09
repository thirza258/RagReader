from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('evaluation', '0002_chunk_config_hash_chunk_unique_chunk_per_config'),
    ]

    operations = [
        migrations.AddField(
            model_name='groundtruthchunk',
            name='source',
            field=models.CharField(
                choices=[('manual', 'Manually selected'), ('pooled', 'Candidate pooling (RRF)')],
                db_index=True,
                default='manual',
                help_text='How this chunk was chosen as ground truth.',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='groundtruthchunk',
            name='rank',
            field=models.PositiveIntegerField(blank=True, help_text='1-based RRF rank (pooled only).', null=True),
        ),
        migrations.AddField(
            model_name='groundtruthchunk',
            name='rrf_score',
            field=models.FloatField(blank=True, help_text='Fused RRF score (pooled only).', null=True),
        ),
        migrations.AddField(
            model_name='groundtruthchunk',
            name='metadata',
            field=models.JSONField(blank=True, default=dict, help_text='Which pipelines contributed, and at what rank.'),
        ),
        migrations.AlterModelOptions(
            name='groundtruthchunk',
            options={'ordering': ['rank', 'id']},
        ),
    ]
