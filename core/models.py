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

    def __init__(self, *args, **kwargs):
        # Backward-compatible shim while legacy callers still pass exercise_type.
        self._legacy_exercise_type = kwargs.pop("exercise_type", None)
        super().__init__(*args, **kwargs)

    tutorial = models.ForeignKey(
        Tutorial,
        on_delete=models.CASCADE,
        related_name="exercises",
    )
    title = models.CharField(max_length=200)
    order_index = models.PositiveIntegerField()
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

    @property
    def exercise_type(self):
        if not self.pk:
            return self._legacy_exercise_type or self.ExerciseType.NUMERICAL
        first_part_type = (
            ExercisePart.objects.filter(variant__exercise=self)
            .order_by("order_index", "id")
            .values_list("answer_type", flat=True)
            .first()
        )
        if first_part_type == ExerciseVariant.PartAnswerType.DOCUMENT_UPLOAD:
            return self.ExerciseType.DOCUMENT_UPLOAD
        if first_part_type == ExerciseVariant.PartAnswerType.NUMERICAL:
            return self.ExerciseType.NUMERICAL
        return self._legacy_exercise_type or self.ExerciseType.NUMERICAL


class ExerciseVariant(models.Model):
    class PartAnswerType(models.TextChoices):
        NUMERICAL = "numerical", "Numerical"
        DOCUMENT_UPLOAD = "document_upload", "Document upload"

    exercise = models.ForeignKey(
        Exercise,
        on_delete=models.CASCADE,
        related_name="variants",
    )
    exercise_text = models.TextField()
    image = models.ImageField(upload_to="exercise_variants/images/", blank=True, null=True)
    supervisor_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["exercise_id", "id"]

    def __str__(self):
        return f"{self.exercise.title} - Variant {self.id}"

    def clean(self):
        super().clean()
        return


class ArchiveBatch(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name="archive_batches",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="archive_batches_created",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.course.title} - Archive batch {self.id}"


class ExercisePart(models.Model):
    variant = models.ForeignKey(
        ExerciseVariant,
        on_delete=models.CASCADE,
        related_name="parts",
    )
    label = models.CharField(max_length=20)
    prompt_text = models.TextField(blank=True)
    answer_type = models.CharField(
        max_length=20,
        choices=ExerciseVariant.PartAnswerType.choices,
        default=ExerciseVariant.PartAnswerType.NUMERICAL,
    )
    reference_solution = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    absolute_tolerance = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    available_points = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    order_index = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["variant_id", "order_index", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["variant", "label"],
                name="core_exercisepart_unique_label_per_variant",
            ),
            models.UniqueConstraint(
                fields=["variant", "order_index"],
                name="core_exercisepart_unique_order_per_variant",
            ),
        ]

    def __str__(self):
        return f"{self.variant.exercise.title} - Part {self.label}"

    def clean(self):
        super().clean()
        errors = {}
        if self.available_points is not None and self.available_points < 0:
            errors["available_points"] = "Available points must be non-negative."
        if self.absolute_tolerance is not None and self.absolute_tolerance < 0:
            errors["absolute_tolerance"] = "Tolerance must be non-negative."

        is_numerical_part = self.answer_type == ExerciseVariant.PartAnswerType.NUMERICAL
        if is_numerical_part:
            if self.reference_solution is None:
                errors["reference_solution"] = "Reference solution is required for numerical parts."
            if self.absolute_tolerance is None:
                errors["absolute_tolerance"] = "Tolerance is required for numerical parts."
            if self.available_points is None:
                errors["available_points"] = "Available points are required for numerical parts."

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
    score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    is_correct = models.BooleanField(blank=True, null=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    archive_batch = models.ForeignKey(
        ArchiveBatch,
        on_delete=models.PROTECT,
        related_name="results",
        blank=True,
        null=True,
    )
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["-submitted_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "exercise"],
                condition=models.Q(archive_batch__isnull=True),
                name="core_result_unique_active_student_exercise",
            )
        ]

    def save(self, *args, **kwargs):
        # Keep legacy flag aligned while archive_batch becomes archive source of truth.
        self.is_archived = self.archive_batch_id is not None
        super().save(*args, **kwargs)

    def recompute_total_score(self):
        total = self.parts.aggregate(total=models.Sum("score")).get("total")
        self.score = total if total is not None else 0

    def __str__(self):
        return f"{self.student.email} - {self.exercise.title}"


class ResultPart(models.Model):
    result = models.ForeignKey(
        Result,
        on_delete=models.CASCADE,
        related_name="parts",
    )
    exercise_part = models.ForeignKey(
        ExercisePart,
        on_delete=models.PROTECT,
        related_name="result_parts",
    )
    submitted_numerical_value = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    uploaded_file = models.FileField(
        upload_to="student_submissions/",
        blank=True,
        null=True,
        validators=[validate_student_submission_file],
    )
    reference_value_used = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    tolerance_used = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    is_correct = models.BooleanField(blank=True, null=True)
    score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    is_manually_graded = models.BooleanField(default=False)
    feedback = models.TextField(blank=True)
    graded_at = models.DateTimeField(blank=True, null=True)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="graded_result_parts",
        blank=True,
        null=True,
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["result_id", "exercise_part__order_index", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["result", "exercise_part"],
                name="core_resultpart_unique_result_exercisepart",
            )
        ]

    def __str__(self):
        return f"{self.result.student.email} - {self.exercise_part.label}"
