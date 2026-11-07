from __future__ import annotations

from dataclasses import dataclass, field

FIELD_NAMES = ('supplier', 'invoice_number', 'invoice_date', 'subtotal', 'tax', 'total', 'currency')
MONEY_FIELDS = ('subtotal', 'tax', 'total')
SUPPORTED_CURRENCIES = ('USD', 'EUR', 'GBP', 'HKD', 'CNY')
MAX_TEXT_CHARS = 300


@dataclass
class Candidate:
    raw_text: str
    page_number: int
    rule_id: str
    context: str = ''


@dataclass
class Issue:
    code: str
    message: str
    field: str | None = None
    blocking: bool = False


@dataclass
class FieldValue:
    extracted_value: str | None = None
    current_value: str | None = None
    candidates: list[Candidate] = field(default_factory=list)
    edited_by_user: bool = False


@dataclass(frozen=True)
class Limits:
    max_files: int = 50
    max_file_bytes: int = 10 * 1024 * 1024
    max_batch_bytes: int = 100 * 1024 * 1024
    max_pages: int = 20
    timeout_seconds: float = 30
    max_page_chars: int = 100_000
    max_document_chars: int = 1_000_000


@dataclass
class DocumentText:
    filename: str
    file_sha256: str
    page_count: int = 0
    pages: list[str] = field(default_factory=list)
    status: str = 'text_ready'
    issues: list[Issue] = field(default_factory=list)


def _empty_fields() -> dict[str, FieldValue]:
    return {name: FieldValue() for name in FIELD_NAMES}


@dataclass
class InvoiceRecord:
    record_id: str
    filename: str
    file_sha256: str
    page_count: int = 0
    fields: dict[str, FieldValue] = field(default_factory=_empty_fields)
    processing_status: str = 'text_ready'
    review_status: str = 'needs_review'
    issues: list[Issue] = field(default_factory=list)
    original_issues: list[Issue] | None = None
    initial_issues: list[Issue] | None = None
    duplicate_group_ids: list[str] = field(default_factory=list)
    excluded: bool = False
    review_reason: str = ''
    edit_history: list[dict] = field(default_factory=list)
