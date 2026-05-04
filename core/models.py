from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models

from .validators import validate_student_submission_file, validate_university_email_domain


class UserManager(BaseUserManager):
    """Manager for custom user model using email as identifier."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        role = extra_fields.setdefault("role", User.Role.STUDENT)
        if role in {User.Role.SUPERVISOR, User.Role.ADMINISTRATOR}:
            extra_fields.setdefault("is_staff", True)
        else:
            extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMINISTRATOR)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        SUPERVISOR = "supervisor", "Supervisor"
        ADMINISTRATOR = "administrator", "Administrator"

    username = None
    email = models.EmailField(unique=True, validators=[validate_university_email_domain])
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def save(self, *args, **kwargs):
        # Keep admin login eligibility aligned with role-based access.
        if self.is_superuser:
            self.is_staff = True
        elif self.role in {self.Role.SUPERVISOR, self.Role.ADMINISTRATOR}:
            self.is_staff = True
        else:
            self.is_staff = False
        super().save(*args, **kwargs)


class Course(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "core.User",
        on_delete=models.PROTECT,
        related_name="courses_created",
    )
    supervisors = models.ManyToManyField(
        "core.User",
        related_name="courses_supervised",
        blank=True,
    )

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.created_by_id:
            self.supervisors.add(self.created_by)


class Tutorial(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="tutorials",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    order_index = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["course_id", "order_index", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "order_index"],
                name="core_tutorial_unique_order_per_course",
            )
        ]

    def __str__(self):
        return f"{self.course.title} - {self.title}"


class Exercise(models.Model):
    class ExerciseType(models.TextChoices):
        NUMERICAL = "numerical", "Numerical"
        DOCUMENT_UPLOAD = "document_upload", "Document upload"

    tutorial = models.ForeignKey(
        Tutorial,
        on_delete=models.CASCADE,
        related_name="exercises",
    )
    title = models.CharField(max_length=200)
    order_index = models.PositiveIntegerField()
    exercise_type = models.CharField(
        max_length=20,
        choices=ExerciseType.choices,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tutorial_id", "order_index", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tutorial", "order_index"],
                name="core_exercise_unique_order_per_tutorial",
            )
        ]

    def __str__(self):
        return f"{self.tutorial.title} - {self.title}"

    def clean(self):
        super().clean()
        valid_types = {self.ExerciseType.NUMERICAL, self.ExerciseType.DOCUMENT_UPLOAD}
        if self.exercise_type not in valid_types:
            raise ValidationError(
                {"exercise_type": "Exercise type must be either numerical or document_upload."}
            )


class ExerciseVariant(models.Model):
    exercise = models.ForeignKey(
        Exercise,
        on_delete=models.CASCADE,
        related_name="variants",
    )
    exercise_text = models.TextField()
    image = models.ImageField(upload_to="exercise_variants/images/", blank=True, null=True)
    reference_solution = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    absolute_tolerance = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    available_points = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    supervisor_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["exercise_id", "id"]

    def __str__(self):
        return f"{self.exercise.title} - Variant {self.id}"

    def clean(self):
        super().clean()
        errors = {}

        if self.available_points is not None and self.available_points < 0:
            errors["available_points"] = "Available points must be non-negative."
        if self.absolute_tolerance is not None and self.absolute_tolerance < 0:
            errors["absolute_tolerance"] = "Tolerance must be non-negative."

        if self.exercise_id and self.exercise.exercise_type == Exercise.ExerciseType.NUMERICAL:
            if self.reference_solution is None:
                errors["reference_solution"] = (
                    "Reference solution is required for numerical exercises."
                )
            if self.absolute_tolerance is None:
                errors["absolute_tolerance"] = (
                    "Tolerance is required for numerical exercises."
                )
            if self.available_points is None:
                errors["available_points"] = (
                    "Available points are required for numerical exercises."
                )

        if errors:
            raise ValidationError(errors)


class Result(models.Model):
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="results",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name="results",
    )
    tutorial = models.ForeignKey(
        Tutorial,
        on_delete=models.PROTECT,
        related_name="results",
    )
    exercise = models.ForeignKey(
        Exercise,
        on_delete=models.PROTECT,
        related_name="results",
    )
    assigned_variant = models.ForeignKey(
        ExerciseVariant,
        on_delete=models.PROTECT,
        related_name="results",
    )
    submitted_numerical_value = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    uploaded_file = models.FileField(
        upload_to="student_submissions/",
        blank=True,
        null=True,
        validators=[validate_student_submission_file],
    )
    score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    is_correct = models.BooleanField(blank=True, null=True)
    is_manually_graded = models.BooleanField(default=False)
    feedback = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    graded_at = models.DateTimeField(blank=True, null=True)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="graded_results",
        blank=True,
        null=True,
    )
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["-submitted_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "exercise"],
                condition=models.Q(is_archived=False),
                name="core_result_unique_active_student_exercise",
            )
        ]

    def __str__(self):
        return f"{self.student.email} - {self.exercise.title}"
