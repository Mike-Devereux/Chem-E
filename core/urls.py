from django.contrib.auth import views as auth_views
from django.urls import path

from .views import (
    CourseDetailView,
    CourseListView,
    ExerciseDetailView,
    RegisterView,
    TutorialDetailView,
)

urlpatterns = [
    path("", CourseListView.as_view(), name="home"),
    path("courses/<int:pk>/", CourseDetailView.as_view(), name="course_detail"),
    path("tutorials/<int:pk>/", TutorialDetailView.as_view(), name="tutorial_detail"),
    path("exercises/<int:pk>/", ExerciseDetailView.as_view(), name="exercise_detail"),
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="/login/"), name="logout"),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]
