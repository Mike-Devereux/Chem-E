import random
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView

from .forms import NumericalAnswerForm, RegistrationForm
from .grading import is_numerical_answer_correct
from .models import Course, Exercise, Result, Tutorial, User


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
        else:
            context["variant"] = self.object.variants.order_by("id").first()
        if self.object.exercise_type == Exercise.ExerciseType.NUMERICAL:
            context["numerical_form"] = kwargs.get("numerical_form") or NumericalAnswerForm()
        return context

    def _get_or_assign_student_result(self):
        variants = list(self.object.variants.order_by("id"))
        if not variants:
            return None

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
        return result

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
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
                result.save(
                    update_fields=[
                        "submitted_numerical_value",
                        "is_correct",
                        "score",
                        "submitted_at",
                    ]
                )
            context = self.get_context_data(
                numerical_form=NumericalAnswerForm(),
                submission_received=True,
                submitted_value=form.cleaned_data["submitted_value"],
                is_correct=is_correct,
            )
            return self.render_to_response(context)
        return self.render_to_response(self.get_context_data(numerical_form=form))


class RegisterView(CreateView):
    form_class = RegistrationForm
    template_name = "core/register.html"
    success_url = reverse_lazy("login")
