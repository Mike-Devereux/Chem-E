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
        return render(request, self.template_name, {"courses": courses})


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
        form = TutorialEditForm()
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Create tutorial in {course.title}", "cancel_url": reverse_lazy("supervisor_course_manage_detail", kwargs={"course_id": course.id})},
        )

    def post(self, request, course_id):
        course = self._get_course(course_id)
        form = TutorialEditForm(request.POST)
        if form.is_valid():
            tutorial = form.save(commit=False)
            tutorial.course = course
            tutorial.save()
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
        form = TutorialEditForm(instance=tutorial)
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Edit tutorial: {tutorial.title}", "cancel_url": reverse_lazy("supervisor_tutorial_manage_detail", kwargs={"tutorial_id": tutorial.id})},
        )

    def post(self, request, tutorial_id):
        tutorial = self._get_tutorial(tutorial_id)
        form = TutorialEditForm(request.POST, instance=tutorial)
        if form.is_valid():
            form.save()
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
        form = ExerciseEditForm()
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Create exercise in {tutorial.title}", "cancel_url": reverse_lazy("supervisor_tutorial_manage_detail", kwargs={"tutorial_id": tutorial.id})},
        )

    def post(self, request, tutorial_id):
        tutorial = self._get_tutorial(tutorial_id)
        form = ExerciseEditForm(request.POST)
        if form.is_valid():
            exercise = form.save(commit=False)
            exercise.tutorial = tutorial
            exercise.save()
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
        form = ExerciseEditForm(instance=exercise)
        return render(
            request,
            self.template_name,
            {"form": form, "title": f"Edit exercise: {exercise.title}", "cancel_url": reverse_lazy("supervisor_exercise_manage_detail", kwargs={"exercise_id": exercise.id})},
        )

    def post(self, request, exercise_id):
        exercise = self._get_exercise(exercise_id)
        form = ExerciseEditForm(request.POST, instance=exercise)
        if form.is_valid():
            form.save()
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
                and (
                    result.submitted_numerical_value is not None
                    or bool(result.uploaded_file)
                )
                else None
            )
        else:
            variant = self.object.variants.order_by("id").first()
            context["variant"] = variant
        context["parts"] = variant.parts.order_by("order_index", "id") if variant else []
        if self.object.exercise_type == Exercise.ExerciseType.NUMERICAL:
            context["numerical_form"] = kwargs.get("numerical_form") or NumericalAnswerForm()
        elif self.object.exercise_type == Exercise.ExerciseType.DOCUMENT_UPLOAD:
            context["upload_form"] = kwargs.get("upload_form") or UploadSubmissionForm()
        return context

    def _ensure_default_part_for_variant(self, variant):
        part = variant.parts.order_by("order_index", "id").first()
        if part:
            return part
        answer_type = (
            ExerciseVariant.PartAnswerType.DOCUMENT_UPLOAD
            if variant.exercise.exercise_type == Exercise.ExerciseType.DOCUMENT_UPLOAD
            else ExerciseVariant.PartAnswerType.NUMERICAL
        )
        return ExercisePart.objects.create(
            variant=variant,
            label="a",
            prompt_text="",
            answer_type=answer_type,
            reference_solution=variant.reference_solution,
            absolute_tolerance=variant.absolute_tolerance,
            available_points=variant.available_points,
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
        if self.object.exercise_type == Exercise.ExerciseType.DOCUMENT_UPLOAD:
            form = UploadSubmissionForm(request.POST, request.FILES)
            if form.is_valid() and self.request.user.role == User.Role.STUDENT:
                result = self._get_or_assign_student_result()
                if result.is_manually_graded:
                    form.add_error(
                        None,
                        "This submission has already been manually graded and cannot be replaced.",
                    )
                    return self.render_to_response(self.get_context_data(upload_form=form))

                old_file_name = result.uploaded_file.name if result.uploaded_file else None
                result.uploaded_file = form.cleaned_data["uploaded_file"]
                result.submitted_at = timezone.now()
                result.score = Decimal("0")
                result.is_correct = None
                result.is_manually_graded = False
                result.submitted_numerical_value = None
                result.save(
                    update_fields=[
                        "uploaded_file",
                        "submitted_at",
                        "score",
                        "is_correct",
                        "is_manually_graded",
                        "submitted_numerical_value",
                    ]
                )
                upload_part = (
                    result.assigned_variant.parts.filter(
                        answer_type=ExerciseVariant.PartAnswerType.DOCUMENT_UPLOAD
                    )
                    .order_by("order_index", "id")
                    .first()
                    or self._ensure_default_part_for_variant(result.assigned_variant)
                )
                ResultPart.objects.update_or_create(
                    result=result,
                    exercise_part=upload_part,
                    defaults={
                        "submitted_numerical_value": None,
                        "uploaded_file": result.uploaded_file,
                        "is_correct": None,
                        "score": Decimal("0"),
                    },
                )
                result.recompute_total_score()
                result.save(update_fields=["score"])
                # Delete the previous upload only after new save succeeds.
                if old_file_name and old_file_name != result.uploaded_file.name:
                    if default_storage.exists(old_file_name):
                        default_storage.delete(old_file_name)
                return self.render_to_response(
                    self.get_context_data(upload_form=UploadSubmissionForm())
                )
            return self.render_to_response(self.get_context_data(upload_form=form))

        if self.object.exercise_type != Exercise.ExerciseType.NUMERICAL:
            return self.render_to_response(self.get_context_data())

        form = NumericalAnswerForm(request.POST)
        if form.is_valid():
            result = None
            variant = (
                (result := self._get_or_assign_student_result()).assigned_variant
                if self.request.user.role == User.Role.STUDENT
                else self.object.variants.order_by("id").first()
            )
            is_correct = None
            if (
                variant
                and variant.reference_solution is not None
                and variant.absolute_tolerance is not None
            ):
                is_correct = is_numerical_answer_correct(
                    submitted_value=form.cleaned_data["submitted_value"],
                    reference_solution=variant.reference_solution,
                    absolute_tolerance=variant.absolute_tolerance,
                )
            if result and is_correct is not None:
                result.submitted_numerical_value = form.cleaned_data["submitted_value"]
                result.is_correct = is_correct
                result.score = variant.available_points if is_correct else Decimal("0")
                result.submitted_at = timezone.now()
                # Numerical submissions are auto-graded immediately.
                result.is_manually_graded = True
                result.graded_at = timezone.now()
                result.graded_by = None
                result.save(
                    update_fields=[
                        "submitted_numerical_value",
                        "is_correct",
                        "score",
                        "submitted_at",
                        "is_manually_graded",
                        "graded_at",
                        "graded_by",
                    ]
                )
                numerical_part = (
                    variant.parts.filter(answer_type=ExerciseVariant.PartAnswerType.NUMERICAL)
                    .order_by("order_index", "id")
                    .first()
                    or self._ensure_default_part_for_variant(variant)
                )
                ResultPart.objects.update_or_create(
                    result=result,
                    exercise_part=numerical_part,
                    defaults={
                        "submitted_numerical_value": form.cleaned_data["submitted_value"],
                        "uploaded_file": None,
                        "is_correct": is_correct,
                        "score": variant.available_points if is_correct else Decimal("0"),
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
            submissions = submissions.filter(is_manually_graded=True)
        elif status_filter == "ungraded":
            submissions = submissions.filter(is_manually_graded=False)
        context["status_filter"] = status_filter or "all"
        context["submissions"] = submissions.order_by("-submitted_at", "-id")
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
        if self.object.exercise.exercise_type == Exercise.ExerciseType.DOCUMENT_UPLOAD:
            initial = {
                "score": self.object.score,
                "feedback": self.object.feedback,
            }
            context["grading_form"] = kwargs.get("grading_form") or ManualUploadGradingForm(
                initial=initial
            )
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if not _user_can_access_course_results(request.user, self.object.course):
            raise PermissionDenied
        if self.object.exercise.exercise_type != Exercise.ExerciseType.DOCUMENT_UPLOAD:
            return self.render_to_response(self.get_context_data())

        form = ManualUploadGradingForm(request.POST)
        if form.is_valid():
            self.object.score = form.cleaned_data["score"]
            self.object.feedback = form.cleaned_data["feedback"]
            self.object.is_manually_graded = True
            self.object.graded_by = request.user
            self.object.graded_at = timezone.now()
            self.object.save(
                update_fields=[
                    "score",
                    "feedback",
                    "is_manually_graded",
                    "graded_by",
                    "graded_at",
                ]
            )
            return self.render_to_response(self.get_context_data())
        return self.render_to_response(self.get_context_data(grading_form=form))


class SupervisorSubmissionFileDownloadView(SupervisorRequiredMixin, View):
    def get(self, request, result_id):
        submission = get_object_or_404(Result, pk=result_id, archive_batch__isnull=True)
        if not _user_can_access_course_results(request.user, submission.course):
            raise PermissionDenied
        if not submission.uploaded_file:
            raise Http404("No uploaded file for this submission.")
        return FileResponse(
            submission.uploaded_file.open("rb"),
            as_attachment=True,
            filename=os.path.basename(submission.uploaded_file.name),
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
        context["results"] = self.object.results.select_related(
            "student", "exercise", "tutorial"
        ).order_by("-submitted_at", "-id")
        return context


class SupervisorArchivedSubmissionFileDownloadView(SupervisorRequiredMixin, View):
    def get(self, request, result_id):
        submission = get_object_or_404(Result, pk=result_id, archive_batch__isnull=False)
        if not _user_can_access_course(request.user, submission.course):
            raise PermissionDenied
        if not submission.uploaded_file:
            raise Http404("No uploaded file for this submission.")
        return FileResponse(
            submission.uploaded_file.open("rb"),
            as_attachment=True,
            filename=os.path.basename(submission.uploaded_file.name),
        )


class RegisterView(CreateView):
    form_class = RegistrationForm
    template_name = "core/register.html"
    success_url = reverse_lazy("login")
