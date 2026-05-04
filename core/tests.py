from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import path, reverse
from django.views import View

from .access import (
    AdministratorRequiredMixin,
    SupervisorRequiredMixin,
    administrator_required,
    supervisor_required,
)
from .models import Course, Exercise, ExerciseVariant, Result, Tutorial, User


class UserEmailDomainValidationTests(TestCase):
    def test_accepts_unibas_domain(self):
        user = User(email="student@unibas.ch", password="dummy-password")
        user.full_clean()

    def test_accepts_stud_unibas_domain(self):
        user = User(email="student@stud.unibas.ch", password="dummy-password")
        user.full_clean()

    def test_accepts_domains_case_insensitively(self):
        user = User(email="Student@StUd.UnIbAs.Ch", password="dummy-password")
        user.full_clean()

    def test_rejects_non_university_domain(self):
        user = User(email="student@example.com", password="dummy-password")
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_rejects_similar_but_invalid_domain(self):
        user = User(email="student@evilunibas.ch", password="dummy-password")
        with self.assertRaises(ValidationError):
            user.full_clean()


@supervisor_required
def supervisor_decorator_view(request):
    return HttpResponse("ok")


@administrator_required
def administrator_decorator_view(request):
    return HttpResponse("ok")


class SupervisorMixinView(SupervisorRequiredMixin, View):
    def get(self, request):
        return HttpResponse("ok")


class AdministratorMixinView(AdministratorRequiredMixin, View):
    def get(self, request):
        return HttpResponse("ok")


urlpatterns = [
    path("decorator/supervisor/", supervisor_decorator_view),
    path("decorator/administrator/", administrator_decorator_view),
    path("mixin/supervisor/", SupervisorMixinView.as_view()),
    path("mixin/administrator/", AdministratorMixinView.as_view()),
]


@override_settings(ROOT_URLCONF="core.tests")
class RoleAccessHelpersTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(email="student@unibas.ch", password="test-password")
        self.supervisor = User.objects.create_user(
            email="supervisor@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.administrator = User.objects.create_user(
            email="admin@unibas.ch",
            password="test-password",
            role=User.Role.ADMINISTRATOR,
        )

    def test_student_cannot_access_supervisor_decorator_view(self):
        self.client.force_login(self.student)
        response = self.client.get("/decorator/supervisor/")
        self.assertEqual(response.status_code, 403)

    def test_supervisor_can_access_supervisor_decorator_view(self):
        self.client.force_login(self.supervisor)
        response = self.client.get("/decorator/supervisor/")
        self.assertEqual(response.status_code, 200)

    def test_administrator_can_access_supervisor_decorator_view(self):
        self.client.force_login(self.administrator)
        response = self.client.get("/decorator/supervisor/")
        self.assertEqual(response.status_code, 200)

    def test_only_administrator_can_access_administrator_decorator_view(self):
        self.client.force_login(self.supervisor)
        response = self.client.get("/decorator/administrator/")
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.administrator)
        response = self.client.get("/decorator/administrator/")
        self.assertEqual(response.status_code, 200)

    def test_supervisor_and_administrator_can_access_supervisor_mixin_view(self):
        self.client.force_login(self.supervisor)
        response = self.client.get("/mixin/supervisor/")
        self.assertEqual(response.status_code, 200)

        self.client.force_login(self.administrator)
        response = self.client.get("/mixin/supervisor/")
        self.assertEqual(response.status_code, 200)

    def test_student_cannot_access_supervisor_mixin_view(self):
        self.client.force_login(self.student)
        response = self.client.get("/mixin/supervisor/")
        self.assertEqual(response.status_code, 403)

    def test_only_administrator_can_access_administrator_mixin_view(self):
        self.client.force_login(self.student)
        response = self.client.get("/mixin/administrator/")
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.supervisor)
        response = self.client.get("/mixin/administrator/")
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.administrator)
        response = self.client.get("/mixin/administrator/")
        self.assertEqual(response.status_code, 200)


class Phase2ModelTests(TestCase):
    def setUp(self):
        self.supervisor = User.objects.create_user(
            email="supervisor@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.student = User.objects.create_user(
            email="student@unibas.ch",
            password="test-password",
            role=User.Role.STUDENT,
        )
        self.grader = User.objects.create_user(
            email="grader@unibas.ch",
            password="test-password",
            role=User.Role.ADMINISTRATOR,
        )

    def test_create_phase2_models_and_relationships(self):
        course = Course.objects.create(
            title="Chemistry 101",
            description="Intro course",
            created_by=self.supervisor,
        )
        tutorial = Tutorial.objects.create(
            course=course,
            title="Tutorial 1",
            description="Basics",
            order_index=1,
        )
        exercise = Exercise.objects.create(
            tutorial=tutorial,
            title="Exercise 1",
            order_index=1,
            exercise_type=Exercise.ExerciseType.NUMERICAL,
        )
        variant = ExerciseVariant.objects.create(
            exercise=exercise,
            exercise_text="Calculate pH.",
            reference_solution="7.0000",
            absolute_tolerance="0.1000",
            available_points="5.00",
        )
        result = Result.objects.create(
            student=self.student,
            course=course,
            tutorial=tutorial,
            exercise=exercise,
            assigned_variant=variant,
            submitted_numerical_value="7.0500",
            score="5.00",
            is_correct=True,
            is_manually_graded=False,
            feedback="Well done",
            graded_by=self.grader,
            is_archived=False,
        )

        self.assertEqual(tutorial.course, course)
        self.assertEqual(exercise.tutorial, tutorial)
        self.assertEqual(variant.exercise, exercise)
        self.assertEqual(result.student, self.student)
        self.assertEqual(result.assigned_variant, variant)

    def test_str_methods_return_useful_strings(self):
        course = Course.objects.create(title="Thermodynamics", created_by=self.supervisor)
        tutorial = Tutorial.objects.create(course=course, title="Week 1", order_index=1)
        exercise = Exercise.objects.create(
            tutorial=tutorial,
            title="Heat Balance",
            order_index=1,
            exercise_type=Exercise.ExerciseType.NUMERICAL,
        )
        variant = ExerciseVariant.objects.create(exercise=exercise, exercise_text="Compute Q.")
        result = Result.objects.create(
            student=self.student,
            course=course,
            tutorial=tutorial,
            exercise=exercise,
            assigned_variant=variant,
        )

        self.assertIn("Thermodynamics", str(course))
        self.assertIn("Week 1", str(tutorial))
        self.assertIn("Heat Balance", str(exercise))
        self.assertIn("Variant", str(variant))
        self.assertIn(self.student.email, str(result))

    def test_one_active_result_per_student_per_exercise_constraint(self):
        course = Course.objects.create(title="Organic Chem", created_by=self.supervisor)
        tutorial = Tutorial.objects.create(course=course, title="Lab", order_index=1)
        exercise = Exercise.objects.create(
            tutorial=tutorial,
            title="Molecule Naming",
            order_index=1,
            exercise_type=Exercise.ExerciseType.DOCUMENT_UPLOAD,
        )
        variant = ExerciseVariant.objects.create(exercise=exercise, exercise_text="Upload answer sheet.")

        Result.objects.create(
            student=self.student,
            course=course,
            tutorial=tutorial,
            exercise=exercise,
            assigned_variant=variant,
            is_archived=False,
        )

        with self.assertRaises(IntegrityError):
            Result.objects.create(
                student=self.student,
                course=course,
                tutorial=tutorial,
                exercise=exercise,
                assigned_variant=variant,
                is_archived=False,
            )


class ExerciseValidationTests(TestCase):
    def setUp(self):
        self.supervisor = User.objects.create_user(
            email="supervisor_validation@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.course = Course.objects.create(title="Validation Course", created_by=self.supervisor)
        self.tutorial = Tutorial.objects.create(
            course=self.course,
            title="Validation Tutorial",
            order_index=1,
        )

    def test_exercise_type_must_be_numerical_or_upload(self):
        exercise = Exercise(
            tutorial=self.tutorial,
            title="Invalid type exercise",
            order_index=1,
            exercise_type="invalid_type",
        )
        with self.assertRaises(ValidationError):
            exercise.full_clean()

    def test_numerical_variant_requires_reference_tolerance_and_points(self):
        exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Numerical exercise",
            order_index=1,
            exercise_type=Exercise.ExerciseType.NUMERICAL,
        )
        variant = ExerciseVariant(
            exercise=exercise,
            exercise_text="Compute result.",
            reference_solution=None,
            absolute_tolerance=None,
            available_points=None,
        )
        with self.assertRaises(ValidationError) as ctx:
            variant.full_clean()
        self.assertIn("reference_solution", ctx.exception.message_dict)
        self.assertIn("absolute_tolerance", ctx.exception.message_dict)
        self.assertIn("available_points", ctx.exception.message_dict)

    def test_upload_variant_does_not_require_reference_solution(self):
        exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Upload exercise",
            order_index=2,
            exercise_type=Exercise.ExerciseType.DOCUMENT_UPLOAD,
        )
        variant = ExerciseVariant(
            exercise=exercise,
            exercise_text="Upload your document.",
            reference_solution=None,
            absolute_tolerance=None,
            available_points="2.00",
        )
        variant.full_clean()

    def test_available_points_must_be_non_negative(self):
        exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Points check exercise",
            order_index=3,
            exercise_type=Exercise.ExerciseType.DOCUMENT_UPLOAD,
        )
        variant = ExerciseVariant(
            exercise=exercise,
            exercise_text="Any answer.",
            available_points="-0.01",
        )
        with self.assertRaises(ValidationError) as ctx:
            variant.full_clean()
        self.assertIn("available_points", ctx.exception.message_dict)

    def test_tolerance_must_be_non_negative(self):
        exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Tolerance check exercise",
            order_index=4,
            exercise_type=Exercise.ExerciseType.NUMERICAL,
        )
        variant = ExerciseVariant(
            exercise=exercise,
            exercise_text="Compute value.",
            reference_solution="1.0000",
            absolute_tolerance="-0.1000",
            available_points="1.00",
        )
        with self.assertRaises(ValidationError) as ctx:
            variant.full_clean()
        self.assertIn("absolute_tolerance", ctx.exception.message_dict)


class Phase3SupervisorAdminTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email="student_admin@unibas.ch",
            password="test-password",
            role=User.Role.STUDENT,
        )
        self.supervisor_a = User.objects.create_user(
            email="supervisor_a@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.supervisor_b = User.objects.create_user(
            email="supervisor_b@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.administrator = User.objects.create_user(
            email="administrator_admin@unibas.ch",
            password="test-password",
            role=User.Role.ADMINISTRATOR,
        )

        self.course_a = Course.objects.create(title="Supervisor A Course", created_by=self.supervisor_a)
        self.course_b = Course.objects.create(title="Supervisor B Course", created_by=self.supervisor_b)

    def test_student_cannot_access_django_admin(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_supervisor_can_access_admin_and_create_course(self):
        self.client.force_login(self.supervisor_a)
        index_response = self.client.get(reverse("admin:index"))
        self.assertEqual(index_response.status_code, 200)

        add_response = self.client.post(
            reverse("admin:core_course_add"),
            {
                "title": "Created by Supervisor A",
                "description": "Created in admin test",
                "_save": "Save",
            },
        )
        self.assertEqual(add_response.status_code, 302)
        self.assertTrue(
            Course.objects.filter(
                title="Created by Supervisor A",
                created_by=self.supervisor_a,
            ).exists()
        )

    def test_supervisor_cannot_see_or_edit_other_supervisor_courses(self):
        self.client.force_login(self.supervisor_a)
        list_response = self.client.get(reverse("admin:core_course_changelist"))
        self.assertContains(list_response, "Supervisor A Course")
        self.assertNotContains(list_response, "Supervisor B Course")

        change_response = self.client.get(reverse("admin:core_course_change", args=[self.course_b.id]))
        self.assertEqual(change_response.status_code, 302)

        post_response = self.client.post(
            reverse("admin:core_course_change", args=[self.course_b.id]),
            {
                "title": "Illicit update attempt",
                "description": self.course_b.description,
                "created_by": self.course_b.created_by_id,
                "is_active": "on",
                "_save": "Save",
            },
        )
        self.assertEqual(post_response.status_code, 302)
        self.course_b.refresh_from_db()
        self.assertEqual(self.course_b.title, "Supervisor B Course")

    def test_administrator_can_see_and_edit_all_courses(self):
        self.client.force_login(self.administrator)
        list_response = self.client.get(reverse("admin:core_course_changelist"))
        self.assertContains(list_response, "Supervisor A Course")
        self.assertContains(list_response, "Supervisor B Course")

        change_response = self.client.post(
            reverse("admin:core_course_change", args=[self.course_b.id]),
            {
                "title": "Supervisor B Course Updated",
                "description": self.course_b.description,
                "created_by": self.course_b.created_by_id,
                "is_active": "on",
                "_save": "Save",
            },
        )
        self.assertEqual(change_response.status_code, 302)
        self.course_b.refresh_from_db()
        self.assertEqual(self.course_b.title, "Supervisor B Course Updated")
