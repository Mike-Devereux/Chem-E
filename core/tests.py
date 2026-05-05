from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from django.db import IntegrityError
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
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
from .models import ArchiveBatch, Course, Exercise, ExerciseVariant, Result, Tutorial, User


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
        self.supervisor_c = User.objects.create_user(
            email="supervisor_c@unibas.ch",
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
        self.tutorial_a = Tutorial.objects.create(
            course=self.course_a,
            title="Tutorial A",
            order_index=1,
        )
        self.tutorial_b = Tutorial.objects.create(
            course=self.course_b,
            title="Tutorial B",
            order_index=1,
        )
        self.exercise_a = Exercise.objects.create(
            tutorial=self.tutorial_a,
            title="Exercise A",
            order_index=1,
            exercise_type=Exercise.ExerciseType.NUMERICAL,
        )
        self.exercise_b = Exercise.objects.create(
            tutorial=self.tutorial_b,
            title="Exercise B",
            order_index=1,
            exercise_type=Exercise.ExerciseType.DOCUMENT_UPLOAD,
        )
        self.variant_a = ExerciseVariant.objects.create(
            exercise=self.exercise_a,
            exercise_text="Variant A text",
            reference_solution="1.0000",
            absolute_tolerance="0.1000",
            available_points="2.00",
        )
        self.variant_b = ExerciseVariant.objects.create(
            exercise=self.exercise_b,
            exercise_text="Variant B text",
            available_points="3.00",
        )

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

    def test_administrator_can_view_and_edit_all_tutorials_exercises_and_variants(self):
        self.client.force_login(self.administrator)

        tutorial_list_response = self.client.get(reverse("admin:core_tutorial_changelist"))
        self.assertContains(tutorial_list_response, "Tutorial A")
        self.assertContains(tutorial_list_response, "Tutorial B")
        tutorial_change_response = self.client.get(
            reverse("admin:core_tutorial_change", args=[self.tutorial_b.id])
        )
        self.assertEqual(tutorial_change_response.status_code, 200)

        exercise_list_response = self.client.get(reverse("admin:core_exercise_changelist"))
        self.assertContains(exercise_list_response, "Exercise A")
        self.assertContains(exercise_list_response, "Exercise B")
        exercise_change_response = self.client.get(
            reverse("admin:core_exercise_change", args=[self.exercise_b.id])
        )
        self.assertEqual(exercise_change_response.status_code, 200)

        variant_list_response = self.client.get(reverse("admin:core_exercisevariant_changelist"))
        self.assertContains(variant_list_response, "Tutorial A - Exercise A")
        self.assertContains(variant_list_response, "Tutorial B - Exercise B")
        variant_change_response = self.client.get(
            reverse("admin:core_exercisevariant_change", args=[self.variant_b.id])
        )
        self.assertEqual(variant_change_response.status_code, 200)

    def test_supervisor_remains_restricted_from_other_course_tutorials_exercises_and_variants(self):
        self.client.force_login(self.supervisor_a)

        tutorial_list_response = self.client.get(reverse("admin:core_tutorial_changelist"))
        self.assertContains(tutorial_list_response, "Tutorial A")
        self.assertNotContains(tutorial_list_response, "Tutorial B")
        tutorial_change_response = self.client.get(
            reverse("admin:core_tutorial_change", args=[self.tutorial_b.id])
        )
        self.assertEqual(tutorial_change_response.status_code, 302)

        exercise_list_response = self.client.get(reverse("admin:core_exercise_changelist"))
        self.assertContains(exercise_list_response, "Exercise A")
        self.assertNotContains(exercise_list_response, "Exercise B")
        exercise_change_response = self.client.get(
            reverse("admin:core_exercise_change", args=[self.exercise_b.id])
        )
        self.assertEqual(exercise_change_response.status_code, 302)

        variant_list_response = self.client.get(reverse("admin:core_exercisevariant_changelist"))
        self.assertContains(variant_list_response, "Tutorial A - Exercise A")
        self.assertNotContains(variant_list_response, "Tutorial B - Exercise B")
        variant_change_response = self.client.get(
            reverse("admin:core_exercisevariant_change", args=[self.variant_b.id])
        )
        self.assertEqual(variant_change_response.status_code, 302)

    def test_admin_delete_confirmation_page_is_shown_for_course(self):
        self.client.force_login(self.administrator)
        response = self.client.get(reverse("admin:core_course_delete", args=[self.course_b.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Are you sure")
        self.assertContains(response, "Supervisor B Course")

    def test_administrator_can_delete_course_and_cascade_related_content(self):
        self.client.force_login(self.administrator)
        response = self.client.post(
            reverse("admin:core_course_delete", args=[self.course_b.id]),
            {"post": "yes"},
        )
        self.assertEqual(response.status_code, 302)

        self.assertFalse(Course.objects.filter(id=self.course_b.id).exists())
        self.assertFalse(Tutorial.objects.filter(id=self.tutorial_b.id).exists())
        self.assertFalse(Exercise.objects.filter(id=self.exercise_b.id).exists())
        self.assertFalse(ExerciseVariant.objects.filter(id=self.variant_b.id).exists())

        # Unrelated course data must remain untouched.
        self.assertTrue(Course.objects.filter(id=self.course_a.id).exists())
        self.assertTrue(Tutorial.objects.filter(id=self.tutorial_a.id).exists())
        self.assertTrue(Exercise.objects.filter(id=self.exercise_a.id).exists())
        self.assertTrue(ExerciseVariant.objects.filter(id=self.variant_a.id).exists())

    def test_administrator_can_delete_tutorial_and_cascade_exercises_and_variants(self):
        self.client.force_login(self.administrator)
        response = self.client.post(
            reverse("admin:core_tutorial_delete", args=[self.tutorial_b.id]),
            {"post": "yes"},
        )
        self.assertEqual(response.status_code, 302)

        self.assertFalse(Tutorial.objects.filter(id=self.tutorial_b.id).exists())
        self.assertFalse(Exercise.objects.filter(id=self.exercise_b.id).exists())
        self.assertFalse(ExerciseVariant.objects.filter(id=self.variant_b.id).exists())
        self.assertTrue(Course.objects.filter(id=self.course_b.id).exists())
        self.assertTrue(Tutorial.objects.filter(id=self.tutorial_a.id).exists())

    def test_administrator_can_delete_exercise_and_cascade_variants_only_for_that_exercise(self):
        self.client.force_login(self.administrator)
        response = self.client.post(
            reverse("admin:core_exercise_delete", args=[self.exercise_b.id]),
            {"post": "yes"},
        )
        self.assertEqual(response.status_code, 302)

        self.assertFalse(Exercise.objects.filter(id=self.exercise_b.id).exists())
        self.assertFalse(ExerciseVariant.objects.filter(id=self.variant_b.id).exists())
        self.assertTrue(Exercise.objects.filter(id=self.exercise_a.id).exists())
        self.assertTrue(ExerciseVariant.objects.filter(id=self.variant_a.id).exists())

    def test_administrator_can_delete_single_variant_without_affecting_other_content(self):
        self.client.force_login(self.administrator)
        response = self.client.post(
            reverse("admin:core_exercisevariant_delete", args=[self.variant_b.id]),
            {"post": "yes"},
        )
        self.assertEqual(response.status_code, 302)

        self.assertFalse(ExerciseVariant.objects.filter(id=self.variant_b.id).exists())
        self.assertTrue(Exercise.objects.filter(id=self.exercise_b.id).exists())
        self.assertTrue(ExerciseVariant.objects.filter(id=self.variant_a.id).exists())

    def test_shared_supervisor_can_access_shared_course_in_admin(self):
        self.course_a.supervisors.add(self.supervisor_c)
        self.client.force_login(self.supervisor_c)
        list_response = self.client.get(reverse("admin:core_course_changelist"))
        self.assertContains(list_response, "Supervisor A Course")
        change_response = self.client.get(reverse("admin:core_course_change", args=[self.course_a.id]))
        self.assertEqual(change_response.status_code, 200)

    def test_supervisor_cannot_access_user_admin(self):
        self.client.force_login(self.supervisor_a)
        response = self.client.get(reverse("admin:core_user_changelist"))
        self.assertEqual(response.status_code, 403)

    def test_administrator_can_access_user_role_field_in_admin(self):
        self.client.force_login(self.administrator)
        response = self.client.get(reverse("admin:core_user_change", args=[self.student.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="role"', html=False)

    def test_administrator_can_view_users_in_admin(self):
        self.client.force_login(self.administrator)
        response = self.client.get(reverse("admin:core_user_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.student.email)

    def test_supervisor_cannot_change_user_role_or_deactivate_user(self):
        self.client.force_login(self.supervisor_a)
        change_url = reverse("admin:core_user_change", args=[self.student.id])
        post_response = self.client.post(
            change_url,
            {
                "email": self.student.email,
                "password": self.student.password,
                "role": User.Role.SUPERVISOR,
                "_save": "Save",
            },
        )
        self.assertEqual(post_response.status_code, 403)
        self.student.refresh_from_db()
        self.assertEqual(self.student.role, User.Role.STUDENT)
        self.assertTrue(self.student.is_active)

    def test_supervisor_cannot_modify_users_via_admin_endpoints(self):
        self.client.force_login(self.supervisor_a)
        response = self.client.post(
            reverse("admin:core_user_change", args=[self.student.id]),
            {
                "email": self.student.email,
                "password": self.student.password,
                "role": User.Role.ADMINISTRATOR,
                "_save": "Save",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.student.refresh_from_db()
        self.assertEqual(self.student.role, User.Role.STUDENT)

    def test_administrator_can_access_user_active_flag_in_admin(self):
        self.client.force_login(self.administrator)
        change_url = reverse("admin:core_user_change", args=[self.student.id])
        response = self.client.get(change_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="is_active"', html=False)

    def test_administrator_can_change_user_role_and_persist(self):
        model_admin = admin.site._registry[User]
        request = RequestFactory().post("/")
        request.user = self.administrator
        target_user = User.objects.get(pk=self.student.id)

        form_class = model_admin.get_form(request, obj=target_user)
        initial_data = form_class(instance=target_user).initial
        form_data = {
            **initial_data,
            "email": target_user.email,
            "password": target_user.password,
            "role": User.Role.SUPERVISOR,
            "date_joined_0": target_user.date_joined.strftime("%Y-%m-%d"),
            "date_joined_1": target_user.date_joined.strftime("%H:%M:%S"),
            "groups": [],
            "user_permissions": [],
        }
        form = form_class(
            data=form_data,
            instance=target_user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        updated_user = form.save(commit=False)
        model_admin.save_model(request, updated_user, form, change=True)
        form.save_m2m()

        target_user.refresh_from_db()
        self.assertEqual(target_user.role, User.Role.SUPERVISOR)

    def test_administrator_sees_admin_password_change_link_for_user(self):
        self.client.force_login(self.administrator)
        response = self.client.get(reverse("admin:core_user_change", args=[self.student.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "../password/")

    def test_user_can_request_password_reset_via_email(self):
        response = self.client.post(
            reverse("password_reset"),
            {"email": self.student.email},
        )
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.student.email, mail.outbox[0].to)


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
        self.assertTrue(result.is_manually_graded)
        self.assertIsNotNone(result.graded_at)
        self.assertIsNone(result.graded_by)
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
        self.assertTrue(second_result.is_manually_graded)
        self.assertIsNotNone(second_result.graded_at)

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
        self.shared_supervisor = User.objects.create_user(
            email="shared_supervisor_submissions_view@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.unrelated_supervisor = User.objects.create_user(
            email="unrelated_supervisor_submissions_view@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.administrator = User.objects.create_user(
            email="admin_submissions_view@unibas.ch",
            password="test-password",
            role=User.Role.ADMINISTRATOR,
        )
        self.course = Course.objects.create(title="Submissions Course", created_by=self.supervisor)
        self.course.supervisors.add(self.shared_supervisor)
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
        self.assertContains(response, "Graded")
        self.assertContains(response, "3.00")
        result = Result.objects.get(student=self.student, exercise=self.exercise, is_archived=False)
        self.assertContains(
            response,
            reverse("supervisor_submission_detail", args=[result.id]),
        )

    def test_administrator_can_access_supervisor_submissions_page(self):
        self.client.force_login(self.administrator)
        response = self.client.get(
            reverse("supervisor_exercise_submissions", args=[self.exercise.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_shared_supervisor_can_access_supervisor_submissions_page(self):
        self.client.force_login(self.shared_supervisor)
        response = self.client.get(
            reverse("supervisor_exercise_submissions", args=[self.exercise.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_unrelated_supervisor_cannot_access_supervisor_submissions_page(self):
        self.client.force_login(self.unrelated_supervisor)
        response = self.client.get(
            reverse("supervisor_exercise_submissions", args=[self.exercise.id])
        )
        self.assertEqual(response.status_code, 403)

    def test_supervisor_not_in_course_supervisors_is_denied_even_if_creator_field_matches(self):
        self.course.supervisors.remove(self.supervisor)
        self.client.force_login(self.supervisor)
        response = self.client.get(
            reverse("supervisor_exercise_submissions", args=[self.exercise.id])
        )
        self.assertEqual(response.status_code, 403)

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
        self.assertContains(response, "Status: Graded")
        self.assertContains(response, "Submitted numerical value: 1.0000")
        self.assertContains(response, "Reference solution: 1.0000")
        self.assertContains(response, "Tolerance: 0.1000")
        self.assertContains(response, "Correctness: True")

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

    def test_shared_supervisor_can_access_supervisor_submission_detail(self):
        result = Result.objects.get(student=self.student, exercise=self.exercise, is_archived=False)
        self.client.force_login(self.shared_supervisor)
        response = self.client.get(
            reverse("supervisor_submission_detail", args=[result.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_unrelated_supervisor_cannot_access_supervisor_submission_detail(self):
        result = Result.objects.get(student=self.student, exercise=self.exercise, is_archived=False)
        self.client.force_login(self.unrelated_supervisor)
        response = self.client.get(
            reverse("supervisor_submission_detail", args=[result.id])
        )
        self.assertEqual(response.status_code, 403)

    def test_unrelated_supervisor_cannot_submit_grading_form(self):
        upload_exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Upload Unauthorized Grading Exercise",
            order_index=8,
            exercise_type=Exercise.ExerciseType.DOCUMENT_UPLOAD,
        )
        upload_variant = ExerciseVariant.objects.create(
            exercise=upload_exercise,
            exercise_text="Upload unauthorized grading report.",
            available_points="4.00",
        )
        upload_result = Result.objects.create(
            student=self.student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=upload_exercise,
            assigned_variant=upload_variant,
            uploaded_file=SimpleUploadedFile("unauthorized.pdf", b"content"),
            is_manually_graded=False,
            score="0.00",
        )

        self.client.force_login(self.unrelated_supervisor)
        response = self.client.post(
            reverse("supervisor_submission_detail", args=[upload_result.id]),
            {"score": "3.00", "feedback": "Unauthorized grading attempt."},
        )
        self.assertEqual(response.status_code, 403)
        upload_result.refresh_from_db()
        self.assertFalse(upload_result.is_manually_graded)


class SupervisorGradingWorkflowTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email="workflow_student@unibas.ch",
            password="test-password",
            role=User.Role.STUDENT,
        )
        self.course_owner = User.objects.create_user(
            email="workflow_owner@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.shared_supervisor = User.objects.create_user(
            email="workflow_shared@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        # Keep compatibility with existing tests that use self.supervisor naming.
        self.supervisor = self.shared_supervisor
        self.unrelated_supervisor = User.objects.create_user(
            email="workflow_unrelated@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.administrator = User.objects.create_user(
            email="workflow_admin@unibas.ch",
            password="test-password",
            role=User.Role.ADMINISTRATOR,
        )

        self.course = Course.objects.create(
            title="Workflow Course",
            created_by=self.course_owner,
        )
        self.course.supervisors.add(self.shared_supervisor)
        self.tutorial = Tutorial.objects.create(
            course=self.course,
            title="Workflow Tutorial",
            order_index=1,
        )
        self.exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Workflow Upload Exercise",
            order_index=1,
            exercise_type=Exercise.ExerciseType.DOCUMENT_UPLOAD,
        )
        self.variant = ExerciseVariant.objects.create(
            exercise=self.exercise,
            exercise_text="Upload workflow report",
            available_points="5.00",
        )
        self.result = Result.objects.create(
            student=self.student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=self.exercise,
            assigned_variant=self.variant,
            uploaded_file=SimpleUploadedFile("workflow.pdf", b"workflow-content"),
            score="0.00",
            feedback="",
            is_manually_graded=False,
        )

    def test_shared_supervisor_can_view_submissions_and_grade(self):
        self.client.force_login(self.shared_supervisor)

        list_response = self.client.get(
            reverse("supervisor_exercise_submissions", args=[self.exercise.id])
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, self.student.email)

        grade_response = self.client.post(
            reverse("supervisor_submission_detail", args=[self.result.id]),
            {"score": "4.25", "feedback": "Solid submission."},
        )
        self.assertEqual(grade_response.status_code, 200)

        self.result.refresh_from_db()
        self.assertEqual(str(self.result.score), "4.25")
        self.assertEqual(self.result.feedback, "Solid submission.")
        self.assertTrue(self.result.is_manually_graded)
        self.assertEqual(self.result.graded_by, self.shared_supervisor)
        self.assertIsNotNone(self.result.graded_at)

    def test_student_cannot_access_supervisor_pages(self):
        self.client.force_login(self.student)
        list_response = self.client.get(
            reverse("supervisor_exercise_submissions", args=[self.exercise.id])
        )
        detail_response = self.client.get(
            reverse("supervisor_submission_detail", args=[self.result.id])
        )
        self.assertEqual(list_response.status_code, 403)
        self.assertEqual(detail_response.status_code, 403)

    def test_unrelated_supervisor_cannot_access_course_submissions(self):
        self.client.force_login(self.unrelated_supervisor)
        list_response = self.client.get(
            reverse("supervisor_exercise_submissions", args=[self.exercise.id])
        )
        detail_response = self.client.get(
            reverse("supervisor_submission_detail", args=[self.result.id])
        )
        self.assertEqual(list_response.status_code, 403)
        self.assertEqual(detail_response.status_code, 403)

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
        numerical_exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Workflow Numerical Exercise",
            order_index=9,
            exercise_type=Exercise.ExerciseType.NUMERICAL,
        )
        numerical_variant = ExerciseVariant.objects.create(
            exercise=numerical_exercise,
            exercise_text="Workflow numerical variant.",
            reference_solution="2.0000",
            absolute_tolerance="0.1000",
            available_points="2.00",
        )
        numerical_result = Result.objects.create(
            student=self.student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=numerical_exercise,
            assigned_variant=numerical_variant,
            submitted_numerical_value="2.0000",
            score="2.00",
            is_correct=True,
            is_manually_graded=True,
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
        self.assertContains(response, "Status: Graded")
        self.assertEqual(
            Result.objects.filter(student=self.student, exercise=upload_exercise, is_archived=False).count(),
            1,
        )
        upload_result.refresh_from_db()
        self.assertEqual(str(upload_result.score), "4.75")
        self.assertEqual(upload_result.feedback, "Good work overall.")
        self.assertTrue(upload_result.is_manually_graded)
        self.assertEqual(upload_result.graded_by, self.supervisor)
        self.assertIsNotNone(upload_result.graded_at)

    def test_submissions_list_shows_ungraded_and_graded_status(self):
        upload_exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Upload Status Exercise",
            order_index=6,
            exercise_type=Exercise.ExerciseType.DOCUMENT_UPLOAD,
        )
        upload_variant = ExerciseVariant.objects.create(
            exercise=upload_exercise,
            exercise_text="Upload status report.",
            available_points="3.00",
        )
        upload_result = Result.objects.create(
            student=self.student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=upload_exercise,
            assigned_variant=upload_variant,
            uploaded_file=SimpleUploadedFile("status.pdf", b"content"),
            is_manually_graded=False,
            score="0.00",
        )

        self.client.force_login(self.supervisor)
        ungraded_response = self.client.get(
            reverse("supervisor_exercise_submissions", args=[upload_exercise.id])
        )
        self.assertContains(ungraded_response, "Ungraded")

        upload_result.is_manually_graded = True
        upload_result.score = "2.50"
        upload_result.save(update_fields=["is_manually_graded", "score"])
        graded_response = self.client.get(
            reverse("supervisor_exercise_submissions", args=[upload_exercise.id])
        )
        self.assertContains(graded_response, "Graded")

    def test_submissions_list_filters_graded_vs_ungraded(self):
        upload_exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Upload Filter Exercise",
            order_index=7,
            exercise_type=Exercise.ExerciseType.DOCUMENT_UPLOAD,
        )
        upload_variant = ExerciseVariant.objects.create(
            exercise=upload_exercise,
            exercise_text="Upload filter report.",
            available_points="3.00",
        )
        graded_student = User.objects.create_user(
            email="graded_filter_student@unibas.ch",
            password="test-password",
            role=User.Role.STUDENT,
        )
        ungraded_student = User.objects.create_user(
            email="ungraded_filter_student@unibas.ch",
            password="test-password",
            role=User.Role.STUDENT,
        )
        Result.objects.create(
            student=graded_student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=upload_exercise,
            assigned_variant=upload_variant,
            uploaded_file=SimpleUploadedFile("graded-filter.pdf", b"content"),
            is_manually_graded=True,
            score="2.00",
        )
        Result.objects.create(
            student=ungraded_student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=upload_exercise,
            assigned_variant=upload_variant,
            uploaded_file=SimpleUploadedFile("ungraded-filter.pdf", b"content"),
            is_manually_graded=False,
            score="0.00",
        )

        self.client.force_login(self.supervisor)
        graded_response = self.client.get(
            reverse("supervisor_exercise_submissions", args=[upload_exercise.id]) + "?status=graded"
        )
        self.assertContains(graded_response, "<td>graded_filter_student@unibas.ch</td>", html=True)
        self.assertNotContains(
            graded_response,
            "<td>ungraded_filter_student@unibas.ch</td>",
            html=True,
        )

        ungraded_response = self.client.get(
            reverse("supervisor_exercise_submissions", args=[upload_exercise.id]) + "?status=ungraded"
        )
        self.assertContains(
            ungraded_response,
            "<td>ungraded_filter_student@unibas.ch</td>",
            html=True,
        )
        self.assertNotContains(
            ungraded_response,
            "<td>graded_filter_student@unibas.ch</td>",
            html=True,
        )

    def test_student_cannot_submit_manual_grading_form(self):
        upload_exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Upload Student Grading Exercise",
            order_index=5,
            exercise_type=Exercise.ExerciseType.DOCUMENT_UPLOAD,
        )
        upload_variant = ExerciseVariant.objects.create(
            exercise=upload_exercise,
            exercise_text="Upload student grading report.",
            available_points="6.00",
        )
        upload_result = Result.objects.create(
            student=self.student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=upload_exercise,
            assigned_variant=upload_variant,
            uploaded_file=SimpleUploadedFile("student-grade.pdf", b"content"),
            score="0.00",
            is_manually_graded=False,
        )

        self.client.force_login(self.student)
        response = self.client.post(
            reverse("supervisor_submission_detail", args=[upload_result.id]),
            {"score": "5.00", "feedback": "Attempted unauthorized grade."},
        )
        self.assertEqual(response.status_code, 403)
        upload_result.refresh_from_db()
        self.assertEqual(str(upload_result.score), "0.00")
        self.assertFalse(upload_result.is_manually_graded)
        self.assertIsNone(upload_result.graded_by)


class SupervisorCourseSummaryAccessTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email="summary_student@unibas.ch",
            password="test-password",
            role=User.Role.STUDENT,
        )
        self.course_owner = User.objects.create_user(
            email="summary_owner@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.shared_supervisor = User.objects.create_user(
            email="summary_shared_supervisor@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.unrelated_supervisor = User.objects.create_user(
            email="summary_unrelated_supervisor@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.administrator = User.objects.create_user(
            email="summary_admin@unibas.ch",
            password="test-password",
            role=User.Role.ADMINISTRATOR,
        )
        self.course = Course.objects.create(
            title="Summary Access Course",
            created_by=self.course_owner,
        )
        self.course.supervisors.add(self.shared_supervisor)
        self.tutorial = Tutorial.objects.create(
            course=self.course,
            title="Summary Tutorial",
            order_index=1,
        )
        self.exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Summary Exercise",
            order_index=1,
            exercise_type=Exercise.ExerciseType.NUMERICAL,
            is_active=True,
        )
        self.variant = ExerciseVariant.objects.create(
            exercise=self.exercise,
            exercise_text="Summary variant",
            reference_solution="1.0000",
            absolute_tolerance="0.1000",
            available_points="1.00",
        )
        Result.objects.create(
            student=self.student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=self.exercise,
            assigned_variant=self.variant,
            submitted_numerical_value="1.0000",
            is_correct=True,
            score="1.00",
            is_manually_graded=True,
        )

    def test_course_owner_supervisor_can_access_course_summary(self):
        self.client.force_login(self.course_owner)
        response = self.client.get(reverse("supervisor_course_summary", args=[self.course.id]))
        self.assertEqual(response.status_code, 200)

    def test_shared_supervisor_can_access_course_summary(self):
        self.client.force_login(self.shared_supervisor)
        response = self.client.get(reverse("supervisor_course_summary", args=[self.course.id]))
        self.assertEqual(response.status_code, 200)

    def test_unrelated_supervisor_cannot_access_course_summary(self):
        self.client.force_login(self.unrelated_supervisor)
        response = self.client.get(reverse("supervisor_course_summary", args=[self.course.id]))
        self.assertEqual(response.status_code, 403)

    def test_administrator_can_access_course_summary(self):
        self.client.force_login(self.administrator)
        response = self.client.get(reverse("supervisor_course_summary", args=[self.course.id]))
        self.assertEqual(response.status_code, 200)

    def test_student_cannot_access_course_summary(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("supervisor_course_summary", args=[self.course.id]))
        self.assertEqual(response.status_code, 403)


class SupervisorCourseSummaryViewTests(TestCase):
    def setUp(self):
        self.owner_supervisor = User.objects.create_user(
            email="summary_owner_view@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.shared_supervisor = User.objects.create_user(
            email="summary_shared_view@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.unrelated_supervisor = User.objects.create_user(
            email="summary_unrelated_view@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.administrator = User.objects.create_user(
            email="summary_admin_view@unibas.ch",
            password="test-password",
            role=User.Role.ADMINISTRATOR,
        )
        self.student_a = User.objects.create_user(
            email="summary_student_a@unibas.ch",
            password="test-password",
            role=User.Role.STUDENT,
        )
        self.student_b = User.objects.create_user(
            email="summary_student_b@unibas.ch",
            password="test-password",
            role=User.Role.STUDENT,
        )

        self.course = Course.objects.create(
            title="Summary Matrix Course",
            created_by=self.owner_supervisor,
        )
        self.course.supervisors.add(self.shared_supervisor)

        self.tutorial_1 = Tutorial.objects.create(
            course=self.course,
            title="Tutorial 1",
            order_index=1,
        )
        self.tutorial_2 = Tutorial.objects.create(
            course=self.course,
            title="Tutorial 2",
            order_index=2,
        )

        self.exercise_1 = Exercise.objects.create(
            tutorial=self.tutorial_1,
            title="Exercise 1",
            order_index=1,
            exercise_type=Exercise.ExerciseType.NUMERICAL,
            is_active=True,
        )
        self.exercise_2 = Exercise.objects.create(
            tutorial=self.tutorial_1,
            title="Exercise 2",
            order_index=2,
            exercise_type=Exercise.ExerciseType.DOCUMENT_UPLOAD,
            is_active=True,
        )
        self.exercise_3 = Exercise.objects.create(
            tutorial=self.tutorial_2,
            title="Exercise 3",
            order_index=1,
            exercise_type=Exercise.ExerciseType.NUMERICAL,
            is_active=True,
        )

        self.variant_1 = ExerciseVariant.objects.create(
            exercise=self.exercise_1,
            exercise_text="Variant 1",
            reference_solution="1.0000",
            absolute_tolerance="0.1000",
            available_points="5.00",
        )
        self.variant_2 = ExerciseVariant.objects.create(
            exercise=self.exercise_2,
            exercise_text="Variant 2",
            available_points="6.00",
        )
        self.variant_3 = ExerciseVariant.objects.create(
            exercise=self.exercise_3,
            exercise_text="Variant 3",
            reference_solution="2.0000",
            absolute_tolerance="0.1000",
            available_points="7.00",
        )

        Result.objects.create(
            student=self.student_a,
            course=self.course,
            tutorial=self.tutorial_1,
            exercise=self.exercise_1,
            assigned_variant=self.variant_1,
            submitted_numerical_value="1.0000",
            is_correct=True,
            score="5.00",
            is_manually_graded=True,
        )
        Result.objects.create(
            student=self.student_a,
            course=self.course,
            tutorial=self.tutorial_1,
            exercise=self.exercise_2,
            assigned_variant=self.variant_2,
            uploaded_file=SimpleUploadedFile("pending.pdf", b"pending"),
            score="0.00",
            is_manually_graded=False,
        )
        Result.objects.create(
            student=self.student_a,
            course=self.course,
            tutorial=self.tutorial_2,
            exercise=self.exercise_3,
            assigned_variant=self.variant_3,
            submitted_numerical_value="2.0000",
            is_correct=True,
            score="7.00",
            is_manually_graded=True,
        )
        Result.objects.create(
            student=self.student_b,
            course=self.course,
            tutorial=self.tutorial_1,
            exercise=self.exercise_1,
            assigned_variant=self.variant_1,
            submitted_numerical_value="0.9500",
            is_correct=True,
            score="4.00",
            is_manually_graded=True,
        )

    def test_summary_shows_expected_scores_and_missing_cells_in_context(self):
        self.client.force_login(self.owner_supervisor)
        response = self.client.get(reverse("supervisor_course_summary", args=[self.course.id]))
        self.assertEqual(response.status_code, 200)

        exercises = response.context["exercises"]
        exercise_ids = [exercise.id for exercise in exercises]
        self.assertEqual(exercise_ids, [self.exercise_1.id, self.exercise_2.id, self.exercise_3.id])

        rows_by_student_id = {
            row["student"].id: row["cells"] for row in response.context["summary_rows"]
        }
        student_a_cells = rows_by_student_id[self.student_a.id]
        student_b_cells = rows_by_student_id[self.student_b.id]

        self.assertEqual(str(student_a_cells[0].score), "5.00")
        self.assertFalse(student_a_cells[1].is_manually_graded)
        self.assertEqual(str(student_a_cells[2].score), "7.00")

        self.assertEqual(str(student_b_cells[0].score), "4.00")
        self.assertIsNone(student_b_cells[1])
        self.assertIsNone(student_b_cells[2])

        self.assertContains(response, "5.00")
        self.assertContains(response, "4.00")
        self.assertContains(response, "7.00")
        self.assertContains(response, "Ungraded")

    def test_filtering_by_tutorial_limits_exercises_and_results(self):
        self.client.force_login(self.owner_supervisor)
        response = self.client.get(
            reverse("supervisor_course_summary", args=[self.course.id]),
            {"tutorial_id": str(self.tutorial_1.id)},
        )
        self.assertEqual(response.status_code, 200)

        exercise_ids = [exercise.id for exercise in response.context["exercises"]]
        self.assertEqual(exercise_ids, [self.exercise_1.id, self.exercise_2.id])

        rows_by_student_id = {
            row["student"].id: row["cells"] for row in response.context["summary_rows"]
        }
        self.assertEqual(len(rows_by_student_id[self.student_a.id]), 2)
        self.assertEqual(len(rows_by_student_id[self.student_b.id]), 2)
        self.assertEqual(str(rows_by_student_id[self.student_a.id][0].score), "5.00")
        self.assertFalse(rows_by_student_id[self.student_a.id][1].is_manually_graded)

    def test_filtering_by_student_shows_only_selected_student_row(self):
        self.client.force_login(self.owner_supervisor)
        response = self.client.get(
            reverse("supervisor_course_summary", args=[self.course.id]),
            {"student_id": str(self.student_b.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["summary_rows"]), 1)
        self.assertEqual(response.context["summary_rows"][0]["student"].id, self.student_b.id)
        self.assertContains(response, f"<th>{self.student_b.email}</th>", html=True)
        self.assertNotContains(response, f"<th>{self.student_a.email}</th>", html=True)

    def test_access_control_for_summary_endpoint(self):
        summary_url = reverse("supervisor_course_summary", args=[self.course.id])

        self.client.force_login(self.owner_supervisor)
        self.assertEqual(self.client.get(summary_url).status_code, 200)

        self.client.force_login(self.shared_supervisor)
        self.assertEqual(self.client.get(summary_url).status_code, 200)

        self.client.force_login(self.unrelated_supervisor)
        self.assertEqual(self.client.get(summary_url).status_code, 403)

        self.client.force_login(self.administrator)
        self.assertEqual(self.client.get(summary_url).status_code, 200)

        self.client.force_login(self.student_a)
        self.assertEqual(self.client.get(summary_url).status_code, 403)


class SupervisorCourseArchiveResultsViewTests(TestCase):
    def setUp(self):
        self.owner_supervisor = User.objects.create_user(
            email="archive_owner@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.shared_supervisor = User.objects.create_user(
            email="archive_shared@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.unrelated_supervisor = User.objects.create_user(
            email="archive_unrelated@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.administrator = User.objects.create_user(
            email="archive_admin@unibas.ch",
            password="test-password",
            role=User.Role.ADMINISTRATOR,
        )
        self.student = User.objects.create_user(
            email="archive_student@unibas.ch",
            password="test-password",
            role=User.Role.STUDENT,
        )
        self.other_student = User.objects.create_user(
            email="archive_other_student@unibas.ch",
            password="test-password",
            role=User.Role.STUDENT,
        )
        self.course = Course.objects.create(
            title="Archive Course",
            created_by=self.owner_supervisor,
        )
        self.course.supervisors.add(self.shared_supervisor)
        self.other_course = Course.objects.create(
            title="Archive Other Course",
            created_by=self.administrator,
        )
        self.tutorial = Tutorial.objects.create(course=self.course, title="Archive Tutorial", order_index=1)
        self.other_tutorial = Tutorial.objects.create(
            course=self.other_course,
            title="Archive Other Tutorial",
            order_index=1,
        )
        self.exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Archive Exercise",
            order_index=1,
            exercise_type=Exercise.ExerciseType.DOCUMENT_UPLOAD,
        )
        self.numerical_exercise = Exercise.objects.create(
            tutorial=self.tutorial,
            title="Archive Numerical Exercise",
            order_index=2,
            exercise_type=Exercise.ExerciseType.NUMERICAL,
        )
        self.other_exercise = Exercise.objects.create(
            tutorial=self.other_tutorial,
            title="Archive Other Exercise",
            order_index=1,
            exercise_type=Exercise.ExerciseType.NUMERICAL,
        )
        self.variant = ExerciseVariant.objects.create(
            exercise=self.exercise,
            exercise_text="Archive variant",
            available_points="1.00",
        )
        self.other_variant = ExerciseVariant.objects.create(
            exercise=self.other_exercise,
            exercise_text="Archive other variant",
            reference_solution="1.0000",
            absolute_tolerance="0.1000",
            available_points="1.00",
        )
        self.numerical_variant = ExerciseVariant.objects.create(
            exercise=self.numerical_exercise,
            exercise_text="Archive numerical variant",
            reference_solution="2.0000",
            absolute_tolerance="0.1000",
            available_points="2.00",
        )
        self.current_result = Result.objects.create(
            student=self.student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=self.exercise,
            assigned_variant=self.variant,
            uploaded_file=SimpleUploadedFile("archive-target.pdf", b"archive target"),
            is_manually_graded=False,
            is_archived=False,
        )
        self.current_numerical_result = Result.objects.create(
            student=self.other_student,
            course=self.course,
            tutorial=self.tutorial,
            exercise=self.numerical_exercise,
            assigned_variant=self.numerical_variant,
            submitted_numerical_value="2.0000",
            is_correct=True,
            score="2.00",
            is_manually_graded=True,
            is_archived=False,
        )
        self.other_course_result = Result.objects.create(
            student=self.other_student,
            course=self.other_course,
            tutorial=self.other_tutorial,
            exercise=self.other_exercise,
            assigned_variant=self.other_variant,
            submitted_numerical_value="1.0000",
            is_correct=True,
            score="1.00",
            is_manually_graded=True,
            is_archived=False,
        )

    def test_get_shows_confirmation_with_current_result_count(self):
        self.client.force_login(self.owner_supervisor)
        response = self.client.get(
            reverse("supervisor_course_archive_results", args=[self.course.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Current (unarchived) results in this course: 2")
        self.assertContains(response, 'name="note"', html=False)

    def test_post_archives_only_current_results_for_selected_course(self):
        self.client.force_login(self.owner_supervisor)
        response = self.client.post(
            reverse("supervisor_course_archive_results", args=[self.course.id]),
            {"note": "Spring 2026 Tutorial 1"},
        )
        self.assertRedirects(
            response,
            reverse("supervisor_course_summary", args=[self.course.id]),
        )

        self.assertEqual(ArchiveBatch.objects.filter(course=self.course).count(), 1)
        batch = ArchiveBatch.objects.get(course=self.course)
        self.current_result.refresh_from_db()
        self.current_numerical_result.refresh_from_db()
        self.other_course_result.refresh_from_db()

        self.assertEqual(self.current_result.archive_batch_id, batch.id)
        self.assertEqual(self.current_numerical_result.archive_batch_id, batch.id)
        self.assertEqual(batch.note, "Spring 2026 Tutorial 1")
        self.assertTrue(self.current_result.is_archived)
        self.assertTrue(self.current_numerical_result.is_archived)
        self.assertTrue(bool(self.current_result.uploaded_file))
        self.assertIsNone(self.other_course_result.archive_batch)
        self.assertFalse(self.other_course_result.is_archived)

    def test_access_control_for_archive_action(self):
        archive_url = reverse("supervisor_course_archive_results", args=[self.course.id])

        self.client.force_login(self.shared_supervisor)
        self.assertEqual(self.client.get(archive_url).status_code, 200)

        self.client.force_login(self.administrator)
        self.assertEqual(self.client.get(archive_url).status_code, 200)

        self.client.force_login(self.unrelated_supervisor)
        self.assertEqual(self.client.get(archive_url).status_code, 403)

        self.client.force_login(self.student)
        self.assertEqual(self.client.get(archive_url).status_code, 403)

    def test_supervisor_can_archive_current_course_results(self):
        self.client.force_login(self.owner_supervisor)
        response = self.client.post(
            reverse("supervisor_course_archive_results", args=[self.course.id]),
            {"note": "End of term"},
        )
        self.assertRedirects(response, reverse("supervisor_course_summary", args=[self.course.id]))
        self.assertEqual(ArchiveBatch.objects.filter(course=self.course).count(), 1)
        self.assertEqual(Result.objects.filter(course=self.course, archive_batch__isnull=True).count(), 0)

    def test_archives_page_lists_batches_with_metadata_and_detail_link(self):
        batch = ArchiveBatch.objects.create(
            course=self.course,
            created_by=self.owner_supervisor,
            note="Spring 2026 Tutorial 1",
        )
        self.current_result.archive_batch = batch
        self.current_result.is_archived = True
        self.current_result.save(update_fields=["archive_batch", "is_archived"])

        self.client.force_login(self.owner_supervisor)
        response = self.client.get(reverse("supervisor_course_archives", args=[self.course.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Spring 2026 Tutorial 1")
        self.assertContains(response, self.owner_supervisor.email)
        self.assertContains(response, "<td>1</td>", html=True)
        self.assertContains(
            response,
            reverse("supervisor_course_archive_batch_detail", args=[batch.id]),
        )

    def test_archives_page_access_control(self):
        archives_url = reverse("supervisor_course_archives", args=[self.course.id])

        self.client.force_login(self.shared_supervisor)
        self.assertEqual(self.client.get(archives_url).status_code, 200)

        self.client.force_login(self.administrator)
        self.assertEqual(self.client.get(archives_url).status_code, 200)

        self.client.force_login(self.unrelated_supervisor)
        self.assertEqual(self.client.get(archives_url).status_code, 403)

        self.client.force_login(self.student)
        self.assertEqual(self.client.get(archives_url).status_code, 403)

    def test_archived_results_disappear_from_current_summary_and_submissions_views(self):
        self.client.force_login(self.owner_supervisor)
        self.client.post(reverse("supervisor_course_archive_results", args=[self.course.id]))

        summary_response = self.client.get(reverse("supervisor_course_summary", args=[self.course.id]))
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(len(summary_response.context["results"]), 0)
        self.assertContains(summary_response, "No submission")

        submissions_response = self.client.get(
            reverse("supervisor_exercise_submissions", args=[self.exercise.id])
        )
        self.assertEqual(submissions_response.status_code, 200)
        self.assertContains(submissions_response, "No submissions yet.")

    def test_archived_results_appear_in_archive_browsing(self):
        self.client.force_login(self.owner_supervisor)
        self.client.post(
            reverse("supervisor_course_archive_results", args=[self.course.id]),
            {"note": "Spring archive"},
        )
        batch = ArchiveBatch.objects.get(course=self.course)

        archives_response = self.client.get(reverse("supervisor_course_archives", args=[self.course.id]))
        self.assertEqual(archives_response.status_code, 200)
        self.assertContains(archives_response, "Spring archive")
        self.assertContains(archives_response, "<td>2</td>", html=True)

        detail_response = self.client.get(
            reverse("supervisor_course_archive_batch_detail", args=[batch.id])
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, self.student.email)
        self.assertContains(detail_response, self.other_student.email)

    def test_archive_batch_detail_page_access_and_course_scoping(self):
        batch = ArchiveBatch.objects.create(
            course=self.course,
            created_by=self.owner_supervisor,
            note="Scoped batch",
        )
        self.current_result.archive_batch = batch
        self.current_result.is_archived = True
        self.current_result.save(update_fields=["archive_batch", "is_archived"])

        detail_url = reverse(
            "supervisor_course_archive_batch_detail",
            args=[batch.id],
        )

        self.client.force_login(self.owner_supervisor)
        detail_response = self.client.get(detail_url)
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Scoped batch")
        self.assertContains(detail_response, self.student.email)
        self.assertContains(
            detail_response,
            reverse("supervisor_archived_submission_file_download", args=[self.current_result.id]),
        )

        self.client.force_login(self.unrelated_supervisor)
        self.assertEqual(self.client.get(detail_url).status_code, 403)

    def test_archived_result_data_and_uploaded_file_reference_are_preserved(self):
        original_uploaded_name = self.current_result.uploaded_file.name
        original_score = str(self.current_numerical_result.score)
        original_submitted_at = self.current_numerical_result.submitted_at

        self.client.force_login(self.owner_supervisor)
        self.client.post(
            reverse("supervisor_course_archive_results", args=[self.course.id]),
            {"note": "Preservation batch"},
        )

        self.current_result.refresh_from_db()
        self.current_numerical_result.refresh_from_db()

        self.assertIsNotNone(self.current_result.archive_batch_id)
        self.assertEqual(self.current_result.uploaded_file.name, original_uploaded_name)
        self.assertEqual(str(self.current_numerical_result.score), original_score)
        self.assertEqual(self.current_numerical_result.submitted_at, original_submitted_at)
        self.assertEqual(str(self.current_numerical_result.submitted_numerical_value), "2.0000")

    def test_archived_file_download_is_course_access_controlled(self):
        batch = ArchiveBatch.objects.create(
            course=self.course,
            created_by=self.owner_supervisor,
            note="File batch",
        )
        self.current_result.archive_batch = batch
        self.current_result.is_archived = True
        self.current_result.save(update_fields=["archive_batch", "is_archived"])

        download_url = reverse(
            "supervisor_archived_submission_file_download",
            args=[self.current_result.id],
        )

        self.client.force_login(self.owner_supervisor)
        ok_response = self.client.get(download_url)
        self.assertEqual(ok_response.status_code, 200)

        self.client.force_login(self.unrelated_supervisor)
        denied_response = self.client.get(download_url)
        self.assertEqual(denied_response.status_code, 403)

    def test_unrelated_supervisor_cannot_archive_or_view_other_course_archives(self):
        self.client.force_login(self.unrelated_supervisor)
        archive_post_response = self.client.post(
            reverse("supervisor_course_archive_results", args=[self.course.id])
        )
        self.assertEqual(archive_post_response.status_code, 403)
        archives_get_response = self.client.get(
            reverse("supervisor_course_archives", args=[self.course.id])
        )
        self.assertEqual(archives_get_response.status_code, 403)

    def test_administrator_can_archive_and_view_all_course_archives(self):
        self.client.force_login(self.administrator)
        archive_post_response = self.client.post(
            reverse("supervisor_course_archive_results", args=[self.course.id]),
            {"note": "Admin archive"},
        )
        self.assertRedirects(
            archive_post_response,
            reverse("supervisor_course_summary", args=[self.course.id]),
        )
        batch = ArchiveBatch.objects.get(course=self.course)

        archives_response = self.client.get(reverse("supervisor_course_archives", args=[self.course.id]))
        self.assertEqual(archives_response.status_code, 200)
        self.assertContains(archives_response, "Admin archive")

        detail_response = self.client.get(
            reverse("supervisor_course_archive_batch_detail", args=[batch.id])
        )
        self.assertEqual(detail_response.status_code, 200)

    def test_post_does_not_create_empty_archive_batch_when_no_current_results(self):
        batch = ArchiveBatch.objects.create(
            course=self.course,
            created_by=self.owner_supervisor,
            note="Already archived",
        )
        Result.objects.filter(course=self.course, archive_batch__isnull=True).update(
            archive_batch=batch,
            is_archived=True,
        )
        existing_count = ArchiveBatch.objects.filter(course=self.course).count()

        self.client.force_login(self.owner_supervisor)
        response = self.client.post(
            reverse("supervisor_course_archive_results", args=[self.course.id]),
            {"note": "Should not create"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No current results to archive for this course.")
        self.assertEqual(ArchiveBatch.objects.filter(course=self.course).count(), existing_count)

    def test_already_archived_results_are_not_rearchived(self):
        old_batch = ArchiveBatch.objects.create(
            course=self.course,
            created_by=self.owner_supervisor,
            note="Old archive",
        )
        self.current_result.archive_batch = old_batch
        self.current_result.is_archived = True
        self.current_result.save(update_fields=["archive_batch", "is_archived"])

        self.client.force_login(self.owner_supervisor)
        self.client.post(reverse("supervisor_course_archive_results", args=[self.course.id]))
        self.current_result.refresh_from_db()
        self.current_numerical_result.refresh_from_db()

        self.assertEqual(self.current_result.archive_batch_id, old_batch.id)
        self.assertIsNotNone(self.current_numerical_result.archive_batch_id)
        self.assertNotEqual(self.current_numerical_result.archive_batch_id, old_batch.id)


class SupervisorLandingAndSummaryListViewTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email="landing_student@unibas.ch",
            password="test-password",
            role=User.Role.STUDENT,
        )
        self.supervisor_owner = User.objects.create_user(
            email="landing_owner@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.shared_supervisor = User.objects.create_user(
            email="landing_shared@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.unrelated_supervisor = User.objects.create_user(
            email="landing_unrelated@unibas.ch",
            password="test-password",
            role=User.Role.SUPERVISOR,
        )
        self.administrator = User.objects.create_user(
            email="landing_admin@unibas.ch",
            password="test-password",
            role=User.Role.ADMINISTRATOR,
        )
        self.course_a = Course.objects.create(
            title="Landing Course A",
            created_by=self.supervisor_owner,
        )
        self.course_b = Course.objects.create(
            title="Landing Course B",
            created_by=self.administrator,
        )
        self.course_a.supervisors.add(self.shared_supervisor)

    def test_student_cannot_access_supervisor_landing_or_summary_list(self):
        self.client.force_login(self.student)
        landing_response = self.client.get(reverse("supervisor_landing"))
        summary_list_response = self.client.get(reverse("supervisor_course_summary_list"))
        self.assertEqual(landing_response.status_code, 403)
        self.assertEqual(summary_list_response.status_code, 403)

    def test_supervisor_landing_contains_required_navigation_links(self):
        self.client.force_login(self.supervisor_owner)
        response = self.client.get(reverse("supervisor_landing"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("home"))
        self.assertContains(response, reverse("supervisor_course_summary_list"))
        self.assertContains(response, "/admin/")

    def test_supervisor_pages_show_only_accessible_courses_for_supervisor(self):
        self.client.force_login(self.shared_supervisor)
        landing_response = self.client.get(reverse("supervisor_landing"))
        summary_list_response = self.client.get(reverse("supervisor_course_summary_list"))

        self.assertContains(landing_response, "Landing Course A")
        self.assertNotContains(landing_response, "Landing Course B")
        self.assertContains(summary_list_response, "Landing Course A")
        self.assertNotContains(summary_list_response, "Landing Course B")

    def test_administrator_can_access_supervisor_pages_and_see_all_courses(self):
        self.client.force_login(self.administrator)
        landing_response = self.client.get(reverse("supervisor_landing"))
        summary_list_response = self.client.get(reverse("supervisor_course_summary_list"))
        self.assertEqual(landing_response.status_code, 200)
        self.assertEqual(summary_list_response.status_code, 200)
        self.assertContains(landing_response, "Landing Course A")
        self.assertContains(landing_response, "Landing Course B")
        self.assertContains(summary_list_response, "Landing Course A")
        self.assertContains(summary_list_response, "Landing Course B")

    def test_unrelated_supervisor_only_sees_courses_they_supervise(self):
        self.client.force_login(self.unrelated_supervisor)
        landing_response = self.client.get(reverse("supervisor_landing"))
        summary_list_response = self.client.get(reverse("supervisor_course_summary_list"))
        self.assertEqual(landing_response.status_code, 200)
        self.assertEqual(summary_list_response.status_code, 200)
        self.assertContains(landing_response, "No accessible courses.")
        self.assertContains(summary_list_response, "No accessible courses.")
