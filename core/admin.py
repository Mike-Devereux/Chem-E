from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Course, Exercise, ExerciseVariant, Tutorial, User


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
    list_display = ("title", "is_active", "created_by", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("title", "description", "created_by__email")
    ordering = ("title",)


@admin.register(Tutorial)
class TutorialAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "order_index", "is_active", "created_at")
    list_filter = ("is_active", "course")
    search_fields = ("title", "description", "course__title")
    ordering = ("course", "order_index", "title")


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ("title", "tutorial", "exercise_type", "order_index", "is_active", "created_at", "updated_at")
    list_filter = ("exercise_type", "is_active", "tutorial__course")
    search_fields = ("title", "tutorial__title", "tutorial__course__title")
    ordering = ("tutorial", "order_index", "title")


@admin.register(ExerciseVariant)
class ExerciseVariantAdmin(admin.ModelAdmin):
    list_display = ("id", "exercise", "available_points", "created_at", "updated_at")
    list_filter = ("exercise__tutorial__course", "exercise__exercise_type")
    search_fields = ("exercise__title", "exercise__tutorial__title", "exercise__tutorial__course__title")
    ordering = ("exercise", "id")
