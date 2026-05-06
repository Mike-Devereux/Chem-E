from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0014_backfill_default_parts"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="exercise",
            name="exercise_type",
        ),
    ]
