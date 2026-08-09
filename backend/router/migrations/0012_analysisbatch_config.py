from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('router', '0011_remove_analysisresult_model_agreement'),
    ]

    operations = [
        migrations.AddField(
            model_name='analysisbatch',
            name='config',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Normalized analysis config: methods, models, top_k, ground_truth_mode.',
            ),
        ),
    ]
