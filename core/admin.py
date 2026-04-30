from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Course, Exercise, ExerciseVariant, Result, Tutorial, User


class TutorialInline(admin.TabularInline):
    model = Tutorial
    extra = 0
    fields = ("title", "order_index", "is_active")
    ordering = ("order_index", "id")


class ExerciseInline(admin.TabularInline):
    model = Exercise
    extra = 0
    fields = ("title", "order_index", "exercise_type", "is_active")
    ordering = ("order_index", "id")


class ExerciseVariantInline(admin.TabularInline):
    model = ExerciseVariant
    extra = 0
    fields = ("exercise_text", "available_points", "created_at")
    readonly_fields = ("created_at",)
    ordering = ("id",)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    model = User
    ordering = ("email",)
    list_display = ("email", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    search_fields = ("email",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Role", {"fields": ("role",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "role", "is_staff", "is_superuser", "is_active"),
            },
        ),
    )


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "created_by", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("title", "description", "created_by__email")
    ordering = ("title",)
    inlines = (TutorialInline,)


@admin.register(Tutorial)
class TutorialAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "order_index", "is_active", "created_at")
    list_filter = ("is_active", "course")
    search_fields = ("title", "description", "course__title", "course__created_by__email")
    ordering = ("course", "order_index", "title")
    inlines = (ExerciseInline,)


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ("title", "tutorial", "exercise_type", "order_index", "is_active", "created_at", "updated_at")
    list_filter = ("exercise_type", "is_active", "tutorial", "tutorial__course")
    search_fields = ("title", "tutorial__title", "tutorial__course__title", "tutorial__course__created_by__email")
    ordering = ("tutorial", "order_index", "title")
    inlines = (ExerciseVariantInline,)


@admin.register(ExerciseVariant)
class ExerciseVariantAdmin(admin.ModelAdmin):
    list_display = ("id", "exercise", "available_points", "created_at", "updated_at")
    list_filter = ("exercise__tutorial__course", "exercise__tutorial", "exercise__exercise_type", "exercise__is_active")
    search_fields = (
        "exercise__title",
        "exercise_text",
        "exercise__tutorial__title",
        "exercise__tutorial__course__title",
    )
    ordering = ("exercise", "id")


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "student",
        "course",
        "tutorial",
        "exercise",
        "score",
        "is_correct",
        "is_manually_graded",
        "is_archived",
        "submitted_at",
        "graded_at",
    )
    list_filter = (
        "course",
        "tutorial",
        "exercise__exercise_type",
        "exercise__is_active",
        "is_correct",
        "is_manually_graded",
        "is_archived",
    )
    search_fields = ("student__email", "graded_by__email", "exercise__title", "tutorial__title", "course__title")
    ordering = ("-submitted_at",)
