from django.contrib.auth.forms import UserCreationForm
from django import forms

from .html_sanitizer import sanitize_rich_text
from .models import Course, Exercise, ExercisePart, ExerciseVariant, Tutorial, User
from .numeric_parsing import parse_decimal_value, parse_float_value
from .validators import validate_student_submission_file


class RegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email",)


class NumericalAnswerForm(forms.Form):
    submitted_value = forms.CharField(
        label="Your numerical answer",
    )

    def clean_submitted_value(self):
        try:
            return parse_decimal_value(self.cleaned_data["submitted_value"])
        except ValueError as exc:
            raise forms.ValidationError(str(exc))


class UploadSubmissionForm(forms.Form):
    uploaded_file = forms.FileField(
        label="Upload your solution file",
        validators=[validate_student_submission_file],
    )


class ManualUploadGradingForm(forms.Form):
    score = forms.DecimalField(
        min_value=0,
        max_digits=8,
        decimal_places=2,
    )
    feedback = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class CourseEditForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ("title", "description", "is_active")


class TutorialEditForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.course = kwargs.pop("course", None)
        super().__init__(*args, **kwargs)
        if self.course is None and self.instance and self.instance.pk:
            self.course = self.instance.course

    def clean_order_index(self):
        order_index = self.cleaned_data["order_index"]
        if self.course is None:
            return order_index
        queryset = Tutorial.objects.filter(course=self.course, order_index=order_index)
        if self.instance and self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError(
                "This order index is already used in this course."
            )
        return order_index

    class Meta:
        model = Tutorial
        fields = ("title", "description", "order_index", "is_active")


class ExerciseEditForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.tutorial = kwargs.pop("tutorial", None)
        super().__init__(*args, **kwargs)
        if self.tutorial is None and self.instance and self.instance.pk:
            self.tutorial = self.instance.tutorial

    def clean_order_index(self):
        order_index = self.cleaned_data["order_index"]
        if self.tutorial is None:
            return order_index
        queryset = Exercise.objects.filter(tutorial=self.tutorial, order_index=order_index)
        if self.instance and self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError(
                "This order index is already used in this tutorial."
            )
        return order_index

    class Meta:
        model = Exercise
        fields = ("title", "order_index", "is_active")


class ExerciseVariantEditForm(forms.ModelForm):
    def clean_exercise_text(self):
        return sanitize_rich_text(self.cleaned_data.get("exercise_text", ""))

    class Meta:
        model = ExerciseVariant
        fields = (
            "exercise_text",
            "image",
            "supervisor_notes",
        )


class ExercisePartEditForm(forms.ModelForm):
    reference_solution = forms.CharField(required=False)
    absolute_tolerance = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        self.variant = kwargs.pop("variant", None)
        super().__init__(*args, **kwargs)
        if self.variant is None and self.instance and self.instance.pk:
            self.variant = self.instance.variant

    def clean_order_index(self):
        order_index = self.cleaned_data["order_index"]
        if self.variant is None:
            return order_index
        queryset = ExercisePart.objects.filter(variant=self.variant, order_index=order_index)
        if self.instance and self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError(
                "This order index is already used in this variant."
            )
        return order_index

    def clean_reference_solution(self):
        value = self.cleaned_data.get("reference_solution")
        if value in (None, ""):
            return None
        try:
            return parse_float_value(value)
        except ValueError as exc:
            raise forms.ValidationError(str(exc))

    def clean_absolute_tolerance(self):
        value = self.cleaned_data.get("absolute_tolerance")
        if value in (None, ""):
            return None
        try:
            return parse_float_value(value)
        except ValueError as exc:
            raise forms.ValidationError(str(exc))

    def clean_prompt_text(self):
        return sanitize_rich_text(self.cleaned_data.get("prompt_text", ""))

    class Meta:
        model = ExercisePart
        fields = (
            "label",
            "order_index",
            "answer_type",
            "prompt_text",
            "reference_solution",
            "absolute_tolerance",
            "available_points",
        )
