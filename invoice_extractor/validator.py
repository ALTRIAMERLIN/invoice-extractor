from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from invoice_extractor.models import (
    FIELD_NAMES,
    MAX_TEXT_CHARS,
    MONEY_FIELDS,
    SUPPORTED_CURRENCIES,
    InvoiceRecord,
    Issue,
)

MAX_MONEY = Decimal('999999999.99')
MONEY_CHARS = re.compile(r'[0-9][0-9.,]*')
TEXT_FIELDS = ('supplier', 'invoice_number')
CURRENCY_MARKER = re.compile(
    r'^(?:USD|EUR|GBP|HKD|CNY|[$€£])\s*|\s*(?:USD|EUR|GBP|HKD|CNY)$', re.IGNORECASE
)
MONTHS = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6, 'july': 7,
    'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
}
DAY_MONTH_YEAR = re.compile(r'(\d{1,2})\s+([A-Za-z]+)\.?,?\s+(\d{4})')
MONTH_DAY_YEAR = re.compile(r'([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})')
ISO_DATE = re.compile(r'(\d{4})-(\d{2})-(\d{2})')
NUMERIC_DATE = re.compile(r'(\d{1,2})([/.-])(\d{1,2})\2(\d{4})')


def _grouped_digits(integer_part: str, separator: str) -> str:
    groups = integer_part.split(separator)
    first, rest = groups[0], groups[1:]
    if not 1 <= len(first) <= 3 or any(len(group) != 3 for group in rest):
        raise ValueError('invalid digit grouping')
    return ''.join(groups)


def _split_money(text: str) -> tuple[str, str]:
    if not MONEY_CHARS.fullmatch(text) or text.endswith(('.', ',')):
        raise ValueError('invalid money value')
    commas, dots = text.count(','), text.count('.')
    if commas and dots:
        decimal_sep = ',' if text.rfind(',') > text.rfind('.') else '.'
        grouping_sep = '.' if decimal_sep == ',' else ','
        if text.count(decimal_sep) != 1:
            raise ValueError('invalid money value')
        integer_part, fraction = text.rsplit(decimal_sep, 1)
        if grouping_sep not in integer_part:
            raise ValueError('invalid money value')
        return _grouped_digits(integer_part, grouping_sep), fraction
    separator = ',' if commas else '.' if dots else ''
    if not separator:
        return text, ''
    if text.count(separator) > 1:
        return _grouped_digits(text, separator), ''
    integer_part, fraction = text.split(separator)
    if len(fraction) == 3:
        raise ValueError('ambiguous money grouping')
    if separator == ',' and len(fraction) > 2:
        raise ValueError('invalid money value')
    return integer_part, fraction


def parse_money(raw: str) -> str:
    if not isinstance(raw, str):
        raise ValueError('money must be text')
    text = raw.strip()
    negative_parens = text.startswith('(') and text.endswith(')')
    if negative_parens:
        raise ValueError('negative money is not allowed')
    text = CURRENCY_MARKER.sub('', text).strip()
    if not text or text.startswith('-') or text.startswith('+') or '%' in text:
        raise ValueError('invalid money value')
    if re.search(r'[eE]', text):
        raise ValueError('invalid money value')
    integer_part, fraction = _split_money(text)
    if not integer_part or not integer_part.isdigit():
        raise ValueError('invalid money value')
    if fraction and (not fraction.isdigit() or len(fraction) > 2):
        raise ValueError('invalid money value')
    value = Decimal(f'{integer_part}.{fraction or "0"}')
    if not value.is_finite() or value < 0 or value > MAX_MONEY:
        raise ValueError('money out of range')
    return f'{value:.2f}'


def _calendar_date(year: int, month: int, day: int) -> str:
    try:
        return date(year, month, day).isoformat()
    except ValueError as error:
        raise ValueError('invalid calendar date') from error


def _month_number(name: str) -> int:
    month = MONTHS.get(name.lower())
    if month is None:
        raise ValueError('unknown month name')
    return month


def parse_date(raw: str) -> str:
    if not isinstance(raw, str):
        raise ValueError('date must be text')
    text = raw.strip()
    if match := ISO_DATE.fullmatch(text):
        return _calendar_date(int(match[1]), int(match[2]), int(match[3]))
    if match := DAY_MONTH_YEAR.fullmatch(text):
        return _calendar_date(int(match[3]), _month_number(match[2]), int(match[1]))
    if match := MONTH_DAY_YEAR.fullmatch(text):
        return _calendar_date(int(match[3]), _month_number(match[1]), int(match[2]))
    if match := NUMERIC_DATE.fullmatch(text):
        first, second, year = int(match[1]), int(match[3]), int(match[4])
        if first > 12 and second <= 12:
            return _calendar_date(year, second, first)
        if second > 12 and first <= 12:
            return _calendar_date(year, first, second)
        if first == second:
            return _calendar_date(year, first, second)
        if first <= 12 and second <= 12:
            raise ValueError('ambiguous numeric date')
        raise ValueError('invalid calendar date')
    raise ValueError('unsupported date format')


PARSERS = {
    'invoice_date': parse_date,
    'subtotal': parse_money,
    'tax': parse_money,
    'total': parse_money,
}
REGENERATED_CODES = frozenset(
    {f'{prefix}{name}' for prefix in ('missing_', 'invalid_') for name in FIELD_NAMES}
    | {'money_mismatch', 'source_not_text_ready', 'invalid_name'}
)
SOURCE_ISSUE_CODE = 'source_not_text_ready'
SOURCE_ISSUE_MESSAGE = 'source document was not fully read; manual review required'
MONEY_TOLERANCE = Decimal('0.01')


def _parse_currency(raw: str) -> str:
    code = raw.strip().upper()
    if code not in SUPPORTED_CURRENCIES:
        raise ValueError('unsupported currency')
    return code


def _is_regenerated(issue: Issue) -> bool:
    return issue.code in REGENERATED_CODES


def _carry_forward(record: InvoiceRecord) -> list[Issue]:
    kept: list[Issue] = []
    for issue in [*(record.original_issues or []), *record.issues]:
        if _is_regenerated(issue):
            continue
        if issue.field is not None and record.fields[issue.field].edited_by_user:
            continue
        if issue not in kept:
            kept.append(issue)
    return kept


def _is_original(issue: Issue) -> bool:
    return not _is_regenerated(issue) and not issue.code.startswith('duplicate_')


def _check_field(record: InvoiceRecord, name: str) -> Issue | None:
    raw = record.fields[name].current_value
    if raw is None or not raw.strip():
        return Issue(code=f'missing_{name}', message=f'{name} is missing', field=name)
    if name in TEXT_FIELDS and len(raw.strip()) > MAX_TEXT_CHARS:
        return Issue(
            code='invalid_name',
            message=f'{name} is longer than {MAX_TEXT_CHARS} characters',
            field=name,
            blocking=True,
        )
    try:
        if name == 'currency':
            _parse_currency(raw)
        elif name in PARSERS:
            PARSERS[name](raw)
    except ValueError as error:
        return Issue(
            code=f'invalid_{name}',
            message=f'{name} is invalid: {error}',
            field=name,
            blocking=True,
        )
    return None


def _money_mismatch(record: InvoiceRecord) -> Issue | None:
    amounts = {}
    for name in MONEY_FIELDS:
        raw = record.fields[name].current_value
        if raw is None or not raw.strip():
            return None
        try:
            amounts[name] = Decimal(parse_money(raw))
        except ValueError:
            return None
    difference = amounts['subtotal'] + amounts['tax'] - amounts['total']
    if abs(difference) <= MONEY_TOLERANCE:
        return None
    return Issue(
        code='money_mismatch',
        message='subtotal plus tax does not equal total',
    )


def validate(record: InvoiceRecord) -> list[Issue]:
    if record.original_issues is None:
        record.original_issues = [issue for issue in record.issues if _is_original(issue)]
    issues = _carry_forward(record)
    for name in FIELD_NAMES:
        issue = _check_field(record, name)
        if issue is not None:
            issues.append(issue)
    mismatch = _money_mismatch(record)
    if mismatch is not None:
        issues.append(mismatch)
    if record.processing_status != 'text_ready' and not any(
        issue.code == SOURCE_ISSUE_CODE for issue in issues
    ):
        issues.append(Issue(code=SOURCE_ISSUE_CODE, message=SOURCE_ISSUE_MESSAGE))
    record.issues = issues
    if record.initial_issues is None:
        record.initial_issues = [issue for issue in issues if not issue.code.startswith('duplicate_')]
    has_blocking = any(issue.blocking for issue in issues)
    if record.review_status == 'user_confirmed' and not has_blocking:
        return issues
    has_edits = any(field_value.edited_by_user for field_value in record.fields.values())
    record.review_status = 'needs_review' if issues or has_edits else 'auto_checked'
    return issues
