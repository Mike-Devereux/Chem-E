from decimal import Decimal, InvalidOperation


def normalize_scientific_notation(value):
    if isinstance(value, str):
        return value.strip().replace("D", "e").replace("d", "e")
    return value


def parse_decimal_value(value):
    normalized = normalize_scientific_notation(value)
    try:
        return Decimal(normalized)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Enter a number.") from exc


def parse_float_value(value):
    normalized = normalize_scientific_notation(value)
    try:
        return float(normalized)
    except (TypeError, ValueError) as exc:
        raise ValueError("Enter a number.") from exc
