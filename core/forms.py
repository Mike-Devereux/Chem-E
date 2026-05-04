from django.contrib.auth.forms import UserCreationForm
from django import forms

from .models import User
from .validators import validate_student_submission_file


class RegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email",)


class NumericalAnswerForm(forms.Form):
    submitted_value = forms.DecimalField(
        label="Your numerical answer",
        decimal_places=4,
        max_digits=12,
    )


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
