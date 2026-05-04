from django.contrib.auth.forms import UserCreationForm
from django import forms

from .models import User


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
