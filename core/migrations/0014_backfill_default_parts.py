from django.db import migrations


def backfill_default_parts(apps, schema_editor):
    Exercise = apps.get_model("core", "Exercise")
    ExerciseVariant = apps.get_model("core", "ExerciseVariant")
    ExercisePart = apps.get_model("core", "ExercisePart")

    for exercise in Exercise.objects.all():
        if ExercisePart.objects.filter(variant__exercise_id=exercise.id).exists():
            continue
        variant = ExerciseVariant.objects.filter(exercise_id=exercise.id).order_by("id").first()
        if variant is None:
            variant = ExerciseVariant.objects.create(
                exercise_id=exercise.id,
                exercise_text="",
                supervisor_notes="Auto-created during exercise type migration.",
            )
        ExercisePart.objects.create(
            variant_id=variant.id,
            label="a",
            prompt_text="",
            answer_type="numerical",
            reference_solution="0.0000",
            absolute_tolerance="0.0000",
            available_points="1.00",
            order_index=1,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_remove_exercisevariant_absolute_tolerance_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_default_parts, migrations.RunPython.noop),
    ]
