import random
import os
from decimal import Decimal

from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404
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


class SupervisorLandingView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_landing.html"

    def get(self, request):
        courses = _courses_accessible_to_supervisor_or_admin(request.user)
        return render(
            request,
            self.template_name,
            {"courses": courses},
        )


class SupervisorCourseSummaryListView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_course_summary_list.html"

    def get(self, request):
        courses = _courses_accessible_to_supervisor_or_admin(request.user)
        return render(
            request,
            self.template_name,
            {"courses": courses},
        )


class SupervisorCourseManageListView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_course_manage_list.html"

    def get(self, request):
        courses = _courses_accessible_to_supervisor_or_admin(request.user)
        return render(
            request,
            self.template_name,
            {
                "courses": courses,
                "course_form": CourseEditForm(),
            },
        )

    def post(self, request):
        courses = _courses_accessible_to_supervisor_or_admin(request.user)
        form = CourseEditForm(request.POST)
        if form.is_valid():
            course = form.save(commit=False)
            course.created_by = request.user
            course.save()
            return redirect("supervisor_course_manage_detail", course_id=course.id)
        return render(
            request,
            self.template_name,
            {
                "courses": courses,
                "course_form": form,
            },
        )


class SupervisorCourseManageDetailView(SupervisorRequiredMixin, DetailView):
    model = Course
    template_name = "core/supervisor_course_manage_detail.html"
    context_object_name = "course"
    pk_url_kwarg = "course_id"

    def get_context_data(self, **kwargs):
        _assert_user_can_manage_course(self.request.user, self.object)
        context = super().get_context_data(**kwargs)
        context["tutorials"] = self.object.tutorials.order_by("order_index", "id")
        return context


class SupervisorCourseEditView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_simple_form.html"

    def _get_course(self, course_id):
        course = get_object_or_404(Course, pk=course_id)
        _assert_user_can_manage_course(self.request.user, course)
        return course

    def get(self, request, course_id):
        course = self._get_course(course_id)
        form = CourseEditForm(instance=course)
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Edit course: {course.title}", "cancel_url": reverse_lazy("supervisor_course_manage_detail", kwargs={"course_id": course.id})},
        )

    def post(self, request, course_id):
        course = self._get_course(course_id)
        form = CourseEditForm(request.POST, instance=course)
        if form.is_valid():
            form.save()
            return redirect("supervisor_course_manage_detail", course_id=course.id)
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Edit course: {course.title}", "cancel_url": reverse_lazy("supervisor_course_manage_detail", kwargs={"course_id": course.id})},
        )


class SupervisorTutorialCreateView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_simple_form.html"

    def _get_course(self, course_id):
        course = get_object_or_404(Course, pk=course_id)
        _assert_user_can_manage_course(self.request.user, course)
        return course

    def get(self, request, course_id):
        course = self._get_course(course_id)
        form = TutorialEditForm(
            course=course,
            initial={"order_index": _next_order_index(course.tutorials.all())},
        )
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Create tutorial in {course.title}", "cancel_url": reverse_lazy("supervisor_course_manage_detail", kwargs={"course_id": course.id})},
        )

    def post(self, request, course_id):
        course = self._get_course(course_id)
        form = TutorialEditForm(request.POST, course=course)
        if form.is_valid():
            tutorial = form.save(commit=False)
            tutorial.course = course
            try:
                with transaction.atomic():
                    tutorial.save()
            except IntegrityError:
                form.add_error("order_index", "This order index is already used in this course.")
            else:
                return redirect("supervisor_course_manage_detail", course_id=course.id)
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Create tutorial in {course.title}", "cancel_url": reverse_lazy("supervisor_course_manage_detail", kwargs={"course_id": course.id})},
        )


class SupervisorTutorialManageDetailView(SupervisorRequiredMixin, DetailView):
    model = Tutorial
    template_name = "core/supervisor_tutorial_manage_detail.html"
    context_object_name = "tutorial"
    pk_url_kwarg = "tutorial_id"

    def get_context_data(self, **kwargs):
        _assert_user_can_manage_course(self.request.user, self.object.course)
        context = super().get_context_data(**kwargs)
        context["exercises"] = self.object.exercises.order_by("order_index", "id")
        return context


class SupervisorTutorialEditView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_simple_form.html"

    def _get_tutorial(self, tutorial_id):
        tutorial = get_object_or_404(Tutorial, pk=tutorial_id)
        _assert_user_can_manage_course(self.request.user, tutorial.course)
        return tutorial

    def get(self, request, tutorial_id):
        tutorial = self._get_tutorial(tutorial_id)
        form = TutorialEditForm(instance=tutorial, course=tutorial.course)
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Edit tutorial: {tutorial.title}", "cancel_url": reverse_lazy("supervisor_tutorial_manage_detail", kwargs={"tutorial_id": tutorial.id})},
        )

    def post(self, request, tutorial_id):
        tutorial = self._get_tutorial(tutorial_id)
        form = TutorialEditForm(request.POST, instance=tutorial, course=tutorial.course)
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
            except IntegrityError:
                form.add_error("order_index", "This order index is already used in this course.")
            else:
                return redirect("supervisor_tutorial_manage_detail", tutorial_id=tutorial.id)
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Edit tutorial: {tutorial.title}", "cancel_url": reverse_lazy("supervisor_tutorial_manage_detail", kwargs={"tutorial_id": tutorial.id})},
        )


class SupervisorExerciseCreateView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_simple_form.html"

    def _get_tutorial(self, tutorial_id):
        tutorial = get_object_or_404(Tutorial, pk=tutorial_id)
        _assert_user_can_manage_course(self.request.user, tutorial.course)
        return tutorial

    def get(self, request, tutorial_id):
        tutorial = self._get_tutorial(tutorial_id)
        form = ExerciseEditForm(
            tutorial=tutorial,
            initial={"order_index": _next_order_index(tutorial.exercises.all())},
        )
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Create exercise in {tutorial.title}", "cancel_url": reverse_lazy("supervisor_tutorial_manage_detail", kwargs={"tutorial_id": tutorial.id})},
        )

    def post(self, request, tutorial_id):
        tutorial = self._get_tutorial(tutorial_id)
        form = ExerciseEditForm(request.POST, tutorial=tutorial)
        if form.is_valid():
            exercise = form.save(commit=False)
            exercise.tutorial = tutorial
            try:
                with transaction.atomic():
                    exercise.save()
            except IntegrityError:
                form.add_error(
                    "order_index",
                    "This order index is already used in this tutorial.",
                )
            else:
                return redirect("supervisor_tutorial_manage_detail", tutorial_id=tutorial.id)
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Create exercise in {tutorial.title}", "cancel_url": reverse_lazy("supervisor_tutorial_manage_detail", kwargs={"tutorial_id": tutorial.id})},
        )


class SupervisorExerciseManageDetailView(SupervisorRequiredMixin, DetailView):
    model = Exercise
    template_name = "core/supervisor_exercise_manage_detail.html"
    context_object_name = "exercise"
    pk_url_kwarg = "exercise_id"

    def get_context_data(self, **kwargs):
        _assert_user_can_manage_course(self.request.user, self.object.tutorial.course)
        context = super().get_context_data(**kwargs)
        context["variants"] = self.object.variants.order_by("id")
        return context


class SupervisorExerciseEditView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_simple_form.html"

    def _get_exercise(self, exercise_id):
        exercise = get_object_or_404(Exercise, pk=exercise_id)
        _assert_user_can_manage_course(self.request.user, exercise.tutorial.course)
        return exercise

    def get(self, request, exercise_id):
        exercise = self._get_exercise(exercise_id)
        form = ExerciseEditForm(instance=exercise, tutorial=exercise.tutorial)
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Edit exercise: {exercise.title}", "cancel_url": reverse_lazy("supervisor_exercise_manage_detail", kwargs={"exercise_id": exercise.id})},
        )

    def post(self, request, exercise_id):
        exercise = self._get_exercise(exercise_id)
        form = ExerciseEditForm(
            request.POST,
            instance=exercise,
            tutorial=exercise.tutorial,
        )
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
            except IntegrityError:
                form.add_error(
                    "order_index",
                    "This order index is already used in this tutorial.",
                )
            else:
                return redirect("supervisor_exercise_manage_detail", exercise_id=exercise.id)
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Edit exercise: {exercise.title}", "cancel_url": reverse_lazy("supervisor_exercise_manage_detail", kwargs={"exercise_id": exercise.id})},
        )


class SupervisorExerciseVariantCreateView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_simple_form.html"

    def _get_exercise(self, exercise_id):
        exercise = get_object_or_404(Exercise, pk=exercise_id)
        _assert_user_can_manage_course(self.request.user, exercise.tutorial.course)
        return exercise

    def get(self, request, exercise_id):
        exercise = self._get_exercise(exercise_id)
        form = ExerciseVariantEditForm()
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Create variant for {exercise.title}", "cancel_url": reverse_lazy("supervisor_exercise_manage_detail", kwargs={"exercise_id": exercise.id})},
        )

    def post(self, request, exercise_id):
        exercise = self._get_exercise(exercise_id)
        form = ExerciseVariantEditForm(request.POST, request.FILES)
        if form.is_valid():
            variant = form.save(commit=False)
            variant.exercise = exercise
            variant.save()
            return redirect("supervisor_exercise_manage_detail", exercise_id=exercise.id)
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Create variant for {exercise.title}", "cancel_url": reverse_lazy("supervisor_exercise_manage_detail", kwargs={"exercise_id": exercise.id})},
        )


class SupervisorExerciseVariantEditView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_simple_form.html"

    def _get_variant(self, variant_id):
        variant = get_object_or_404(ExerciseVariant, pk=variant_id)
        _assert_user_can_manage_course(self.request.user, variant.exercise.tutorial.course)
        return variant

    def get(self, request, variant_id):
        variant = self._get_variant(variant_id)
        form = ExerciseVariantEditForm(instance=variant)
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Edit variant {variant.id}", "cancel_url": reverse_lazy("supervisor_exercise_manage_detail", kwargs={"exercise_id": variant.exercise_id})},
        )

    def post(self, request, variant_id):
        variant = self._get_variant(variant_id)
        form = ExerciseVariantEditForm(request.POST, request.FILES, instance=variant)
        if form.is_valid():
            form.save()
            return redirect("supervisor_exercise_manage_detail", exercise_id=variant.exercise_id)
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Edit variant {variant.id}", "cancel_url": reverse_lazy("supervisor_exercise_manage_detail", kwargs={"exercise_id": variant.exercise_id})},
        )


class SupervisorExerciseVariantManageDetailView(SupervisorRequiredMixin, DetailView):
    model = ExerciseVariant
    template_name = "core/supervisor_exercise_variant_manage_detail.html"
    context_object_name = "variant"
    pk_url_kwarg = "variant_id"

    def get_context_data(self, **kwargs):
        _assert_user_can_manage_course(self.request.user, self.object.exercise.tutorial.course)
        context = super().get_context_data(**kwargs)
        context["parts"] = self.object.parts.order_by("order_index", "id")
        return context


class SupervisorExercisePartCreateView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_simple_form.html"

    def _get_variant(self, variant_id):
        variant = get_object_or_404(ExerciseVariant, pk=variant_id)
        _assert_user_can_manage_course(self.request.user, variant.exercise.tutorial.course)
        return variant

    def get(self, request, variant_id):
        variant = self._get_variant(variant_id)
        form = ExercisePartEditForm(
            variant=variant,
            initial={"order_index": _next_order_index(variant.parts.all())},
        )
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "title": f"Create part for variant {variant.id}",
                "cancel_url": reverse_lazy(
                    "supervisor_exercise_variant_manage_detail",
                    kwargs={"variant_id": variant.id},
                ),
            },
        )

    def post(self, request, variant_id):
        variant = self._get_variant(variant_id)
        form = ExercisePartEditForm(request.POST, variant=variant)
        if form.is_valid():
            part = form.save(commit=False)
            part.variant = variant
            try:
                with transaction.atomic():
                    part.save()
            except IntegrityError:
                form.add_error("order_index", "This order index is already used in this variant.")
            else:
                return redirect("supervisor_exercise_variant_manage_detail", variant_id=variant.id)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "title": f"Create part for variant {variant.id}",
                "cancel_url": reverse_lazy(
                    "supervisor_exercise_variant_manage_detail",
                    kwargs={"variant_id": variant.id},
                ),
            },
        )


class SupervisorExercisePartEditView(SupervisorRequiredMixin, View):
    template_name = "core/supervisor_simple_form.html"

    def _get_part(self, part_id):
        part = get_object_or_404(ExercisePart, pk=part_id)
        _assert_user_can_manage_course(self.request.user, part.variant.exercise.tutorial.course)
        return part

    def get(self, request, part_id):
        part = self._get_part(part_id)
        form = ExercisePartEditForm(instance=part, variant=part.variant)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "title": f"Edit part {part.label}",
                "cancel_url": reverse_lazy(
                    "supervisor_exercise_variant_manage_detail",
                    kwargs={"variant_id": part.variant_id},
                ),
            },
        )

    def post(self, request, part_id):
        part = self._get_part(part_id)
        form = ExercisePartEditForm(request.POST, instance=part, variant=part.variant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
            except IntegrityError:
                form.add_error("order_index", "This order index is already used in this variant.")
            else:
                return redirect("supervisor_exercise_variant_manage_detail", variant_id=part.variant_id)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "title": f"Edit part {part.label}",
                "cancel_url": reverse_lazy(
                    "supervisor_exercise_variant_manage_detail",
                    kwargs={"variant_id": part.variant_id},
                ),
            },
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
        context["exercises"] = self.object.exercises.filter(is_active=True).order_by(
            "order_index", "id"
        )
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

        exercises_queryset = Exercise.objects.filter(
            tutorial__course=self.object,
            is_active=True,
        )
        if selected_tutorial:
            exercises_queryset = exercises_queryset.filter(tutorial=selected_tutorial)
        exercises = list(
            exercises_queryset.select_related("tutorial").order_by(
                "tutorial__order_index", "tutorial_id", "order_index", "id"
            )
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
        for result in results:
            upload_part = _result_upload_part(result)
            result.display_is_manually_graded = _result_display_is_graded(result)
            result.display_has_submission = _result_has_submission_data(result)
            result.display_uploaded_file = upload_part.uploaded_file if upload_part else None

        results_by_student_exercise = {
            student.id: {exercise.id: None for exercise in exercises} for student in students
        }
        for result in results:
            student_results = results_by_student_exercise.setdefault(result.student_id, {})
            student_results[result.exercise_id] = result

        summary_rows = []
        for student in students:
            exercise_results = results_by_student_exercise.get(student.id, {})
            cells = [exercise_results.get(exercise.id) for exercise in exercises]
            summary_rows.append({"student": student, "cells": cells})

        context["exercises"] = exercises
        context["students"] = students
        context["results"] = results
        context["results_by_student_exercise"] = results_by_student_exercise
        context["summary_rows"] = summary_rows
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
