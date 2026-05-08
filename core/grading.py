from decimal import Decimal


def _to_decimal_exactish(value):
    """Convert float-backed values to Decimal without binary-float artifacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def is_numerical_answer_correct(submitted_value, reference_solution, absolute_tolerance):
    """Return True when submitted value is within absolute tolerance."""
    submitted = _to_decimal_exactish(submitted_value)
    reference = _to_decimal_exactish(reference_solution)
    tolerance = _to_decimal_exactish(absolute_tolerance)
    return abs(submitted - reference) <= tolerance
