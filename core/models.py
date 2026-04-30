from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

from .validators import validate_university_email_domain


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
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", User.Role.STUDENT)
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

    def __str__(self):
        return self.title


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
