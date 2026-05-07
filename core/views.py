import random
import os
from decimal import Decimal

from django.contrib.auth import views as auth_views
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView

from .access import SupervisorRequiredMixin
from .forms import (
    CourseEditForm,
    ExerciseEditForm,
    ExercisePartEditForm,
    ExerciseVariantEditForm,
    ManualUploadGradingForm,
    NumericalAnswerForm,
    RegistrationForm,
    TutorialEditForm,
    UploadSubmissionForm,
)
from .grading import is_numerical_answer_correct
from .models import (
    ArchiveBatch,
    Course,
    Exercise,
    ExercisePart,
    ExerciseVariant,
    Result,
    ResultPart,
    Tutorial,
    User,
)


def _result_has_submission_data(result):
    return result.parts.filter(
        Q(submitted_numerical_value__isnull=False) | Q(uploaded_file__isnull=False)
    ).exists()


def _result_upload_part(result):
    return (
        result.parts.filter(exercise_part__answer_type=ExerciseVariant.PartAnswerType.DOCUMENT_UPLOAD)
        .select_related("exercise_part")
        .order_by("exercise_part__order_index", "id")
        .first()
    )


def _result_display_is_graded(result):
    if result.parts.filter(exercise_part__answer_type=ExerciseVariant.PartAnswerType.NUMERICAL).exists():
        return result.parts.filter(submitted_numerical_value__isnull=False).exists()
    upload_part = _result_upload_part(result)
    return bool(upload_part and upload_part.is_manually_graded)


def _user_can_access_course(user, course):
    if user.is_superuser or user.role == User.Role.ADMINISTRATOR:
        return True
    if user.role != User.Role.SUPERVISOR:
        return False
    return course.created_by_id == user.id or course.supervisors.filter(id=user.id).exists()


def _courses_accessible_to_supervisor_or_admin(user):
    if user.is_superuser or user.role == User.Role.ADMINISTRATOR:
        return Course.objects.all().order_by("title")
    return Course.objects.filter(Q(created_by=user) | Q(supervisors=user)).distinct().order_by("title")


def _user_can_access_course_results(user, course):
    if user.is_superuser or user.role == User.Role.ADMINISTRATOR:
        return True
    if user.role != User.Role.SUPERVISOR:
        return False
    return course.supervisors.filter(id=user.id).exists()


def _assert_user_can_manage_course(user, course):
    if not _user_can_access_course(user, course):
        raise PermissionDenied


def _next_order_index(queryset):
    highest = queryset.order_by("-order_index").values_list("order_index", flat=True).first()
    return (highest or 0) + 1


def _serialize_part_node(part):
    return {
        "id": part.id,
        "label": part.label,
        "prompt_text": part.prompt_text,
        "answer_type": part.answer_type,
        "order_index": part.order_index,
        "available_points": str(part.available_points),
    }


def _serialize_variant_node(variant):
    return {
        "id": variant.id,
        "exercise_text": variant.exercise_text,
        "supervisor_notes": variant.supervisor_notes,
        "parts": [
            _serialize_part_node(part)
            for part in variant.parts.all().order_by("order_index", "id")
        ],
    }


def _serialize_exercise_node(exercise):
    return {
        "id": exercise.id,
        "title": exercise.title,
        "order_index": exercise.order_index,
        "is_active": exercise.is_active,
        "variants": [
            _serialize_variant_node(variant)
            for variant in exercise.variants.all().order_by("id")
        ],
    }


def _serialize_tutorial_node(tutorial):
    return {
        "id": tutorial.id,
        "title": tutorial.title,
        "description": tutorial.description,
        "order_index": tutorial.order_index,
        "is_active": tutorial.is_active,
        "exercises": [
            _serialize_exercise_node(exercise)
            for exercise in tutorial.exercises.all().order_by("order_index", "id")
        ],
    }


def _serialize_course_node(course):
    return {
        "id": course.id,
        "title": course.title,
        "description": course.description,
        "is_active": course.is_active,
        "tutorials": [
            _serialize_tutorial_node(tutorial)
            for tutorial in course.tutorials.all().order_by("order_index", "id")
        ],
    }


class CourseListView(LoginRequiredMixin, ListView):
    model = Course
    template_name = "core/course_list.html"
    context_object_name = "courses"

    def get_queryset(self):
        return Course.objects.filter(is_active=True).order_by("title")


class RoleAwareLoginView(auth_views.LoginView):
    def get_success_url(self):
        user = self.request.user
        if user.role in {User.Role.SUPERVISOR, User.Role.ADMINISTRATOR} or user.is_superuser:
            return reverse_lazy("supervisor_landing")
        return super().get_success_url()


class LogoutView(View):
    def get(self, request):
        auth_logout(request)
        return redirect("login")

    def post(self, request):
        auth_logout(request)
        return redirect("login")


class SupervisorLandingView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_landing.html"

    def get(self, request):
        courses = _courses_accessible_to_supervisor_or_admin(request.user)
        return render(
            request,
            self.template_name,
            {"courses": courses},
        )


class SupervisorTreePageView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_tree.html"

    def get(self, request):
        return render(request, self.template_name)


class LegacySupervisorWorkflowRedirectView(SupervisorRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        return redirect("supervisor_tree")

    def post(self, request, *args, **kwargs):
        return redirect("supervisor_tree")


class SupervisorTreeDataView(SupervisorRequiredMixin, View):
    def get(self, request):
        courses = (
            _courses_accessible_to_supervisor_or_admin(request.user)
            .prefetch_related(
                "tutorials__exercises__variants__parts",
            )
            .order_by("title")
        )
        course_nodes = [_serialize_course_node(course) for course in courses]
        return JsonResponse({"courses": course_nodes})


class SupervisorTreeNodeUpdateView(SupervisorRequiredMixin, View):
    def post(self, request, node_type, node_id):
        if node_type == "course":
            return self._update_course(request, node_id)
        if node_type == "tutorial":
            return self._update_tutorial(request, node_id)
        if node_type == "exercise":
            return self._update_exercise(request, node_id)
        if node_type == "variant":
            return self._update_variant(request, node_id)
        if node_type == "part":
            return self._update_part(request, node_id)
        return JsonResponse({"ok": False, "errors": {"node": ["Unknown node type."]}}, status=400)

    def _form_error_response(self, form, status=400):
        return JsonResponse({"ok": False, "errors": form.errors}, status=status)

    def _update_course(self, request, node_id):
        course = get_object_or_404(Course, pk=node_id)
        _assert_user_can_manage_course(request.user, course)
        form = CourseEditForm(request.POST, instance=course)
        if not form.is_valid():
            return self._form_error_response(form)
        form.save()
        return JsonResponse({"ok": True, "node_type": "course", "updated_node": _serialize_course_node(course)})

    def _update_tutorial(self, request, node_id):
        tutorial = get_object_or_404(Tutorial, pk=node_id)
        _assert_user_can_manage_course(request.user, tutorial.course)
        form = TutorialEditForm(request.POST, instance=tutorial, course=tutorial.course)
        if not form.is_valid():
            return self._form_error_response(form)
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            form.add_error("order_index", "This order index is already used in this course.")
            return self._form_error_response(form)
        return JsonResponse({"ok": True, "node_type": "tutorial", "updated_node": _serialize_tutorial_node(tutorial)})

    def _update_exercise(self, request, node_id):
        exercise = get_object_or_404(Exercise, pk=node_id)
        _assert_user_can_manage_course(request.user, exercise.tutorial.course)
        form = ExerciseEditForm(request.POST, instance=exercise, tutorial=exercise.tutorial)
        if not form.is_valid():
            return self._form_error_response(form)
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            form.add_error("order_index", "This order index is already used in this tutorial.")
            return self._form_error_response(form)
        return JsonResponse({"ok": True, "node_type": "exercise", "updated_node": _serialize_exercise_node(exercise)})

    def _update_variant(self, request, node_id):
        variant = get_object_or_404(ExerciseVariant, pk=node_id)
        _assert_user_can_manage_course(request.user, variant.exercise.tutorial.course)
        form = ExerciseVariantEditForm(request.POST, instance=variant)
        if not form.is_valid():
            return self._form_error_response(form)
        form.save()
        return JsonResponse({"ok": True, "node_type": "variant", "updated_node": _serialize_variant_node(variant)})

    def _update_part(self, request, node_id):
        part = get_object_or_404(ExercisePart, pk=node_id)
        _assert_user_can_manage_course(request.user, part.variant.exercise.tutorial.course)
        part_data = {
            "label": request.POST.get("label", part.label),
            "prompt_text": request.POST.get("prompt_text", part.prompt_text),
            "answer_type": part.answer_type,
            "reference_solution": (
                "" if part.reference_solution is None else str(part.reference_solution)
            ),
            "absolute_tolerance": (
                "" if part.absolute_tolerance is None else str(part.absolute_tolerance)
            ),
            "available_points": str(part.available_points),
            "order_index": request.POST.get("order_index", str(part.order_index)),
        }
        form = ExercisePartEditForm(part_data, instance=part, variant=part.variant)
        if not form.is_valid():
            return self._form_error_response(form)
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            form.add_error("order_index", "This order index is already used in this variant.")
            return self._form_error_response(form)
        return JsonResponse({"ok": True, "node_type": "part", "updated_node": _serialize_part_node(part)})


class SupervisorTreeNodeCreateView(SupervisorRequiredMixin, View):
    def post(self, request):
        node_type = request.POST.get("node_type")
        parent_id = request.POST.get("parent_id")
        if node_type == "course":
            return self._create_course(request)
        if node_type == "tutorial":
            return self._create_tutorial(request, parent_id)
        if node_type == "exercise":
            return self._create_exercise(request, parent_id)
        if node_type == "variant":
            return self._create_variant(request, parent_id)
        if node_type == "part":
            return self._create_part(request, parent_id)
        return JsonResponse({"ok": False, "errors": {"node_type": ["Unknown node type."]}}, status=400)

    def _form_error_response(self, form, status=400):
        return JsonResponse({"ok": False, "errors": form.errors}, status=status)

    def _create_course(self, request):
        form = CourseEditForm(request.POST)
        if not form.is_valid():
            return self._form_error_response(form)
        course = form.save(commit=False)
        course.created_by = request.user
        course.save()
        return JsonResponse({"ok": True, "node_type": "course", "created_node": _serialize_course_node(course)})

    def _create_tutorial(self, request, parent_id):
        course = get_object_or_404(Course, pk=parent_id)
        _assert_user_can_manage_course(request.user, course)
        post_data = request.POST.copy()
        if not post_data.get("order_index"):
            post_data["order_index"] = str(_next_order_index(course.tutorials.all()))
        form = TutorialEditForm(post_data, course=course)
        if not form.is_valid():
            return self._form_error_response(form)
        tutorial = form.save(commit=False)
        tutorial.course = course
        try:
            with transaction.atomic():
                tutorial.save()
        except IntegrityError:
            form.add_error("order_index", "This order index is already used in this course.")
            return self._form_error_response(form)
        return JsonResponse({"ok": True, "node_type": "tutorial", "created_node": _serialize_tutorial_node(tutorial)})

    def _create_exercise(self, request, parent_id):
        tutorial = get_object_or_404(Tutorial, pk=parent_id)
        _assert_user_can_manage_course(request.user, tutorial.course)
        post_data = request.POST.copy()
        if not post_data.get("order_index"):
            post_data["order_index"] = str(_next_order_index(tutorial.exercises.all()))
        form = ExerciseEditForm(post_data, tutorial=tutorial)
        if not form.is_valid():
            return self._form_error_response(form)
        exercise = form.save(commit=False)
        exercise.tutorial = tutorial
        try:
            with transaction.atomic():
                exercise.save()
        except IntegrityError:
            form.add_error("order_index", "This order index is already used in this tutorial.")
            return self._form_error_response(form)
        return JsonResponse({"ok": True, "node_type": "exercise", "created_node": _serialize_exercise_node(exercise)})

    def _create_variant(self, request, parent_id):
        exercise = get_object_or_404(Exercise, pk=parent_id)
        _assert_user_can_manage_course(request.user, exercise.tutorial.course)
        form = ExerciseVariantEditForm(request.POST)
        if not form.is_valid():
            return self._form_error_response(form)
        variant = form.save(commit=False)
        variant.exercise = exercise
        variant.save()
        return JsonResponse({"ok": True, "node_type": "variant", "created_node": _serialize_variant_node(variant)})

    def _create_part(self, request, parent_id):
        variant = get_object_or_404(ExerciseVariant, pk=parent_id)
        _assert_user_can_manage_course(request.user, variant.exercise.tutorial.course)
        post_data = request.POST.copy()
        if not post_data.get("order_index"):
            post_data["order_index"] = str(_next_order_index(variant.parts.all()))
        form = ExercisePartEditForm(post_data, variant=variant)
        if not form.is_valid():
            return self._form_error_response(form)
        part = form.save(commit=False)
        part.variant = variant
        try:
            with transaction.atomic():
                part.save()
        except IntegrityError:
            form.add_error("order_index", "This order index is already used in this variant.")
            return self._form_error_response(form)
        return JsonResponse({"ok": True, "node_type": "part", "created_node": _serialize_part_node(part)})


class SupervisorTreeNodeDeleteView(SupervisorRequiredMixin, View):
    def post(self, request, node_type, node_id):
        if request.POST.get("confirm") != "yes":
            return JsonResponse(
                {"ok": False, "errors": {"confirm": ["Deletion requires confirmation."]}},
                status=400,
            )
        if node_type == "course":
            return self._delete_course(request, node_id)
        if node_type == "tutorial":
            return self._delete_tutorial(request, node_id)
        if node_type == "exercise":
            return self._delete_exercise(request, node_id)
        if node_type == "variant":
            return self._delete_variant(request, node_id)
        if node_type == "part":
            return self._delete_part(request, node_id)
        return JsonResponse({"ok": False, "errors": {"node": ["Unknown node type."]}}, status=400)

    def _delete_course(self, request, node_id):
        course = get_object_or_404(Course, pk=node_id)
        _assert_user_can_manage_course(request.user, course)
        deleted_id = course.id
        course.delete()
        return JsonResponse({"ok": True, "node_type": "course", "deleted_id": deleted_id})

    def _delete_tutorial(self, request, node_id):
        tutorial = get_object_or_404(Tutorial, pk=node_id)
        _assert_user_can_manage_course(request.user, tutorial.course)
        deleted_id = tutorial.id
        tutorial.delete()
        return JsonResponse({"ok": True, "node_type": "tutorial", "deleted_id": deleted_id})

    def _delete_exercise(self, request, node_id):
        exercise = get_object_or_404(Exercise, pk=node_id)
        _assert_user_can_manage_course(request.user, exercise.tutorial.course)
        deleted_id = exercise.id
        exercise.delete()
        return JsonResponse({"ok": True, "node_type": "exercise", "deleted_id": deleted_id})

    def _delete_variant(self, request, node_id):
        variant = get_object_or_404(ExerciseVariant, pk=node_id)
        _assert_user_can_manage_course(request.user, variant.exercise.tutorial.course)
        deleted_id = variant.id
        variant.delete()
        return JsonResponse({"ok": True, "node_type": "variant", "deleted_id": deleted_id})

    def _delete_part(self, request, node_id):
        part = get_object_or_404(ExercisePart, pk=node_id)
        _assert_user_can_manage_course(request.user, part.variant.exercise.tutorial.course)
        deleted_id = part.id
        part.delete()
        return JsonResponse({"ok": True, "node_type": "part", "deleted_id": deleted_id})


class SupervisorCourseSummaryListView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_course_summary_list.html"

    def get(self, request):
        courses = _courses_accessible_to_supervisor_or_admin(request.user)
        return render(
            request,
            self.template_name,
            {"courses": courses},
        )


class CourseDetailView(LoginRequiredMixin, DetailView):
    model = Course
    template_name = "core/course_detail.html"
    context_object_name = "course"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["tutorials"] = self.object.tutorials.order_by("order_index", "id")
        return context


class TutorialDetailView(LoginRequiredMixin, DetailView):
    model = Tutorial
    template_name = "core/tutorial_detail.html"
    context_object_name = "tutorial"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        exercises = list(
            self.object.exercises.filter(is_active=True).order_by("order_index", "id")
        )
        context["exercises"] = exercises

        if self.request.user.role != User.Role.STUDENT:
            return context

        exercise_ids = [exercise.id for exercise in exercises]
        totals_by_exercise_id = {
            row["variant__exercise_id"]: row["total_points"] or Decimal("0.00")
            for row in ExercisePart.objects.filter(variant__exercise_id__in=exercise_ids)
            .values("variant__exercise_id")
            .annotate(total_points=Sum("available_points"))
        }
        results_by_exercise_id = {
            result.exercise_id: result
            for result in Result.objects.filter(
                student=self.request.user,
                exercise_id__in=exercise_ids,
                is_archived=False,
            ).prefetch_related("parts")
        }

        exercise_rows = []
        for exercise in exercises:
            total_points = totals_by_exercise_id.get(exercise.id, Decimal("0.00"))
            result = results_by_exercise_id.get(exercise.id)
            has_submission = bool(
                result
                and any(
                    part.submitted_numerical_value is not None or bool(part.uploaded_file)
                    for part in result.parts.all()
                )
            )
            has_pending_upload_grading = bool(
                result
                and any(
                    part.exercise_part.answer_type == ExerciseVariant.PartAnswerType.DOCUMENT_UPLOAD
                    and bool(part.uploaded_file)
                    and not part.is_manually_graded
                    for part in result.parts.all()
                )
            )
            status = "not_completed"
            if has_pending_upload_grading:
                status = "pending_grading"
            elif has_submission:
                status = "completed"
            score = result.score if has_submission and result else Decimal("0.00")
            exercise_rows.append(
                {
                    "exercise": exercise,
                    "status": status,
                    "score_display": f"{score:.2f}",
                    "total_display": f"{total_points:.2f}",
                }
            )
        context["exercise_rows"] = exercise_rows
        return context


class ExerciseDetailView(LoginRequiredMixin, DetailView):
    model = Exercise
    template_name = "core/exercise_detail.html"
    context_object_name = "exercise"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        variant = None
        if self.request.user.role == User.Role.STUDENT:
            result = self._get_or_assign_student_result()
            variant = result.assigned_variant if result else None
            context["variant"] = variant
            context["existing_result"] = (
                result
                if result
                and _result_has_submission_data(result)
                else None
            )
            if context["existing_result"]:
                context["existing_result_parts"] = (
                    context["existing_result"]
                    .parts.select_related("exercise_part")
                    .order_by("exercise_part__order_index", "id")
                )
        else:
            variant = self.object.variants.order_by("id").first()
            context["variant"] = variant
        parts = variant.parts.order_by("order_index", "id") if variant else []
        context["parts"] = parts
        context["has_numerical_parts"] = any(
            part.answer_type == ExerciseVariant.PartAnswerType.NUMERICAL for part in parts
        )
        context["has_upload_parts"] = any(
            part.answer_type == ExerciseVariant.PartAnswerType.DOCUMENT_UPLOAD for part in parts
        )
        if context["has_numerical_parts"]:
            context["numerical_form"] = kwargs.get("numerical_form") or NumericalAnswerForm()
        if context["has_upload_parts"]:
            context["upload_form"] = kwargs.get("upload_form") or UploadSubmissionForm()
        return context

    def _ensure_default_part_for_variant(self, variant):
        part = variant.parts.order_by("order_index", "id").first()
        if part:
            return part
        return ExercisePart.objects.create(
            variant=variant,
            label="a",
            prompt_text="",
            answer_type=ExerciseVariant.PartAnswerType.NUMERICAL,
            reference_solution=None,
            absolute_tolerance=None,
            available_points=Decimal("1.00"),
            order_index=1,
        )

    def _get_or_assign_student_result(self):
        variants = list(self.object.variants.order_by("id"))
        if not variants:
            return None

        try:
            result, _ = Result.objects.get_or_create(
                student=self.request.user,
                exercise=self.object,
                is_archived=False,
                defaults={
                    "course": self.object.tutorial.course,
                    "tutorial": self.object.tutorial,
                    "assigned_variant": random.choice(variants),
                },
            )
        except IntegrityError:
            # If two requests race, reuse the row created by the winner.
            result = Result.objects.get(
                student=self.request.user,
                exercise=self.object,
                is_archived=False,
            )
        return result

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        result = self._get_or_assign_student_result() if self.request.user.role == User.Role.STUDENT else None
        variant = (
            result.assigned_variant if result else self.object.variants.order_by("id").first()
        )
        parts = variant.parts.order_by("order_index", "id") if variant else ExercisePart.objects.none()
        has_upload_parts = parts.filter(answer_type=ExerciseVariant.PartAnswerType.DOCUMENT_UPLOAD).exists()
        has_numerical_parts = parts.filter(
            answer_type=ExerciseVariant.PartAnswerType.NUMERICAL
        ).exists()
        has_part_numerical_submission = any(
            key.startswith("numerical_part_") for key in request.POST.keys()
        )
        has_part_upload_submission = any(
            key.startswith("upload_part_") for key in request.FILES.keys()
        )

        if (has_part_numerical_submission or has_part_upload_submission) and result:
            submission_errors = []
            numerical_correct_flags = []
            has_saved_part_submission = False

            for part in parts:
                if part.answer_type == ExerciseVariant.PartAnswerType.NUMERICAL:
                    raw_value = request.POST.get(f"numerical_part_{part.id}", "").strip()
                    if raw_value == "":
                        continue
                    try:
                        submitted_value = Decimal(raw_value)
                    except Exception:
                        submission_errors.append(
                            f"Part {part.label}: enter a valid numerical value."
                        )
                        continue

                    has_saved_part_submission = True
                    is_correct = None
                    score = Decimal("0")
                    if (
                        part.reference_solution is not None
                        and part.absolute_tolerance is not None
                    ):
                        is_correct = is_numerical_answer_correct(
                            submitted_value=submitted_value,
                            reference_solution=part.reference_solution,
                            absolute_tolerance=part.absolute_tolerance,
                        )
                        numerical_correct_flags.append(bool(is_correct))
                        score = part.available_points if is_correct else Decimal("0")

                    ResultPart.objects.update_or_create(
                        result=result,
                        exercise_part=part,
                        defaults={
                            "submitted_numerical_value": submitted_value,
                            "uploaded_file": None,
                            "reference_value_used": part.reference_solution,
                            "tolerance_used": part.absolute_tolerance,
                            "is_correct": is_correct,
                            "score": score,
                            "is_manually_graded": True,
                            "feedback": "",
                            "graded_at": timezone.now(),
                            "graded_by": None,
                        },
                    )
                else:
                    uploaded_file = request.FILES.get(f"upload_part_{part.id}")
                    if not uploaded_file:
                        continue
                    upload_result_part = ResultPart.objects.filter(
                        result=result,
                        exercise_part=part,
                    ).first()
                    if upload_result_part and upload_result_part.is_manually_graded:
                        submission_errors.append(
                            f"Part {part.label}: this upload has already been manually graded and cannot be replaced."
                        )
                        continue
                    has_saved_part_submission = True
                    old_file_name = (
                        upload_result_part.uploaded_file.name
                        if upload_result_part and upload_result_part.uploaded_file
                        else None
                    )
                    ResultPart.objects.update_or_create(
                        result=result,
                        exercise_part=part,
                        defaults={
                            "submitted_numerical_value": None,
                            "uploaded_file": uploaded_file,
                            "reference_value_used": None,
                            "tolerance_used": None,
                            "is_correct": None,
                            "score": Decimal("0"),
                            "is_manually_graded": False,
                            "feedback": "",
                            "graded_at": None,
                            "graded_by": None,
                        },
                    )
                    new_upload_result_part = ResultPart.objects.get(
                        result=result,
                        exercise_part=part,
                    )
                    if (
                        old_file_name
                        and new_upload_result_part.uploaded_file
                        and old_file_name != new_upload_result_part.uploaded_file.name
                        and default_storage.exists(old_file_name)
                    ):
                        default_storage.delete(old_file_name)

            if submission_errors:
                context = self.get_context_data()
                context["submission_errors"] = submission_errors
                return self.render_to_response(context)

            if has_saved_part_submission:
                result.submitted_at = timezone.now()
                result.is_correct = (
                    all(numerical_correct_flags) if numerical_correct_flags else None
                )
                result.save(update_fields=["submitted_at", "is_correct"])
                result.recompute_total_score()
                result.save(update_fields=["score"])
            return self.render_to_response(self.get_context_data())

        if has_upload_parts and "uploaded_file" in request.FILES:
            form = UploadSubmissionForm(request.POST, request.FILES)
            if form.is_valid() and result:
                upload_part = (
                    result.assigned_variant.parts.filter(
                        answer_type=ExerciseVariant.PartAnswerType.DOCUMENT_UPLOAD
                    )
                    .order_by("order_index", "id")
                    .first()
                    or self._ensure_default_part_for_variant(result.assigned_variant)
                )
                upload_result_part = ResultPart.objects.filter(
                    result=result,
                    exercise_part=upload_part,
                ).first()
                if upload_result_part and upload_result_part.is_manually_graded:
                    form.add_error(
                        None,
                        "This submission has already been manually graded and cannot be replaced.",
                    )
                    return self.render_to_response(self.get_context_data(upload_form=form))

                old_file_name = (
                    upload_result_part.uploaded_file.name
                    if upload_result_part and upload_result_part.uploaded_file
                    else None
                )
                result.submitted_at = timezone.now()
                result.score = Decimal("0")
                result.is_correct = None
                result.save(update_fields=["submitted_at", "score", "is_correct"])
                ResultPart.objects.update_or_create(
                    result=result,
                    exercise_part=upload_part,
                    defaults={
                        "submitted_numerical_value": None,
                        "uploaded_file": form.cleaned_data["uploaded_file"],
                        "reference_value_used": None,
                        "tolerance_used": None,
                        "is_correct": None,
                        "score": Decimal("0"),
                        "is_manually_graded": False,
                        "feedback": "",
                        "graded_at": None,
                        "graded_by": None,
                    },
                )
                result.recompute_total_score()
                result.save(update_fields=["score"])
                # Delete the previous upload only after new save succeeds.
                new_upload_result_part = ResultPart.objects.get(
                    result=result,
                    exercise_part=upload_part,
                )
                if (
                    old_file_name
                    and new_upload_result_part.uploaded_file
                    and old_file_name != new_upload_result_part.uploaded_file.name
                ):
                    if default_storage.exists(old_file_name):
                        default_storage.delete(old_file_name)
                return self.render_to_response(
                    self.get_context_data(upload_form=UploadSubmissionForm())
                )
            return self.render_to_response(self.get_context_data(upload_form=form))

        if not has_numerical_parts:
            return self.render_to_response(self.get_context_data())

        form = NumericalAnswerForm(request.POST)
        if form.is_valid():
            is_correct = None
            if (
                variant
                and (
                    numerical_part := (
                        variant.parts.filter(answer_type=ExerciseVariant.PartAnswerType.NUMERICAL)
                        .order_by("order_index", "id")
                        .first()
                        or self._ensure_default_part_for_variant(variant)
                    )
                )
                and numerical_part.reference_solution is not None
                and numerical_part.absolute_tolerance is not None
            ):
                is_correct = is_numerical_answer_correct(
                    submitted_value=form.cleaned_data["submitted_value"],
                    reference_solution=numerical_part.reference_solution,
                    absolute_tolerance=numerical_part.absolute_tolerance,
                )
            if result and is_correct is not None:
                result.is_correct = is_correct
                result.score = numerical_part.available_points if is_correct else Decimal("0")
                result.submitted_at = timezone.now()
                result.save(
                    update_fields=[
                        "is_correct",
                        "score",
                        "submitted_at",
                    ]
                )
                ResultPart.objects.update_or_create(
                    result=result,
                    exercise_part=numerical_part,
                    defaults={
                        "submitted_numerical_value": form.cleaned_data["submitted_value"],
                        "uploaded_file": None,
                        "reference_value_used": numerical_part.reference_solution,
                        "tolerance_used": numerical_part.absolute_tolerance,
                        "is_correct": is_correct,
                        "score": numerical_part.available_points if is_correct else Decimal("0"),
                        "is_manually_graded": True,
                        "feedback": "",
                        "graded_at": timezone.now(),
                        "graded_by": None,
                    },
                )
                result.recompute_total_score()
                result.save(update_fields=["score"])
            context = self.get_context_data(
                numerical_form=NumericalAnswerForm(),
            )
            return self.render_to_response(context)
        return self.render_to_response(self.get_context_data(numerical_form=form))


class SupervisorExerciseSubmissionsView(SupervisorRequiredMixin, DetailView):
    model = Exercise
    template_name = "core/supervisor_exercise_submissions.html"
    context_object_name = "exercise"
    pk_url_kwarg = "exercise_id"

    def get_context_data(self, **kwargs):
        if not _user_can_access_course_results(self.request.user, self.object.tutorial.course):
            raise PermissionDenied
        context = super().get_context_data(**kwargs)
        submissions = Result.objects.filter(
            exercise=self.object,
            archive_batch__isnull=True,
        ).select_related("student")
        status_filter = self.request.GET.get("status")
        if status_filter == "graded":
            submissions = submissions.filter(parts__is_manually_graded=True).distinct()
        elif status_filter == "ungraded":
            submissions = submissions.filter(
                parts__exercise_part__answer_type=ExerciseVariant.PartAnswerType.DOCUMENT_UPLOAD,
                parts__is_manually_graded=False,
            ).distinct()
        context["status_filter"] = status_filter or "all"
        submissions = list(submissions.order_by("-submitted_at", "-id"))
        for submission in submissions:
            submission.display_is_manually_graded = _result_display_is_graded(submission)
        context["submissions"] = submissions
        return context


class SupervisorSubmissionDetailView(SupervisorRequiredMixin, DetailView):
    model = Result
    template_name = "core/supervisor_submission_detail.html"
    context_object_name = "submission"
    pk_url_kwarg = "result_id"

    def get_queryset(self):
        return Result.objects.filter(archive_batch__isnull=True)

    def get_context_data(self, **kwargs):
        if not _user_can_access_course_results(self.request.user, self.object.course):
            raise PermissionDenied
        context = super().get_context_data(**kwargs)
        upload_part = _result_upload_part(self.object)
        context["upload_result_part"] = upload_part
        if upload_part:
            initial = {
                "score": upload_part.score,
                "feedback": upload_part.feedback,
            }
            context["grading_form"] = kwargs.get("grading_form") or ManualUploadGradingForm(
                initial=initial
            )
        context["numerical_result_parts"] = self.object.parts.filter(
            exercise_part__answer_type=ExerciseVariant.PartAnswerType.NUMERICAL
        ).select_related("exercise_part")
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if not _user_can_access_course_results(request.user, self.object.course):
            raise PermissionDenied
        if _result_upload_part(self.object) is None:
            return self.render_to_response(self.get_context_data())

        form = ManualUploadGradingForm(request.POST)
        if form.is_valid():
            upload_part = _result_upload_part(self.object)
            if upload_part is None:
                raise Http404("No upload part found for this submission.")
            upload_part.score = form.cleaned_data["score"]
            upload_part.feedback = form.cleaned_data["feedback"]
            upload_part.is_manually_graded = True
            upload_part.graded_by = request.user
            upload_part.graded_at = timezone.now()
            upload_part.save(
                update_fields=[
                    "score",
                    "feedback",
                    "is_manually_graded",
                    "graded_by",
                    "graded_at",
                ]
            )
            self.object.recompute_total_score()
            self.object.save(update_fields=["score"])
            return self.render_to_response(self.get_context_data())
        return self.render_to_response(self.get_context_data(grading_form=form))


class SupervisorSubmissionFileDownloadView(SupervisorRequiredMixin, View):
    def get(self, request, result_id):
        submission = get_object_or_404(Result, pk=result_id, archive_batch__isnull=True)
        if not _user_can_access_course_results(request.user, submission.course):
            raise PermissionDenied
        upload_part = _result_upload_part(submission)
        if not upload_part or not upload_part.uploaded_file:
            raise Http404("No uploaded file for this submission.")
        return FileResponse(
            upload_part.uploaded_file.open("rb"),
            as_attachment=True,
            filename=os.path.basename(upload_part.uploaded_file.name),
        )


class SupervisorCourseSummaryView(SupervisorRequiredMixin, DetailView):
    model = Course
    template_name = "core/supervisor_course_summary.html"
    context_object_name = "course"
    pk_url_kwarg = "course_id"

    def get_context_data(self, **kwargs):
        if not _user_can_access_course(self.request.user, self.object):
            raise PermissionDenied
        context = super().get_context_data(**kwargs)

        tutorials = list(self.object.tutorials.order_by("order_index", "id"))
        selected_tutorial = None
        selected_tutorial_id_raw = self.request.GET.get("tutorial_id")
        if selected_tutorial_id_raw:
            try:
                selected_tutorial = next(
                    tutorial
                    for tutorial in tutorials
                    if tutorial.id == int(selected_tutorial_id_raw)
                )
            except (StopIteration, ValueError):
                selected_tutorial = None

        tutorial_ids = [selected_tutorial.id] if selected_tutorial else [tutorial.id for tutorial in tutorials]
        exercises = list(
            Exercise.objects.filter(
                tutorial__course=self.object,
                tutorial_id__in=tutorial_ids,
                is_active=True,
            )
            .select_related("tutorial")
            .order_by("tutorial__order_index", "tutorial_id", "order_index", "id")
        )
        exercise_ids = [exercise.id for exercise in exercises]
        all_results = list(
            Result.objects.filter(
                course=self.object,
                exercise_id__in=exercise_ids,
                archive_batch__isnull=True,
            )
            .select_related("student")
            .order_by("-submitted_at", "-id")
        )
        all_students = sorted({result.student for result in all_results}, key=lambda student: student.email)
        selected_student = None
        selected_student_id_raw = self.request.GET.get("student_id")
        if selected_student_id_raw:
            try:
                selected_student = next(
                    student for student in all_students if student.id == int(selected_student_id_raw)
                )
            except (StopIteration, ValueError):
                selected_student = None
        students = [selected_student] if selected_student else all_students
        results = (
            [result for result in all_results if result.student_id == selected_student.id]
            if selected_student
            else all_results
        )
        result_ids = [result.id for result in results]
        result_parts = list(
            ResultPart.objects.filter(result_id__in=result_ids).select_related("exercise_part")
        )
        result_by_student_exercise = {
            (result.student_id, result.exercise_id): result for result in results
        }
        result_part_by_result_part = {
            (result_part.result_id, result_part.exercise_part_id): result_part
            for result_part in result_parts
        }

        tutorial_tables = []
        tutorials_to_show = [selected_tutorial] if selected_tutorial else tutorials
        for tutorial in tutorials_to_show:
            tutorial_exercises = [exercise for exercise in exercises if exercise.tutorial_id == tutorial.id]
            exercise_parts = list(
                ExercisePart.objects.filter(variant__exercise__in=tutorial_exercises)
                .select_related("variant__exercise")
                .order_by(
                    "variant__exercise__order_index",
                    "variant__exercise_id",
                    "order_index",
                    "id",
                )
            )
            rows = []
            for student in students:
                cells = []
                for part in exercise_parts:
                    result = result_by_student_exercise.get((student.id, part.variant.exercise_id))
                    result_part = (
                        result_part_by_result_part.get((result.id, part.id))
                        if result
                        else None
                    )
                    cells.append(result_part)
                rows.append({"student": student, "cells": cells})
            tutorial_tables.append(
                {
                    "tutorial": tutorial,
                    "columns": exercise_parts,
                    "rows": rows,
                }
            )

        context["tutorial_tables"] = tutorial_tables
        context["results"] = results
        context["tutorials"] = tutorials
        context["selected_tutorial"] = selected_tutorial
        context["selected_tutorial_id"] = str(selected_tutorial.id) if selected_tutorial else ""
        context["all_students"] = all_students
        context["selected_student"] = selected_student
        context["selected_student_id"] = str(selected_student.id) if selected_student else ""
        return context


class SupervisorCourseArchiveResultsView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_course_archive_results_confirm.html"

    def _get_course(self, course_id):
        return get_object_or_404(Course, pk=course_id)

    def _get_current_results_queryset(self, course):
        return Result.objects.filter(course=course, archive_batch__isnull=True)

    def get(self, request, course_id):
        course = self._get_course(course_id)
        if not _user_can_access_course(request.user, course):
            raise PermissionDenied
        current_results_count = self._get_current_results_queryset(course).count()
        archive_notice = (
            "No current results to archive for this course."
            if current_results_count == 0
            else ""
        )
        return render(
            request,
            self.template_name,
            {
                "course": course,
                "current_results_count": current_results_count,
                "archive_notice": archive_notice,
            },
        )

    def post(self, request, course_id):
        course = self._get_course(course_id)
        if not _user_can_access_course(request.user, course):
            raise PermissionDenied
        note = request.POST.get("note", "").strip()
        current_results_queryset = self._get_current_results_queryset(course)
        current_results_count = current_results_queryset.count()
        if current_results_count == 0:
            return render(
                request,
                self.template_name,
                {
                    "course": course,
                    "current_results_count": 0,
                    "archive_notice": "No current results to archive for this course.",
                },
            )
        with transaction.atomic():
            batch = ArchiveBatch.objects.create(
                course=course,
                created_by=request.user,
                note=note,
            )
            current_results_queryset.update(
                archive_batch=batch,
                is_archived=True,
            )
        return redirect("supervisor_course_summary", course_id=course.id)


class SupervisorCourseArchivesView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_course_archives.html"

    def get(self, request, course_id):
        course = get_object_or_404(Course, pk=course_id)
        if not _user_can_access_course(request.user, course):
            raise PermissionDenied
        archive_batches = (
            ArchiveBatch.objects.filter(course=course)
            .select_related("created_by")
            .annotate(result_count=Count("results"))
            .order_by("-created_at", "-id")
        )
        return render(
            request,
            self.template_name,
            {
                "course": course,
                "archive_batches": archive_batches,
            },
        )


class SupervisorCourseArchiveBatchDetailView(SupervisorRequiredMixin, DetailView):
    model = ArchiveBatch
    template_name = "core/supervisor_course_archive_batch_detail.html"
    context_object_name = "archive_batch"
    pk_url_kwarg = "archive_batch_id"

    def get_queryset(self):
        return ArchiveBatch.objects.select_related("course", "created_by")

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        if not _user_can_access_course(request.user, self.object.course):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        results = list(
            self.object.results.select_related(
            "student", "exercise", "tutorial"
            ).order_by("-submitted_at", "-id")
        )
        for result in results:
            upload_part = _result_upload_part(result)
            result.display_is_manually_graded = _result_display_is_graded(result)
            result.display_uploaded_file = upload_part.uploaded_file if upload_part else None
        context["results"] = results
        return context


class SupervisorArchivedSubmissionFileDownloadView(SupervisorRequiredMixin, View):
    def get(self, request, result_id):
        submission = get_object_or_404(Result, pk=result_id, archive_batch__isnull=False)
        if not _user_can_access_course(request.user, submission.course):
            raise PermissionDenied
        upload_part = _result_upload_part(submission)
        if not upload_part or not upload_part.uploaded_file:
            raise Http404("No uploaded file for this submission.")
        return FileResponse(
            upload_part.uploaded_file.open("rb"),
            as_attachment=True,
            filename=os.path.basename(upload_part.uploaded_file.name),
        )


class RegisterView(CreateView):
    form_class = RegistrationForm
    template_name = "core/register.html"
    success_url = reverse_lazy("login")
