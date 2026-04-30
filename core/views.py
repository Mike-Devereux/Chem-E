from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView

from .forms import RegistrationForm


class HomeView(TemplateView):
    template_name = "core/home.html"


class RegisterView(CreateView):
    form_class = RegistrationForm
    template_name = "core/register.html"
    success_url = reverse_lazy("login")
