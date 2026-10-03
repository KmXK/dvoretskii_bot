from fractions import Fraction

from steward.data.models.bill_v2 import (
    UNKNOWN_PERSON_ID,
    BillItemAssignment,
    BillTransaction,
)


def _integer(value, field: str) -> tuple[int | None, str | None]:
    if isinstance(value, bool):
        return None, f"{field} должно быть целым числом"
    if isinstance(value, int):
        return value, None
    if isinstance(value, float):
        if not value.is_integer():
            return None, f"{field} должно быть целым числом"
        return int(value), None
    if isinstance(value, str):
        value = value.strip()
        if value:
            try:
                return int(value), None
            except ValueError:
                pass
    return None, f"{field} должно быть целым числом"


def _positive(value, field: str) -> tuple[int | None, str | None]:
    result, error = _integer(value, field)
    if error:
        return None, error
    if result <= 0:
        return None, f"{field} должно быть больше нуля"
    return result, None


def _nonnegative(value, field: str) -> tuple[int | None, str | None]:
    result, error = _integer(value, field)
    if error:
        return None, error
    if result < 0:
        return None, f"{field} не может быть отрицательным"
    return result, None


def parse_assignment_list(raw, *, label: str = "позиция") -> tuple[list[BillItemAssignment] | None, str | None]:
    if not isinstance(raw, list):
        return None, f"{label}: назначения должны быть списком"

    assignments = []
    for index, item in enumerate(raw, 1):
        prefix = f"{label}, назначение #{index}"
        if not isinstance(item, dict):
            return None, f"{prefix}: нужен объект"

        unit_count, error = _positive(item.get("unit_count", 1), f"{prefix}: количество")
        if error:
            return None, error
        denominator, error = _positive(item.get("denominator", 1), f"{prefix}: знаменатель")
        if error:
            return None, error

        debtors = item.get("debtors", [])
        error = validate_debtors(debtors, prefix)
        if error:
            return None, error
        assignments.append(
            BillItemAssignment(
                unit_count=unit_count,
                debtors=list(debtors),
                denominator=denominator,
            )
        )

    return assignments, None


def validate_debtors(debtors, label: str = "назначение") -> str | None:
    if not isinstance(debtors, list):
        return f"{label}: должники должны быть списком"
    if any(not isinstance(debtor, str) or not debtor.strip() for debtor in debtors):
        return f"{label}: идентификаторы должников должны быть непустыми строками"
    if len(debtors) != len(set(debtors)):
        return f"{label}: один и тот же должник указан несколько раз"
    return None


def validate_assignments(
    assignments: list[BillItemAssignment],
    quantity: int,
    *,
    label: str = "позиция",
) -> str | None:
    coverage = Fraction(0)
    for index, assignment in enumerate(assignments, 1):
        prefix = f"{label}, назначение #{index}"
        unit_count, error = _positive(assignment.unit_count, f"{prefix}: количество")
        if error:
            return error
        denominator, error = _positive(assignment.denominator, f"{prefix}: знаменатель")
        if error:
            return error
        error = validate_debtors(assignment.debtors, prefix)
        if error:
            return error
        coverage += Fraction(unit_count, denominator)

    if coverage > quantity:
        return f"{label}: распределено {coverage} ед. при количестве {quantity}"
    return None


def is_distribution_incomplete(
    assignments: list[BillItemAssignment],
    quantity: int,
) -> bool:
    coverage = Fraction(0)
    for assignment in assignments:
        coverage += Fraction(assignment.unit_count, assignment.denominator)
        if not assignment.debtors or UNKNOWN_PERSON_ID in assignment.debtors:
            return True
    return coverage != quantity


def validate_transaction_values(
    unit_price_minor,
    quantity,
    assignments: list[BillItemAssignment],
    *,
    label: str = "позиция",
) -> str | None:
    _, error = _nonnegative(unit_price_minor, f"{label}: цена")
    if error:
        return error
    normalized_quantity, error = _positive(quantity, f"{label}: количество")
    if error:
        return error
    return validate_assignments(assignments, normalized_quantity, label=label)


def validate_transaction(transaction: BillTransaction, *, label: str = "позиция") -> str | None:
    return validate_transaction_values(
        transaction.unit_price_minor,
        transaction.quantity,
        transaction.assignments,
        label=label,
    )
