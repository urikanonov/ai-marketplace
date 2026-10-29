"""Editable native-table authoring checks."""
from tables_common import scan_tables


def check_tables(html):
    """Return advisory authoring diagnostics, escalated by the validator's --strict."""
    try:
        scan_tables(html)
    except ValueError as exc:
        return [], ["editable table: " + str(exc)]
    return [], []
