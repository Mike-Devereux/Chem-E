import os

from django.core.exceptions import ValidationError

ALLOWED_EMAIL_DOMAINS = ("unibas.ch", "stud.unibas.ch")
ALLOWED_STUDENT_UPLOAD_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
}
MAX_STUDENT_UPLOAD_SIZE_BYTES = 20 * 1024 * 1024


def validate_university_email_domain(value):
    if not value:
        return

    email = value.strip().lower()
    _, separator, domain = email.rpartition("@")
    if separator != "@" or domain not in ALLOWED_EMAIL_DOMAINS:
        raise ValidationError(
            "Email must end with @unibas.ch or @stud.unibas.ch.",
            code="invalid_email_domain",
        )


def validate_student_submission_file(file_obj):
    if not file_obj:
        return

    _, extension = os.path.splitext(file_obj.name)
    if extension.lower() not in ALLOWED_STUDENT_UPLOAD_EXTENSIONS:
        raise ValidationError(
            "Unsupported file extension. Allowed: pdf, docx, png, jpg, jpeg, tif, tiff.",
            code="invalid_file_extension",
        )

    if file_obj.size > MAX_STUDENT_UPLOAD_SIZE_BYTES:
        raise ValidationError(
            "File size must be 20 MB or smaller.",
            code="file_too_large",
        )
