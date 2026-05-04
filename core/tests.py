from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from django.db import IntegrityError
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import path, reverse
from django.views import View
import os
import tempfile

from .access import (
    AdministratorRequiredMixin,
    SupervisorRequiredMixin,
    administrator_required,
    supervisor_required,
)
from .grading import is_numerical_answer_correct
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


class ExerciseVariantAssignmentTests(TestCase):
    def setUp(self):
        self.supervisor = User.objects.create_user(
            email="supervisor_variant@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.student = User.objects.create_user(
            email="student_variant@unibas.ch",
            password="test-password",
            role=User.Role.STUDENT,
        )
        self.course = Course.objects.create(title="Variant Course", created_by=self.supervisor)
        self.tutorial = Tutorial.objects.create(
            course=self.course,
            title="Variant Tutorial",
            order_index=1,
        )
        self.exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Variant Exercise",
            order_index=1,
            exercise_type=Exercise.ExerciseType.NUMERICAL,
            is_active=True,
        )
        self.variant_a = ExerciseVariant.objects.create(
            exercise=self.exercise,
            exercise_text="Variant A text",
            reference_solution="1.0000",
            absolute_tolerance="0.1000",
            available_points="1.00",
        )
        self.variant_b = ExerciseVariant.objects.create(
            exercise=self.exercise,
            exercise_text="Variant B text",
            reference_solution="2.0000",
            absolute_tolerance="0.1000",
            available_points="1.00",
        )

    def test_first_access_assigns_random_variant_and_stores_result(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("exercise_detail", args=[self.exercise.id]))
        self.assertEqual(response.status_code, 200)

        result = Result.objects.get(student=self.student, exercise=self.exercise, is_archived=False)
        self.assertIn(result.assigned_variant_id, [self.variant_a.id, self.variant_b.id])
        self.assertEqual(response.context["variant"].id, result.assigned_variant_id)

    def test_revisit_keeps_same_assigned_variant(self):
        self.client.force_login(self.student)
        self.client.get(reverse("exercise_detail", args=[self.exercise.id]))
        first_result = Result.objects.get(
            student=self.student,
            exercise=self.exercise,
            is_archived=False,
        )

        second_response = self.client.get(reverse("exercise_detail", args=[self.exercise.id]))
        self.assertEqual(second_response.status_code, 200)

        second_result = Result.objects.get(
            student=self.student,
            exercise=self.exercise,
            is_archived=False,
        )
        self.assertEqual(Result.objects.filter(student=self.student, exercise=self.exercise).count(), 1)
        self.assertEqual(first_result.assigned_variant_id, second_result.assigned_variant_id)
        self.assertEqual(second_response.context["variant"].id, second_result.assigned_variant_id)

    def test_variant_is_stable_on_multiple_page_reloads(self):
        self.client.force_login(self.student)
        first_response = self.client.get(reverse("exercise_detail", args=[self.exercise.id]))
        second_response = self.client.get(reverse("exercise_detail", args=[self.exercise.id]))
        third_response = self.client.get(reverse("exercise_detail", args=[self.exercise.id]))

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(third_response.status_code, 200)

        variant_id = first_response.context["variant"].id
        self.assertEqual(second_response.context["variant"].id, variant_id)
        self.assertEqual(third_response.context["variant"].id, variant_id)
        self.assertEqual(
            Result.objects.filter(
                student=self.student,
                exercise=self.exercise,
                is_archived=False,
            ).count(),
            1,
        )


class NumericalAnswerFormViewTests(TestCase):
    def setUp(self):
        self.supervisor = User.objects.create_user(
            email="supervisor_form@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.student = User.objects.create_user(
            email="student_form@unibas.ch",
            password="test-password",
            role=User.Role.STUDENT,
        )
        self.course = Course.objects.create(title="Form Course", created_by=self.supervisor)
        self.tutorial = Tutorial.objects.create(course=self.course, title="Form Tutorial", order_index=1)
        self.numerical_exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Numerical Form Exercise",
            order_index=1,
            exercise_type=Exercise.ExerciseType.NUMERICAL,
        )
        self.upload_exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Upload Form Exercise",
            order_index=2,
            exercise_type=Exercise.ExerciseType.DOCUMENT_UPLOAD,
        )
        ExerciseVariant.objects.create(
            exercise=self.numerical_exercise,
            exercise_text="Enter a number.",
            reference_solution="10.0000",
            absolute_tolerance="0.1000",
            available_points="2.00",
        )
        ExerciseVariant.objects.create(
            exercise=self.upload_exercise,
            exercise_text="Upload a file.",
            available_points="2.00",
        )

    def test_numerical_exercise_shows_form_and_accepts_numeric_input(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("exercise_detail", args=[self.numerical_exercise.id]))
        self.assertContains(response, "Submit numerical answer")
        self.assertIn("numerical_form", response.context)

        post_response = self.client.post(
            reverse("exercise_detail", args=[self.numerical_exercise.id]),
            {"submitted_value": "12.34"},
        )
        self.assertEqual(post_response.status_code, 200)
        self.assertContains(post_response, "Your latest result")
        self.assertContains(post_response, "Submitted value: 12.3400")

    def test_numerical_exercise_rejects_non_numeric_input(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("exercise_detail", args=[self.numerical_exercise.id]),
            {"submitted_value": "not-a-number"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["numerical_form"],
            "submitted_value",
            "Enter a number.",
        )

    def test_upload_exercise_does_not_show_numerical_form(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("exercise_detail", args=[self.upload_exercise.id]))
        self.assertNotContains(response, "Submit numerical answer")
        self.assertNotIn("numerical_form", response.context)
        self.assertContains(response, "Upload solution file")
        self.assertIn("upload_form", response.context)

    def test_numerical_submission_stores_result_fields(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("exercise_detail", args=[self.numerical_exercise.id]),
            {"submitted_value": "10.02"},
        )
        self.assertEqual(response.status_code, 200)

        result = Result.objects.get(
            student=self.student,
            exercise=self.numerical_exercise,
            is_archived=False,
        )
        self.assertEqual(str(result.submitted_numerical_value), "10.0200")
        self.assertTrue(result.is_correct)
        self.assertEqual(str(result.score), "2.00")
        self.assertIsNotNone(result.submitted_at)
        self.assertEqual(result.assigned_variant.exercise, self.numerical_exercise)

    def test_second_submission_updates_existing_result(self):
        self.client.force_login(self.student)
        self.client.post(
            reverse("exercise_detail", args=[self.numerical_exercise.id]),
            {"submitted_value": "9.00"},
        )
        first_result = Result.objects.get(
            student=self.student,
            exercise=self.numerical_exercise,
            is_archived=False,
        )

        self.client.post(
            reverse("exercise_detail", args=[self.numerical_exercise.id]),
            {"submitted_value": "10.00"},
        )
        second_result = Result.objects.get(
            student=self.student,
            exercise=self.numerical_exercise,
            is_archived=False,
        )

        self.assertEqual(
            Result.objects.filter(
                student=self.student,
                exercise=self.numerical_exercise,
                is_archived=False,
            ).count(),
            1,
        )
        self.assertEqual(first_result.id, second_result.id)
        self.assertEqual(first_result.assigned_variant_id, second_result.assigned_variant_id)
        self.assertEqual(str(second_result.submitted_numerical_value), "10.0000")
        self.assertTrue(second_result.is_correct)
        self.assertEqual(str(second_result.score), "2.00")

    def test_revisit_shows_existing_submission_result(self):
        self.client.force_login(self.student)
        self.client.post(
            reverse("exercise_detail", args=[self.numerical_exercise.id]),
            {"submitted_value": "10.00"},
        )
        revisit_response = self.client.get(
            reverse("exercise_detail", args=[self.numerical_exercise.id])
        )
        self.assertEqual(revisit_response.status_code, 200)
        self.assertContains(revisit_response, "Your latest result")
        self.assertContains(revisit_response, "Submitted value: 10.0000")
        self.assertContains(revisit_response, "Correct: True")
        self.assertContains(revisit_response, "Score: 2.00")

    def test_upload_submission_saves_file_to_existing_result(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("exercise_detail", args=[self.upload_exercise.id]),
            {"uploaded_file": SimpleUploadedFile("solution.pdf", b"upload content")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your latest upload")

        result = Result.objects.get(
            student=self.student,
            exercise=self.upload_exercise,
            is_archived=False,
        )
        self.assertTrue(bool(result.uploaded_file))
        self.assertTrue(result.uploaded_file.name.endswith(".pdf"))
        self.assertIn("student_submissions/", result.uploaded_file.name)
        self.assertEqual(result.assigned_variant.exercise, self.upload_exercise)
        self.assertEqual(str(result.score), "0.00")
        self.assertFalse(result.is_manually_graded)
        self.assertIsNone(result.submitted_numerical_value)

    def test_upload_submission_can_replace_file_before_manual_grading(self):
        media_dir = tempfile.mkdtemp()
        try:
            with self.settings(MEDIA_ROOT=media_dir):
                self.client.force_login(self.student)
                self.client.post(
                    reverse("exercise_detail", args=[self.upload_exercise.id]),
                    {"uploaded_file": SimpleUploadedFile("first.pdf", b"first")},
                )
                result = Result.objects.get(
                    student=self.student,
                    exercise=self.upload_exercise,
                    is_archived=False,
                )
                old_name = result.uploaded_file.name
                self.assertTrue(default_storage.exists(old_name))

                self.client.post(
                    reverse("exercise_detail", args=[self.upload_exercise.id]),
                    {"uploaded_file": SimpleUploadedFile("second.pdf", b"second")},
                )
                result.refresh_from_db()
                self.assertIn("second", os.path.basename(result.uploaded_file.name))
                self.assertFalse(default_storage.exists(old_name))
        finally:
            for root, dirs, files in os.walk(media_dir, topdown=False):
                for file_name in files:
                    os.remove(os.path.join(root, file_name))
                for dir_name in dirs:
                    os.rmdir(os.path.join(root, dir_name))
            os.rmdir(media_dir)

    def test_upload_submission_cannot_replace_after_manual_grading(self):
        self.client.force_login(self.student)
        self.client.post(
            reverse("exercise_detail", args=[self.upload_exercise.id]),
            {"uploaded_file": SimpleUploadedFile("graded.pdf", b"graded")},
        )
        result = Result.objects.get(
            student=self.student,
            exercise=self.upload_exercise,
            is_archived=False,
        )
        original_name = result.uploaded_file.name
        result.is_manually_graded = True
        result.save(update_fields=["is_manually_graded"])

        response = self.client.post(
            reverse("exercise_detail", args=[self.upload_exercise.id]),
            {"uploaded_file": SimpleUploadedFile("new_attempt.pdf", b"new")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot be replaced")
        result.refresh_from_db()
        self.assertEqual(result.uploaded_file.name, original_name)

    def test_upload_submission_rejects_disallowed_file_type(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("exercise_detail", args=[self.upload_exercise.id]),
            {"uploaded_file": SimpleUploadedFile("malware.exe", b"x")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["upload_form"],
            "uploaded_file",
            "Unsupported file extension. Allowed: pdf, docx, png, jpg, jpeg, tif, tiff.",
        )
        self.assertEqual(
            Result.objects.filter(
                student=self.student,
                exercise=self.upload_exercise,
                is_archived=False,
            ).count(),
            1,
        )
        result = Result.objects.get(
            student=self.student,
            exercise=self.upload_exercise,
            is_archived=False,
        )
        self.assertFalse(bool(result.uploaded_file))

    def test_upload_submission_rejects_oversized_file(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("exercise_detail", args=[self.upload_exercise.id]),
            {"uploaded_file": SimpleUploadedFile("big.pdf", b"a" * (20 * 1024 * 1024 + 1))},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["upload_form"],
            "uploaded_file",
            "File size must be 20 MB or smaller.",
        )
        self.assertEqual(
            Result.objects.filter(
                student=self.student,
                exercise=self.upload_exercise,
                is_archived=False,
            ).count(),
            1,
        )
        result = Result.objects.get(
            student=self.student,
            exercise=self.upload_exercise,
            is_archived=False,
        )
        self.assertFalse(bool(result.uploaded_file))


class NumericalCheckingTests(TestCase):
    def test_correct_answer_within_tolerance(self):
        self.assertTrue(
            is_numerical_answer_correct(
                submitted_value="10.04",
                reference_solution="10.00",
                absolute_tolerance="0.05",
            )
        )

    def test_incorrect_answer_outside_tolerance(self):
        self.assertFalse(
            is_numerical_answer_correct(
                submitted_value="10.10",
                reference_solution="10.00",
                absolute_tolerance="0.05",
            )
        )


class StudentUploadValidationTests(TestCase):
    def setUp(self):
        self.supervisor = User.objects.create_user(
            email="supervisor_upload_validation@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.student = User.objects.create_user(
            email="student_upload_validation@unibas.ch",
            password="test-password",
            role=User.Role.STUDENT,
        )
        self.course = Course.objects.create(title="Upload Validation Course", created_by=self.supervisor)
        self.tutorial = Tutorial.objects.create(
            course=self.course,
            title="Upload Validation Tutorial",
            order_index=1,
        )
        self.exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Upload Validation Exercise",
            order_index=1,
            exercise_type=Exercise.ExerciseType.DOCUMENT_UPLOAD,
        )
        self.variant = ExerciseVariant.objects.create(
            exercise=self.exercise,
            exercise_text="Upload a document.",
            available_points="1.00",
        )

    def test_allows_supported_file_extension(self):
        uploaded_file = SimpleUploadedFile(
            "solution.pdf",
            b"dummy pdf content",
            content_type="application/pdf",
        )
        result = Result(
            student=self.student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=self.exercise,
            assigned_variant=self.variant,
            uploaded_file=uploaded_file,
        )
        result.full_clean()

    def test_rejects_unsupported_file_extension(self):
        uploaded_file = SimpleUploadedFile(
            "solution.exe",
            b"binary",
            content_type="application/octet-stream",
        )
        result = Result(
            student=self.student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=self.exercise,
            assigned_variant=self.variant,
            uploaded_file=uploaded_file,
        )
        with self.assertRaises(ValidationError) as ctx:
            result.full_clean()
        self.assertIn("uploaded_file", ctx.exception.message_dict)


class SupervisorExerciseSubmissionsViewTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email="student_submissions_view@unibas.ch",
            password="test-password",
            role=User.Role.STUDENT,
        )
        self.supervisor = User.objects.create_user(
            email="supervisor_submissions_view@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.administrator = User.objects.create_user(
            email="admin_submissions_view@unibas.ch",
            password="test-password",
            role=User.Role.ADMINISTRATOR,
        )
        self.course = Course.objects.create(title="Submissions Course", created_by=self.supervisor)
        self.tutorial = Tutorial.objects.create(course=self.course, title="Week 1", order_index=1)
        self.exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Submission Exercise",
            order_index=1,
            exercise_type=Exercise.ExerciseType.NUMERICAL,
        )
        self.variant = ExerciseVariant.objects.create(
            exercise=self.exercise,
            exercise_text="Solve question",
            reference_solution="1.0000",
            absolute_tolerance="0.1000",
            available_points="3.00",
        )
        Result.objects.create(
            student=self.student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=self.exercise,
            assigned_variant=self.variant,
            submitted_numerical_value="1.0000",
            is_correct=True,
            score="3.00",
            is_manually_graded=True,
        )

    def test_student_cannot_access_supervisor_submissions_page(self):
        self.client.force_login(self.student)
        response = self.client.get(
            reverse("supervisor_exercise_submissions", args=[self.exercise.id])
        )
        self.assertEqual(response.status_code, 403)

    def test_supervisor_can_access_and_see_submission_table(self):
        self.client.force_login(self.supervisor)
        response = self.client.get(
            reverse("supervisor_exercise_submissions", args=[self.exercise.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Submissions for Submission Exercise")
        self.assertContains(response, self.student.email)
        self.assertContains(response, "Yes")
        self.assertContains(response, "3.00")

    def test_administrator_can_access_supervisor_submissions_page(self):
        self.client.force_login(self.administrator)
        response = self.client.get(
            reverse("supervisor_exercise_submissions", args=[self.exercise.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_supervisor_submission_detail_page_shows_required_fields(self):
        result = Result.objects.get(student=self.student, exercise=self.exercise, is_archived=False)
        result.feedback = "Well explained."
        result.uploaded_file = SimpleUploadedFile("answer.pdf", b"file-data")
        result.save(update_fields=["feedback", "uploaded_file"])

        self.client.force_login(self.supervisor)
        response = self.client.get(
            reverse("supervisor_submission_detail", args=[result.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.student.email)
        self.assertContains(response, self.exercise.title)
        self.assertContains(response, self.variant.exercise_text)
        self.assertContains(response, "answer")
        self.assertContains(response, ".pdf")
        self.assertContains(response, "3.00")
        self.assertContains(response, "Well explained.")

    def test_student_cannot_access_supervisor_submission_detail(self):
        result = Result.objects.get(student=self.student, exercise=self.exercise, is_archived=False)
        self.client.force_login(self.student)
        response = self.client.get(
            reverse("supervisor_submission_detail", args=[result.id])
        )
        self.assertEqual(response.status_code, 403)

    def test_administrator_can_access_supervisor_submission_detail(self):
        result = Result.objects.get(student=self.student, exercise=self.exercise, is_archived=False)
        self.client.force_login(self.administrator)
        response = self.client.get(
            reverse("supervisor_submission_detail", args=[result.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_supervisor_submission_detail_invalid_id_returns_404(self):
        self.client.force_login(self.supervisor)
        response = self.client.get(
            reverse("supervisor_submission_detail", args=[999999])
        )
        self.assertEqual(response.status_code, 404)

    def test_supervisor_can_download_uploaded_file_from_submission(self):
        result = Result.objects.get(student=self.student, exercise=self.exercise, is_archived=False)
        result.uploaded_file = SimpleUploadedFile("download.pdf", b"download-content")
        result.save(update_fields=["uploaded_file"])

        self.client.force_login(self.supervisor)
        response = self.client.get(
            reverse("supervisor_submission_file_download", args=[result.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn(".pdf", response["Content-Disposition"])

    def test_student_cannot_download_uploaded_file_from_submission(self):
        result = Result.objects.get(student=self.student, exercise=self.exercise, is_archived=False)
        result.uploaded_file = SimpleUploadedFile("private.pdf", b"private-content")
        result.save(update_fields=["uploaded_file"])

        self.client.force_login(self.student)
        response = self.client.get(
            reverse("supervisor_submission_file_download", args=[result.id])
        )
        self.assertEqual(response.status_code, 403)

    def test_rejects_file_larger_than_20_mb(self):
        uploaded_file = SimpleUploadedFile(
            "solution.pdf",
            b"a" * (20 * 1024 * 1024 + 1),
            content_type="application/pdf",
        )
        result = Result(
            student=self.student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=self.exercise,
            assigned_variant=self.variant,
            uploaded_file=uploaded_file,
        )
        with self.assertRaises(ValidationError) as ctx:
            result.full_clean()
        self.assertIn("uploaded_file", ctx.exception.message_dict)

    def test_manual_grading_form_visible_only_for_upload_type_submission(self):
        # Numerical exercise result should not show upload grading form.
        numerical_result = Result.objects.get(
            student=self.student, exercise=self.exercise, is_archived=False
        )
        self.client.force_login(self.supervisor)
        numerical_response = self.client.get(
            reverse("supervisor_submission_detail", args=[numerical_result.id])
        )
        self.assertNotContains(numerical_response, "Manual grading")

        # Upload exercise result should show grading form.
        upload_exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Upload Submission Exercise",
            order_index=2,
            exercise_type=Exercise.ExerciseType.DOCUMENT_UPLOAD,
        )
        upload_variant = ExerciseVariant.objects.create(
            exercise=upload_exercise,
            exercise_text="Upload your report.",
            available_points="4.00",
        )
        upload_result = Result.objects.create(
            student=self.student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=upload_exercise,
            assigned_variant=upload_variant,
            uploaded_file=SimpleUploadedFile("report.pdf", b"content"),
            score="0.00",
            is_manually_graded=False,
        )
        upload_response = self.client.get(
            reverse("supervisor_submission_detail", args=[upload_result.id])
        )
        self.assertContains(upload_response, "Manual grading")
        self.assertIn("grading_form", upload_response.context)

    def test_manual_grading_form_prefills_existing_values_for_upload_submission(self):
        upload_exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Upload Prefill Exercise",
            order_index=3,
            exercise_type=Exercise.ExerciseType.DOCUMENT_UPLOAD,
        )
        upload_variant = ExerciseVariant.objects.create(
            exercise=upload_exercise,
            exercise_text="Upload prefill report.",
            available_points="5.00",
        )
        upload_result = Result.objects.create(
            student=self.student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=upload_exercise,
            assigned_variant=upload_variant,
            uploaded_file=SimpleUploadedFile("prefill.pdf", b"content"),
            score="2.50",
            feedback="Needs clearer explanation.",
            is_manually_graded=True,
        )

        self.client.force_login(self.supervisor)
        response = self.client.get(
            reverse("supervisor_submission_detail", args=[upload_result.id])
        )
        form = response.context["grading_form"]
        self.assertEqual(str(form["score"].value()), "2.50")
        self.assertEqual(form["feedback"].value(), "Needs clearer explanation.")

    def test_manual_grading_form_saves_for_upload_submission(self):
        upload_exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Upload Grading Exercise",
            order_index=4,
            exercise_type=Exercise.ExerciseType.DOCUMENT_UPLOAD,
        )
        upload_variant = ExerciseVariant.objects.create(
            exercise=upload_exercise,
            exercise_text="Upload grading report.",
            available_points="6.00",
        )
        upload_result = Result.objects.create(
            student=self.student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=upload_exercise,
            assigned_variant=upload_variant,
            uploaded_file=SimpleUploadedFile("grading.pdf", b"content"),
            score="0.00",
            is_manually_graded=False,
        )

        self.client.force_login(self.supervisor)
        response = self.client.post(
            reverse("supervisor_submission_detail", args=[upload_result.id]),
            {"score": "4.75", "feedback": "Good work overall."},
        )
        self.assertEqual(response.status_code, 200)
        upload_result.refresh_from_db()
        self.assertEqual(str(upload_result.score), "4.75")
        self.assertEqual(upload_result.feedback, "Good work overall.")
        self.assertTrue(upload_result.is_manually_graded)
        self.assertEqual(upload_result.graded_by, self.supervisor)
        self.assertIsNotNone(upload_result.graded_at)
