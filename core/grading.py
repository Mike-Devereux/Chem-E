from decimal import Decimal


def is_numerical_answer_correct(submitted_value, reference_solution, absolute_tolerance):
    """Return True when submitted value is within absolute tolerance."""
    submitted = Decimal(submitted_value)
    reference = Decimal(reference_solution)
    tolerance = Decimal(absolute_tolerance)
    return abs(submitted - reference) <= tolerance
