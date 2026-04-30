from django.core.exceptions import ValidationError

ALLOWED_EMAIL_DOMAINS = ("unibas.ch", "stud.unibas.ch")


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
