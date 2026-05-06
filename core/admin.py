from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models import Q

from .models import (
    ArchiveBatch,
    Course,
    Exercise,
    ExercisePart,
    ExerciseVariant,
    Result,
    ResultPart,
    Tutorial,
    User,
)


class SupervisorOwnedContentAdmin(admin.ModelAdmin):
    def _is_supervisor(self, user):
        return user.is_authenticated and user.role == User.Role.SUPERVISOR

    def _is_administrator(self, user):
        return user.is_authenticated and (
            user.is_superuser or user.role == User.Role.ADMINISTRATOR
        )

    def _can_access_content_admin(self, user):
        return self._is_supervisor(user) or self._is_administrator(user)

    def get_supervisor_queryset(self, queryset, user):
        return queryset.none()

    def has_supervisor_object_access(self, user, obj):
        queryset = self.get_supervisor_queryset(self.model.objects.all(), user)
        return queryset.filter(pk=obj.pk).exists()

    def has_module_permission(self, request):
        return self._can_access_content_admin(request.user)

    def has_view_permission(self, request, obj=None):
        if not self._can_access_content_admin(request.user):
            return False
        if obj is None or self._is_administrator(request.user):
            return True
        return self.has_supervisor_object_access(request.user, obj)

    def has_add_permission(self, request):
        return self._can_access_content_admin(request.user)

    def has_change_permission(self, request, obj=None):
        if not self._can_access_content_admin(request.user):
            return False
        if obj is None or self._is_administrator(request.user):
            return True
        return self.has_supervisor_object_access(request.user, obj)

    def has_delete_permission(self, request, obj=None):
        if not self._can_access_content_admin(request.user):
            return False
        if obj is None or self._is_administrator(request.user):
            return True
        return self.has_supervisor_object_access(request.user, obj)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if self._is_administrator(request.user):
            return queryset
        if self._is_supervisor(request.user):
            return self.get_supervisor_queryset(queryset, request.user)
        return queryset.none()


class TutorialInline(admin.TabularInline):
    model = Tutorial
    extra = 0
    fields = ("title", "order_index", "is_active")
    ordering = ("order_index", "id")
    show_change_link = True


class ExerciseInline(admin.TabularInline):
    model = Exercise
    extra = 0
    fields = ("title", "order_index", "is_active")
    ordering = ("order_index", "id")
    show_change_link = True

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "is_active":
            formfield.label = "Active / unlocked"
            formfield.help_text = "Students can attempt this exercise when enabled."
        return formfield


class ExerciseVariantInline(admin.TabularInline):
    model = ExerciseVariant
    extra = 0
    fields = (
        "exercise_text",
        "image",
        "created_at",
    )
    readonly_fields = ("created_at",)
    ordering = ("id",)
    show_change_link = True


class ExercisePartInline(admin.TabularInline):
    model = ExercisePart
    extra = 0
    fields = (
        "label",
        "order_index",
        "answer_type",
        "prompt_text",
        "reference_solution",
        "absolute_tolerance",
        "available_points",
    )
    ordering = ("order_index", "id")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    model = User
    ordering = ("email",)
    list_display = ("email", "role", "is_active")
    list_filter = ("role", "is_active")
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

    def _is_administrator(self, user):
        return user.is_authenticated and (
            user.is_superuser or user.role == User.Role.ADMINISTRATOR
        )

    def has_module_permission(self, request):
        return self._is_administrator(request.user)

    def has_view_permission(self, request, obj=None):
        return self._is_administrator(request.user)

    def has_add_permission(self, request):
        return self._is_administrator(request.user)

    def has_change_permission(self, request, obj=None):
        return self._is_administrator(request.user)

    def has_delete_permission(self, request, obj=None):
        return self._is_administrator(request.user)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if self._is_administrator(request.user):
            return queryset
        return queryset.none()


@admin.register(Course)
class CourseAdmin(SupervisorOwnedContentAdmin):
    list_display = ("title", "created_by", "is_active")
    list_filter = ("is_active",)
    search_fields = ("title", "created_by__email")
    ordering = ("title",)
    inlines = (TutorialInline,)

    def get_supervisor_queryset(self, queryset, user):
        return queryset.filter(Q(created_by=user) | Q(supervisors=user)).distinct()

    def get_exclude(self, request, obj=None):
        if self._is_supervisor(request.user) and not self._is_administrator(request.user):
            return ("created_by",)
        return ()

    def save_model(self, request, obj, form, change):
        if not change and self._is_supervisor(request.user):
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        course = form.instance
        admin_users = User.objects.filter(
            Q(is_superuser=True) | Q(role=User.Role.ADMINISTRATOR)
        )
        for admin_user in admin_users.exclude(courses_supervised=course):
            course.supervisors.add(admin_user)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "supervisors":
            kwargs["queryset"] = User.objects.filter(
                Q(role=User.Role.SUPERVISOR)
                | Q(role=User.Role.ADMINISTRATOR)
                | Q(is_superuser=True)
            ).distinct()
        return super().formfield_for_manytomany(db_field, request, **kwargs)


@admin.register(Tutorial)
class TutorialAdmin(SupervisorOwnedContentAdmin):
    list_display = ("title", "course")
    list_filter = ("is_active", "course")
    search_fields = ("title", "course__title", "course__created_by__email")
    ordering = ("course", "order_index", "title")
    inlines = (ExerciseInline,)

    def get_supervisor_queryset(self, queryset, user):
        return queryset.filter(
            Q(course__created_by=user) | Q(course__supervisors=user)
        ).distinct()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "course" and self._is_supervisor(request.user):
            kwargs["queryset"] = Course.objects.filter(
                Q(created_by=request.user) | Q(supervisors=request.user)
            ).distinct()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Exercise)
class ExerciseAdmin(SupervisorOwnedContentAdmin):
    list_display = (
        "title",
        "tutorial",
        "order_index",
        "active_unlocked_status",
    )
    list_filter = ("is_active", "tutorial", "tutorial__course")
    search_fields = ("title", "tutorial__title", "tutorial__course__title")
    ordering = ("tutorial", "order_index", "title")
    inlines = (ExerciseVariantInline,)

    def get_supervisor_queryset(self, queryset, user):
        return queryset.filter(
            Q(tutorial__course__created_by=user) | Q(tutorial__course__supervisors=user)
        ).distinct()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "tutorial" and self._is_supervisor(request.user):
            kwargs["queryset"] = Tutorial.objects.filter(
                Q(course__created_by=request.user) | Q(course__supervisors=request.user)
            ).distinct()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "is_active":
            formfield.label = "Active / unlocked"
            formfield.help_text = "Students can attempt this exercise when enabled."
        return formfield

    @admin.display(boolean=True, ordering="is_active", description="Active / unlocked")
    def active_unlocked_status(self, obj):
        return obj.is_active


@admin.register(ExerciseVariant)
class ExerciseVariantAdmin(SupervisorOwnedContentAdmin):
    list_display = (
        "id",
        "exercise",
        "exercise_is_active",
        "created_at",
        "updated_at",
    )
    list_filter = (
        "exercise__is_active",
        "exercise__tutorial__course",
        "exercise__tutorial",
    )
    search_fields = (
        "exercise__title",
        "exercise_text",
        "exercise__tutorial__title",
        "exercise__tutorial__course__title",
    )
    ordering = ("exercise", "id")
    inlines = (ExercisePartInline,)

    def get_supervisor_queryset(self, queryset, user):
        return queryset.filter(
            Q(exercise__tutorial__course__created_by=user)
            | Q(exercise__tutorial__course__supervisors=user)
        ).distinct()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "exercise" and self._is_supervisor(request.user):
            kwargs["queryset"] = Exercise.objects.filter(
                Q(tutorial__course__created_by=request.user)
                | Q(tutorial__course__supervisors=request.user)
            ).distinct()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(ordering="exercise__is_active", description="Exercise active")
    def exercise_is_active(self, obj):
        return obj.exercise.is_active


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
        "archive_batch",
        "is_archived",
        "submitted_at",
    )
    list_filter = (
        "course",
        "tutorial",
        "exercise__is_active",
        "is_correct",
        "archive_batch",
        "is_archived",
    )
    search_fields = ("student__email", "exercise__title", "tutorial__title", "course__title")
    ordering = ("-submitted_at",)


@admin.register(ExercisePart)
class ExercisePartAdmin(SupervisorOwnedContentAdmin):
    list_display = ("variant", "label", "order_index", "answer_type", "available_points")
    list_filter = ("answer_type", "variant__exercise__tutorial__course")
    search_fields = ("label", "prompt_text", "variant__exercise__title")
    ordering = ("variant", "order_index", "id")

    def get_supervisor_queryset(self, queryset, user):
        return queryset.filter(
            Q(variant__exercise__tutorial__course__created_by=user)
            | Q(variant__exercise__tutorial__course__supervisors=user)
        ).distinct()


@admin.register(ResultPart)
class ResultPartAdmin(admin.ModelAdmin):
    list_display = (
        "result",
        "exercise_part",
        "score",
        "is_correct",
        "is_manually_graded",
        "submitted_at",
        "graded_at",
    )
    list_filter = ("exercise_part__answer_type", "result__course")
    search_fields = ("result__student__email", "exercise_part__label", "exercise_part__variant__exercise__title")
    ordering = ("-submitted_at", "-id")


@admin.register(ArchiveBatch)
class ArchiveBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "course", "note", "created_by", "created_at")
    list_filter = ("course", "created_at")
    search_fields = ("course__title", "created_by__email", "note")
    ordering = ("-created_at", "-id")
