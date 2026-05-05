from django.contrib.auth import views as auth_views
from django.urls import path

from .views import (
    CourseDetailView,
    CourseListView,
    ExerciseDetailView,
    RegisterView,
    SupervisorCourseSummaryView,
    SupervisorSubmissionFileDownloadView,
    SupervisorSubmissionDetailView,
    SupervisorExerciseSubmissionsView,
    TutorialDetailView,
)

urlpatterns = [
    path("", CourseListView.as_view(), name="home"),
    path("courses/<int:pk>/", CourseDetailView.as_view(), name="course_detail"),
    path("tutorials/<int:pk>/", TutorialDetailView.as_view(), name="tutorial_detail"),
    path("exercises/<int:pk>/", ExerciseDetailView.as_view(), name="exercise_detail"),
    path(
        "supervisor/exercises/<int:exercise_id>/submissions/",
        SupervisorExerciseSubmissionsView.as_view(),
        name="supervisor_exercise_submissions",
    ),
    path(
        "supervisor/submissions/<int:result_id>/",
        SupervisorSubmissionDetailView.as_view(),
        name="supervisor_submission_detail",
    ),
    path(
        "supervisor/submissions/<int:result_id>/file/",
        SupervisorSubmissionFileDownloadView.as_view(),
        name="supervisor_submission_file_download",
    ),
    path(
        "supervisor/courses/<int:course_id>/summary/",
        SupervisorCourseSummaryView.as_view(),
        name="supervisor_course_summary",
    ),
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
