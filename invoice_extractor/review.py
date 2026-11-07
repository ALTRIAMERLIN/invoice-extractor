from datetime import datetime, timezone

from invoice_extractor.models import FIELD_NAMES, MAX_TEXT_CHARS, MONEY_FIELDS, SUPPORTED_CURRENCIES, InvoiceRecord
from invoice_extractor.validator import parse_date, parse_money, validate

MAX_REASON_CHARS = 500
FIELD_LABELS = {
    'supplier': 'Supplier',
    'invoice_number': 'Invoice number',
    'invoice_date': 'Invoice date',
    'subtotal': 'Subtotal',
    'tax': 'Tax',
    'total': 'Total',
    'currency': 'Currency',
}


def apply_edits(record: InvoiceRecord, edits: dict[str, str]) -> None:
    normalized = _normalize_edits(edits)
    changes = {
        name: value
        for name, value in normalized.items()
        if _same_value(name, record.fields[name].current_value, value) is False
    }
    if not changes:
        return
    timestamp = _timestamp()
    for name, value in changes.items():
        field_value = record.fields[name]
        record.edit_history.append(
            {'action': 'edit', 'field': name, 'from': field_value.current_value, 'to': value, 'at': timestamp}
        )
        field_value.current_value = value
    _refresh_edited_flags(record)
    _reopen(record)
    validate(record)


def reset_record(record: InvoiceRecord) -> None:
    timestamp = _timestamp()
    for name in FIELD_NAMES:
        field_value = record.fields[name]
        if _same_value(name, field_value.current_value, field_value.extracted_value) is False:
            record.edit_history.append(
                {
                    'action': 'reset',
                    'field': name,
                    'from': field_value.current_value,
                    'to': field_value.extracted_value,
                    'at': timestamp,
                }
            )
            field_value.current_value = field_value.extracted_value
    _refresh_edited_flags(record)
    _reopen(record)
    validate(record)


def confirm_record(record: InvoiceRecord, reason: str = '') -> None:
    validate(record)
    if any(issue.blocking for issue in record.issues):
        raise ValueError('Correct the invalid values before confirming this record.')
    reason_text = _clean_reason(reason)
    if _needs_reason(record) and not reason_text:
        raise ValueError(
            'Enter a reason to confirm a record with open issues, duplicates, missing values or a failed source.'
        )
    record.review_status = 'user_confirmed'
    record.review_reason = reason_text


def _normalize_edits(edits: dict[str, str]) -> dict[str, str | None]:
    if not isinstance(edits, dict):
        raise ValueError('Edits must map field names to text.')
    normalized: dict[str, str | None] = {}
    problems: list[str] = []
    for name, raw in edits.items():
        if name not in FIELD_NAMES:
            raise ValueError(f'Unknown field: {name}.')
        if not isinstance(raw, str):
            raise ValueError(f'{FIELD_LABELS[name]} must be text.')
        try:
            normalized[name] = _normalize_value(name, raw)
        except ValueError as error:
            problems.append(f'{FIELD_LABELS[name]}: {error}')
    if problems:
        raise ValueError('; '.join(problems))
    return normalized


def _normalize_value(name: str, raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    if name in MONEY_FIELDS:
        return parse_money(text)
    if name == 'invoice_date':
        return parse_date(text)
    if name == 'currency':
        code = text.upper()
        if code not in SUPPORTED_CURRENCIES:
            raise ValueError('use one of USD, EUR, GBP, HKD or CNY')
        return code
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f'use at most {MAX_TEXT_CHARS} characters')
    return text


def _same_value(name: str, stored: str | None, new: str | None) -> bool:
    if _blank(stored) or _blank(new):
        return _blank(stored) and _blank(new)
    try:
        return _normalize_value(name, stored) == new
    except ValueError:
        return stored.strip() == new


def _clean_reason(reason: str) -> str:
    if not isinstance(reason, str):
        raise ValueError('The review reason must be text.')
    text = reason.strip()
    if len(text) > MAX_REASON_CHARS:
        raise ValueError(f'The review reason must be at most {MAX_REASON_CHARS} characters.')
    return text


def _needs_reason(record: InvoiceRecord) -> bool:
    missing_value = any(_blank(record.fields[name].current_value) for name in FIELD_NAMES)
    flagged_edit = bool(record.initial_issues) and any(value.edited_by_user for value in record.fields.values())
    return (
        bool(record.issues)
        or bool(record.duplicate_group_ids)
        or record.processing_status != 'text_ready'
        or missing_value
        or flagged_edit
    )


def _refresh_edited_flags(record: InvoiceRecord) -> None:
    for name in FIELD_NAMES:
        field_value = record.fields[name]
        field_value.edited_by_user = _same_value(
            name, field_value.extracted_value, field_value.current_value
        ) is False


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _reopen(record: InvoiceRecord) -> None:
    record.review_status = 'needs_review'
    record.review_reason = ''


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')
