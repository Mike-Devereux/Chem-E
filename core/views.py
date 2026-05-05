import random
import os
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.db import IntegrityError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView

from .access import SupervisorRequiredMixin
from .forms import (
    ManualUploadGradingForm,
    NumericalAnswerForm,
    RegistrationForm,
    UploadSubmissionForm,
)
from .grading import is_numerical_answer_correct
from .models import Course, Exercise, Result, Tutorial, User


def _user_can_access_course(user, course):
    if user.is_superuser or user.role == User.Role.ADMINISTRATOR:
        return True
    if user.role != User.Role.SUPERVISOR:
        return False
    return course.supervisors.filter(id=user.id).exists()


class CourseListView(LoginRequiredMixin, ListView):
    model = Course
    template_name = "core/course_list.html"
    context_object_name = "courses"

    def get_queryset(self):
        return Course.objects.filter(is_active=True).order_by("title")


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
        if self.request.user.role == User.Role.STUDENT:
            result = self._get_or_assign_student_result()
            context["variant"] = result.assigned_variant if result else None
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
            context["variant"] = self.object.variants.order_by("id").first()
        if self.object.exercise_type == Exercise.ExerciseType.NUMERICAL:
            context["numerical_form"] = kwargs.get("numerical_form") or NumericalAnswerForm()
        elif self.object.exercise_type == Exercise.ExerciseType.DOCUMENT_UPLOAD:
            context["upload_form"] = kwargs.get("upload_form") or UploadSubmissionForm()
        return context

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
        if not _user_can_access_course(self.request.user, self.object.tutorial.course):
            raise PermissionDenied
        context = super().get_context_data(**kwargs)
        submissions = Result.objects.filter(exercise=self.object).select_related("student")
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

    def get_context_data(self, **kwargs):
        if not _user_can_access_course(self.request.user, self.object.course):
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
        if not _user_can_access_course(request.user, self.object.course):
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
        submission = get_object_or_404(Result, pk=result_id)
        if not _user_can_access_course(request.user, submission.course):
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
            Result.objects.filter(course=self.object, exercise_id__in=exercise_ids)
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


class RegisterView(CreateView):
    form_class = RegistrationForm
    template_name = "core/register.html"
    success_url = reverse_lazy("login")
