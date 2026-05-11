import random
import os
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
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
from .numeric_parsing import parse_decimal_value


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


def _format_decimal_compact(value):
    if value is None:
        return ""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    normalized = value.normalize()
    rendered = format(normalized, "f")
    if "." in rendered:
        trimmed = rendered.rstrip("0").rstrip(".")
    else:
        trimmed = rendered
    return trimmed if trimmed else "0"


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


def _get_or_assign_student_result_for_exercise(student, exercise):
    variants = list(exercise.variants.order_by("id"))
    if not variants:
        return None
    assigned_variant = _select_variant_for_student(exercise, variants)
    try:
        result, _ = Result.objects.get_or_create(
            student=student,
            exercise=exercise,
            is_archived=False,
            defaults={
                "course": exercise.tutorial.course,
                "tutorial": exercise.tutorial,
                "assigned_variant": assigned_variant,
            },
        )
    except IntegrityError:
        result = Result.objects.get(
            student=student,
            exercise=exercise,
            is_archived=False,
        )
    return result


def _select_variant_for_student(exercise, variants):
    if not variants:
        return None
    variant_ids = [variant.id for variant in variants]
    usage_rows = (
        Result.objects.filter(
            exercise=exercise,
            is_archived=False,
            assigned_variant_id__in=variant_ids,
        )
        .values("assigned_variant_id")
        .annotate(assigned_count=Count("id"))
    )
    usage_by_variant_id = {
        row["assigned_variant_id"]: row["assigned_count"] for row in usage_rows
    }
    min_count = min(usage_by_variant_id.get(variant_id, 0) for variant_id in variant_ids)
    candidate_variants = [
        variant
        for variant in variants
        if usage_by_variant_id.get(variant.id, 0) == min_count
    ]
    return random.choice(candidate_variants)


def _serialize_part_node(part):
    return {
        "id": part.id,
        "label": part.label,
        "prompt_text": part.prompt_text,
        "answer_type": part.answer_type,
        "reference_solution": (
            "" if part.reference_solution is None else str(part.reference_solution)
        ),
        "absolute_tolerance": (
            "" if part.absolute_tolerance is None else str(part.absolute_tolerance)
        ),
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
            "reference_solution": request.POST.get(
                "reference_solution",
                "" if part.reference_solution is None else str(part.reference_solution),
            ),
            "absolute_tolerance": request.POST.get(
                "absolute_tolerance",
                "" if part.absolute_tolerance is None else str(part.absolute_tolerance),
            ),
            "available_points": request.POST.get("available_points", str(part.available_points)),
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


class SupervisorContentUploadView(SupervisorRequiredMixin, View):
    def post(self, request):
        node_type = request.POST.get("node_type")
        node_id = request.POST.get("node_id")
        uploaded_file = request.FILES.get("file")
        if node_type not in {"variant", "part"}:
            return JsonResponse({"ok": False, "errors": {"node_type": ["Unsupported node type."]}}, status=400)
        if not node_id:
            return JsonResponse({"ok": False, "errors": {"node_id": ["Node id is required."]}}, status=400)
        if not uploaded_file:
            return JsonResponse({"ok": False, "errors": {"file": ["File is required."]}}, status=400)

        if node_type == "variant":
            variant = get_object_or_404(ExerciseVariant, pk=node_id)
            _assert_user_can_manage_course(request.user, variant.exercise.tutorial.course)
        else:
            part = get_object_or_404(ExercisePart, pk=node_id)
            _assert_user_can_manage_course(request.user, part.variant.exercise.tutorial.course)

        original_name = uploaded_file.name or "content-file"
        storage_name = f"content/{original_name}"
        if default_storage.exists(storage_name):
            default_storage.delete(storage_name)
        stored_name = default_storage.save(storage_name, uploaded_file)
        file_url = default_storage.url(stored_name)
        return JsonResponse({"ok": True, "url": file_url, "name": original_name})


class SupervisorContentBrowseView(SupervisorRequiredMixin, View):
    def get(self, request):
        query = (request.GET.get("q") or "").strip().lower()
        content_root = os.path.join(settings.MEDIA_ROOT, "content")
        if not os.path.isdir(content_root):
            return JsonResponse({"ok": True, "files": []})

        files = []
        for root, _, filenames in os.walk(content_root):
            for filename in filenames:
                if query and query not in filename.lower():
                    continue
                absolute_path = os.path.join(root, filename)
                rel_path = os.path.relpath(absolute_path, content_root).replace(os.sep, "/")
                storage_path = f"content/{rel_path}"
                files.append(
                    {
                        "name": filename,
                        "path": storage_path,
                        "url": default_storage.url(storage_path),
                        "modified_ts": os.path.getmtime(absolute_path),
                    }
                )

        files.sort(key=lambda item: item["modified_ts"], reverse=True)
        for item in files:
            item.pop("modified_ts", None)
        return JsonResponse({"ok": True, "files": files})


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
        tutorials = list(self.object.tutorials.order_by("order_index", "id"))
        context["tutorials"] = tutorials
        if self.request.user.role != User.Role.STUDENT:
            return context

        tutorial_ids = [tutorial.id for tutorial in tutorials]
        possible_points_by_tutorial = {tutorial.id: Decimal("0.00") for tutorial in tutorials}
        assigned_variant_ids = Result.objects.filter(
            student=self.request.user,
            course=self.object,
            tutorial_id__in=tutorial_ids,
            is_archived=False,
            assigned_variant__isnull=False,
        ).values("assigned_variant_id")
        parts_by_tutorial = (
            ExercisePart.objects.filter(
                variant_id__in=assigned_variant_ids,
            )
            .values("variant__exercise__tutorial_id")
            .annotate(total_points=Sum("available_points"))
        )
        for row in parts_by_tutorial:
            tutorial_id = row["variant__exercise__tutorial_id"]
            possible_points_by_tutorial[tutorial_id] = row["total_points"] or Decimal("0.00")
        score_by_tutorial = {
            row["tutorial_id"]: row["total_score"] or Decimal("0.00")
            for row in Result.objects.filter(
                student=self.request.user,
                course=self.object,
                tutorial_id__in=tutorial_ids,
                is_archived=False,
            )
            .values("tutorial_id")
            .annotate(total_score=Sum("score"))
        }

        tutorial_rows = []
        for tutorial in tutorials:
            achieved = score_by_tutorial.get(tutorial.id, Decimal("0.00"))
            possible = possible_points_by_tutorial.get(tutorial.id, Decimal("0.00"))
            is_completed = achieved > Decimal("0.00")
            tutorial_rows.append(
                {
                    "tutorial": tutorial,
                    "is_completed": is_completed,
                    "achieved_display": _format_decimal_compact(achieved),
                    "possible_display": _format_decimal_compact(possible),
                }
            )
        context["tutorial_rows"] = tutorial_rows
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

        exercise_ids = [exercise.id for exercise in exercises]
        is_student = self.request.user.role == User.Role.STUDENT
        results_by_exercise_id = {}
        if is_student:
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
            result = results_by_exercise_id.get(exercise.id)
            if is_student and result is None:
                result = _get_or_assign_student_result_for_exercise(self.request.user, exercise)
                if result:
                    results_by_exercise_id[exercise.id] = result
            variant = result.assigned_variant if result else exercise.variants.order_by("id").first()
            parts = list(variant.parts.order_by("order_index", "id")) if variant else []
            total_points = sum((part.available_points for part in parts), Decimal("0.00"))
            existing_parts_by_exercise_part_id = {}
            if result:
                existing_parts_by_exercise_part_id = {
                    result_part.exercise_part_id: result_part
                    for result_part in result.parts.select_related("exercise_part")
                }
            for part in parts:
                if part.absolute_tolerance is None:
                    part.display_tolerance = ""
                else:
                    part.display_tolerance = _format_decimal_compact(part.absolute_tolerance)
                part.saved_result_part = existing_parts_by_exercise_part_id.get(part.id)
                part.prefill_numerical_value = (
                    _format_decimal_compact(part.saved_result_part.submitted_numerical_value)
                    if part.saved_result_part
                    else None
                )
                if part.saved_result_part:
                    part.points_display = (
                        f"Punkte: {_format_decimal_compact(part.saved_result_part.score)}"
                        f" / {_format_decimal_compact(part.available_points)}"
                    )
                else:
                    part.points_display = ""
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
                    "variant": variant,
                    "parts": parts,
                    "has_numerical_parts": any(
                        part.answer_type == ExerciseVariant.PartAnswerType.NUMERICAL
                        for part in parts
                    ),
                    "has_upload_parts": any(
                        part.answer_type == ExerciseVariant.PartAnswerType.DOCUMENT_UPLOAD
                        for part in parts
                    ),
                    "status": status,
                    "score_display": _format_decimal_compact(score),
                    "total_display": _format_decimal_compact(total_points),
                }
            )
        context["exercise_rows"] = exercise_rows
        context["has_any_numerical_parts"] = any(
            row["has_numerical_parts"] for row in exercise_rows
        )
        context["submission_errors"] = kwargs.get("submission_errors", [])
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.user.role != User.Role.STUDENT:
            raise PermissionDenied

        exercises = list(
            self.object.exercises.filter(is_active=True).order_by("order_index", "id")
        )
        submission_errors = []
        touched_results = {}

        for exercise in exercises:
            result = _get_or_assign_student_result_for_exercise(request.user, exercise)
            if not result or not result.assigned_variant:
                continue
            parts = result.assigned_variant.parts.order_by("order_index", "id")
            for part in parts:
                if part.answer_type != ExerciseVariant.PartAnswerType.NUMERICAL:
                    continue
                raw_value = request.POST.get(f"numerical_part_{part.id}", "").strip()
                if raw_value == "":
                    continue
                try:
                    submitted_value = parse_decimal_value(raw_value)
                except ValueError:
                    submission_errors.append(
                        f"Part {part.label}: enter a valid numerical value."
                    )
                    continue

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
                touched = touched_results.setdefault(
                    result.id,
                    {"result": result, "numerical_correct_flags": []},
                )
                if is_correct is not None:
                    touched["numerical_correct_flags"].append(bool(is_correct))

        if submission_errors:
            return self.render_to_response(
                self.get_context_data(submission_errors=submission_errors)
            )

        for touched in touched_results.values():
            result = touched["result"]
            flags = touched["numerical_correct_flags"]
            result.submitted_at = timezone.now()
            result.is_correct = all(flags) if flags else None
            result.save(update_fields=["submitted_at", "is_correct"])
            result.recompute_total_score()
            result.save(update_fields=["score"])

        return redirect("tutorial_detail", pk=self.object.id)


class ExerciseDetailView(LoginRequiredMixin, DetailView):
    model = Exercise
    template_name = "core/exercise_detail.html"
    context_object_name = "exercise"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        variant = None
        result = None
        if self.request.user.role == User.Role.STUDENT:
            result = self._get_or_assign_student_result()
            variant = result.assigned_variant if result else None
            context["variant"] = variant
        else:
            variant = self.object.variants.order_by("id").first()
            context["variant"] = variant
        parts = variant.parts.order_by("order_index", "id") if variant else []
        existing_parts_by_exercise_part_id = {}
        if result:
            existing_parts_by_exercise_part_id = {
                result_part.exercise_part_id: result_part
                for result_part in result.parts.select_related("exercise_part")
            }
        for part in parts:
            if part.absolute_tolerance is None:
                part.display_tolerance = ""
            else:
                part.display_tolerance = _format_decimal_compact(part.absolute_tolerance)
            part.saved_result_part = existing_parts_by_exercise_part_id.get(part.id)
            part.prefill_numerical_value = (
                _format_decimal_compact(part.saved_result_part.submitted_numerical_value)
                if part.saved_result_part
                else None
            )
            if part.saved_result_part:
                part.points_display = (
                    f"Punkte: {_format_decimal_compact(part.saved_result_part.score)}"
                    f" / {_format_decimal_compact(part.available_points)}"
                )
            else:
                part.points_display = ""
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

    def _get_or_assign_student_result(self):
        variants = list(self.object.variants.order_by("id"))
        if not variants:
            return None
        assigned_variant = _select_variant_for_student(self.object, variants)

        try:
            result, _ = Result.objects.get_or_create(
                student=self.request.user,
                exercise=self.object,
                is_archived=False,
                defaults={
                    "course": self.object.tutorial.course,
                    "tutorial": self.object.tutorial,
                    "assigned_variant": assigned_variant,
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

    def _redirect_after_success(self, request):
        next_url = request.POST.get("next", "").strip()
        if not next_url:
            return None
        if url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return None

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
            force_replace_graded_upload = request.POST.get("force_replace_graded_upload") == "1"

            for part in parts:
                if part.answer_type == ExerciseVariant.PartAnswerType.NUMERICAL:
                    raw_value = request.POST.get(f"numerical_part_{part.id}", "").strip()
                    if raw_value == "":
                        continue
                    try:
                        submitted_value = parse_decimal_value(raw_value)
                    except ValueError:
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
                    if (
                        upload_result_part
                        and upload_result_part.is_manually_graded
                        and not force_replace_graded_upload
                    ):
                        submission_errors.append(
                            f"Part {part.label}: Do you really want to upload a new file? Any existing file and any existing grade will be overwritten!"
                        )
                        continue
                    if upload_result_part and upload_result_part.is_manually_graded:
                        old_graded_file_name = (
                            upload_result_part.uploaded_file.name
                            if upload_result_part.uploaded_file
                            else None
                        )
                        upload_result_part.delete()
                        if old_graded_file_name and default_storage.exists(old_graded_file_name):
                            default_storage.delete(old_graded_file_name)
                        upload_result_part = None
                    has_saved_part_submission = True
                    old_file_name = (
                        upload_result_part.uploaded_file.name
                        if upload_result_part and upload_result_part.uploaded_file
                        else None
                    )
                    updated_upload_part, _ = ResultPart.objects.update_or_create(
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
                    updated_upload_part.submitted_at = timezone.now()
                    updated_upload_part.save(update_fields=["submitted_at"])
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
                redirect_response = self._redirect_after_success(request)
                if redirect_response:
                    return redirect_response
            return self.render_to_response(self.get_context_data())

        if not has_numerical_parts:
            return self.render_to_response(self.get_context_data())
        return self.render_to_response(self.get_context_data())


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
        context["is_upload_exercise"] = (
            self.object.exercise.exercise_type == Exercise.ExerciseType.DOCUMENT_UPLOAD
        )
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
        part_results = self.object.parts.select_related("exercise_part").order_by(
            "exercise_part__order_index",
            "id",
        )
        detail_rows = []
        for part_result in part_results:
            submitted_value = "-"
            if part_result.submitted_numerical_value is not None:
                submitted_value = _format_decimal_compact(part_result.submitted_numerical_value)
            elif part_result.uploaded_file:
                submitted_value = part_result.uploaded_file.name

            detail_rows.append(
                {
                    "part_label": part_result.exercise_part.label,
                    "submitted_value": submitted_value,
                    "submitted_file_url": (
                        reverse_lazy("supervisor_submission_file_download", kwargs={"result_id": self.object.id})
                        if part_result.uploaded_file
                        else ""
                    ),
                    "reference_solution": (
                        _format_decimal_compact(part_result.reference_value_used)
                        if part_result.reference_value_used is not None
                        else "-"
                    ),
                    "tolerance": (
                        _format_decimal_compact(part_result.tolerance_used)
                        if part_result.tolerance_used is not None
                        else "-"
                    ),
                    "upload_timestamp": part_result.submitted_at,
                    "awarded_points": part_result.score,
                    "available_points": part_result.exercise_part.available_points,
                }
            )
        context["detail_rows"] = detail_rows
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
            requested_score = form.cleaned_data["score"]
            if requested_score > upload_part.exercise_part.available_points:
                form.add_error(
                    "score",
                    "Score cannot be greater than available points for this exercise part.",
                )
                return self.render_to_response(self.get_context_data(grading_form=form))
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
            ResultPart.objects.filter(result_id__in=result_ids).select_related(
                "exercise_part",
                "exercise_part__variant",
            )
        )
        result_by_student_exercise = {
            (result.student_id, result.exercise_id): result for result in results
        }
        result_part_by_result_exercise_label = {}
        for result_part in result_parts:
            exercise_id = result_part.exercise_part.variant.exercise_id
            key = (result_part.result_id, exercise_id, result_part.exercise_part.label)
            result_part_by_result_exercise_label[key] = result_part

        tutorial_tables = []
        tutorials_to_show = [selected_tutorial] if selected_tutorial else tutorials
        for tutorial in tutorials_to_show:
            tutorial_exercises = [exercise for exercise in exercises if exercise.tutorial_id == tutorial.id]
            tutorial_results = [result for result in results if result.tutorial_id == tutorial.id]
            exercise_parts = []
            seen_exercise_label = set()
            tutorial_exercises_by_id = {exercise.id: exercise for exercise in tutorial_exercises}
            for result in tutorial_results:
                assigned_variant = result.assigned_variant
                if not assigned_variant or assigned_variant.exercise_id not in tutorial_exercises_by_id:
                    continue
                variant_parts = assigned_variant.parts.order_by("order_index", "id")
                for part in variant_parts:
                    key = (assigned_variant.exercise_id, part.label)
                    if key in seen_exercise_label:
                        continue
                    seen_exercise_label.add(key)
                    exercise_parts.append(part)
            exercise_parts.sort(
                key=lambda part: (
                    tutorial_exercises_by_id[part.variant.exercise_id].order_index,
                    part.variant.exercise_id,
                    part.order_index,
                    part.id,
                )
            )
            exercise_groups = []
            for part in exercise_parts:
                exercise = part.variant.exercise
                if not exercise_groups or exercise_groups[-1]["exercise_id"] != exercise.id:
                    exercise_groups.append(
                        {
                            "exercise_id": exercise.id,
                            "exercise_title": exercise.title,
                            "colspan": 1,
                        }
                    )
                else:
                    exercise_groups[-1]["colspan"] += 1
            rows = []
            for student in students:
                cells = []
                row_total = Decimal("0")
                for part in exercise_parts:
                    result = result_by_student_exercise.get((student.id, part.variant.exercise_id))
                    result_part = (
                        result_part_by_result_exercise_label.get(
                            (result.id, part.variant.exercise_id, part.label)
                        )
                        if result
                        else None
                    )
                    cells.append(result_part)
                    if result_part and not (
                        result_part.exercise_part.answer_type
                        == ExerciseVariant.PartAnswerType.DOCUMENT_UPLOAD
                        and not result_part.is_manually_graded
                    ):
                        row_total += result_part.score
                rows.append({"student": student, "cells": cells, "row_total": row_total})
            tutorial_tables.append(
                {
                    "tutorial": tutorial,
                    "columns": exercise_parts,
                    "exercise_groups": exercise_groups,
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


class SupervisorCourseArchiveManageView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_course_archive_manage.html"

    def get(self, request, course_id):
        course = get_object_or_404(Course, pk=course_id)
        if not _user_can_access_course(request.user, course):
            raise PermissionDenied
        current_results_count = Result.objects.filter(
            course=course,
            archive_batch__isnull=True,
        ).count()
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
                "current_results_count": current_results_count,
                "archive_batches": archive_batches,
            },
        )


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
