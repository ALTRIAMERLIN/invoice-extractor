from __future__ import annotations

import hashlib
from collections import defaultdict

from invoice_extractor.models import SUPPORTED_CURRENCIES, InvoiceRecord, Issue
from invoice_extractor.validator import parse_money, validate

DUPLICATE_PREFIX = 'duplicate_'
EXACT_CODE = 'duplicate_exact'
BUSINESS_CODE = 'duplicate_business'
DUPLICATE_MESSAGE = 'record matches another record; review before export'
GROUP_DIGEST_LENGTH = 24


def _normalize_text(raw: str | None) -> str:
    return ' '.join((raw or '').split()).casefold()


def _business_key(record: InvoiceRecord) -> tuple[str, str, str, str] | None:
    supplier = _normalize_text(record.fields['supplier'].current_value)
    invoice_number = _normalize_text(record.fields['invoice_number'].current_value)
    currency = (record.fields['currency'].current_value or '').strip().upper()
    if not supplier or not invoice_number or currency not in SUPPORTED_CURRENCIES:
        return None
    try:
        total = parse_money(record.fields['total'].current_value)
    except ValueError:
        return None
    return supplier, invoice_number, currency, total


def _file_hash(record: InvoiceRecord) -> str | None:
    return (record.file_sha256 or '').strip().lower() or None


def _group_records(
    records: list[InvoiceRecord],
) -> tuple[set[str], dict[str, list[str]]]:
    by_hash: dict[str, set[str]] = defaultdict(set)
    by_key: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    for record in records:
        file_hash = _file_hash(record)
        if file_hash is not None:
            by_hash[file_hash].add(record.record_id)
        business_key = _business_key(record)
        if business_key is not None:
            by_key[business_key].add(record.record_id)
    exact_members: set[str] = set()
    group_ids: dict[str, list[str]] = defaultdict(list)
    for prefix, buckets in (('exact', by_hash.values()), ('business', by_key.values())):
        for member_set in buckets:
            if len(member_set) < 2:
                continue
            members = sorted(member_set)
            digest = hashlib.sha256('\n'.join(members).encode('utf-8')).hexdigest()
            group_id = f'{prefix}-{digest[:GROUP_DIGEST_LENGTH]}'
            for member in members:
                group_ids[member].append(group_id)
                if prefix == 'exact':
                    exact_members.add(member)
    return exact_members, group_ids


def mark_duplicates(records: list[InvoiceRecord]) -> None:
    exact_members, group_ids = _group_records(records)
    for record in records:
        new_ids = sorted(group_ids.get(record.record_id, []))
        membership_changed = sorted(record.duplicate_group_ids) != new_ids
        record.issues = [
            issue for issue in record.issues if not issue.code.startswith(DUPLICATE_PREFIX)
        ]
        record.duplicate_group_ids = new_ids
        if membership_changed:
            if record.review_status == 'user_confirmed':
                record.review_status = 'needs_review'
            record.review_reason = ''
        validate(record)
        if not new_ids:
            continue
        code = EXACT_CODE if record.record_id in exact_members else BUSINESS_CODE
        record.issues.append(Issue(code=code, message=DUPLICATE_MESSAGE))
        if record.review_status != 'user_confirmed':
            record.review_status = 'needs_review'
