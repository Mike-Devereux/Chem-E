from django.core.management.base import BaseCommand
from django.db.models import Q

from core.models import Course, Exercise, ExercisePart, ExerciseVariant, Tutorial, User


class Command(BaseCommand):
    help = "Seed idempotent demo course/tutorial/exercise data for local development."

    def handle(self, *args, **options):
        creator = (
            User.objects.filter(
                Q(role=User.Role.SUPERVISOR)
                | Q(role=User.Role.ADMINISTRATOR)
                | Q(is_superuser=True)
            )
            .order_by("id")
            .first()
        )
        if creator is None:
            self.stdout.write(
                self.style.ERROR(
                    "No supervisor/admin user found. Create one first, then rerun: "
                    "`python manage.py seed_demo_data`."
                )
            )
            return

        course, _ = Course.objects.get_or_create(
            title="Demo Chemical Engineering Course",
            defaults={
                "description": "Seeded demo course for local development.",
                "is_active": True,
                "created_by": creator,
            },
        )

        tutorial_1, _ = Tutorial.objects.get_or_create(
            course=course,
            order_index=1,
            defaults={
                "title": "Tutorial 1: Balances",
                "description": "Material and energy balance exercises.",
                "is_active": True,
            },
        )
        tutorial_2, _ = Tutorial.objects.get_or_create(
            course=course,
            order_index=2,
            defaults={
                "title": "Tutorial 2: Separation",
                "description": "Distillation and separation exercises.",
                "is_active": True,
            },
        )

        ex1, _ = Exercise.objects.get_or_create(
            tutorial=tutorial_1,
            order_index=1,
            defaults={
                "title": "Mass balance basics",
                "exercise_type": Exercise.ExerciseType.NUMERICAL,
                "is_active": True,
            },
        )
        ex2, _ = Exercise.objects.get_or_create(
            tutorial=tutorial_1,
            order_index=2,
            defaults={
                "title": "Upload process sketch",
                "exercise_type": Exercise.ExerciseType.DOCUMENT_UPLOAD,
                "is_active": True,
            },
        )
        ex3, _ = Exercise.objects.get_or_create(
            tutorial=tutorial_2,
            order_index=1,
            defaults={
                "title": "Distillation reflux ratio",
                "exercise_type": Exercise.ExerciseType.NUMERICAL,
                "is_active": True,
            },
        )

        variant_1, _ = ExerciseVariant.objects.get_or_create(
            exercise=ex1,
            exercise_text="Calculate outlet mass flow for a steady-state mixer.",
            defaults={
                "supervisor_notes": "Demo numerical variant.",
            },
        )
        ExercisePart.objects.get_or_create(
            variant=variant_1,
            order_index=1,
            defaults={
                "label": "a",
                "prompt_text": "Outlet mass flow",
                "answer_type": ExerciseVariant.PartAnswerType.NUMERICAL,
                "reference_solution": "12.5000",
                "absolute_tolerance": "0.0500",
                "available_points": "5.00",
            },
        )
        variant_2, _ = ExerciseVariant.objects.get_or_create(
            exercise=ex2,
            exercise_text="Upload a labeled block-flow diagram of the process.",
            defaults={
                "supervisor_notes": "Demo upload variant.",
            },
        )
        ExercisePart.objects.get_or_create(
            variant=variant_2,
            order_index=1,
            defaults={
                "label": "a",
                "prompt_text": "Upload your block-flow diagram",
                "answer_type": ExerciseVariant.PartAnswerType.DOCUMENT_UPLOAD,
                "available_points": "4.00",
            },
        )
        variant_3, _ = ExerciseVariant.objects.get_or_create(
            exercise=ex3,
            exercise_text="Compute reflux ratio given target top and bottom purities.",
            defaults={
                "supervisor_notes": "Second demo numerical variant.",
            },
        )
        ExercisePart.objects.get_or_create(
            variant=variant_3,
            order_index=1,
            defaults={
                "label": "a",
                "prompt_text": "Reflux ratio",
                "answer_type": ExerciseVariant.PartAnswerType.NUMERICAL,
                "reference_solution": "2.7500",
                "absolute_tolerance": "0.1000",
                "available_points": "6.00",
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Demo data seeded successfully (idempotent): "
                "1 course, 2 tutorials, 3 exercises, and variants."
            )
        )
