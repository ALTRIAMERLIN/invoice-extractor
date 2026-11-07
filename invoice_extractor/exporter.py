import copy
import csv
import io
import json
import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from invoice_extractor.models import FIELD_NAMES, MONEY_FIELDS, InvoiceRecord, Limits
from invoice_extractor.validator import parse_date, parse_money

AUTO_OR_CONFIRMED = ('auto_checked', 'user_confirmed')
FORMULA_PREFIXES = ('=', '+', '-', '@')
INVALID_XML_CHARS = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff\ud800-\udfff]')
EXCEL_CELL_LIMIT = 32767
EXCEL_MONEY_LIMIT = Decimal('999999999.99')
MONEY_FORMAT = '0.00'

INVOICE_COLUMNS = (
    'record_id',
    'filename',
    'page_count',
    'supplier',
    'invoice_number',
    'invoice_date',
    'subtotal',
    'tax',
    'total',
    'currency',
    'processing_status',
    'review_status',
    'duplicate_groups',
    'review_reason',
)
EVIDENCE_COLUMNS = (
    'record_id',
    'filename',
    'row_type',
    'field',
    'extracted_value',
    'current_value',
    'edited_by_user',
    'candidate_no',
    'page_number',
    'rule_id',
    'raw_text',
    'context',
    'issue_code',
    'blocking',
    'detail',
)
BATCH_COLUMNS = (
    'record_id',
    'filename',
    'file_sha256',
    'page_count',
    'processing_status',
    'review_status',
    'excluded',
    'selection_status',
    'issue_count',
    'blocking_issue_count',
    'duplicate_groups',
    'review_reason',
)


def build_exports(records: list[InvoiceRecord], include_all: bool = False) -> dict[str, bytes]:
    snapshot = copy.deepcopy(records)
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    selected = [record for record in snapshot if _is_selected(record, include_all)]
    invoice_rows = [_invoice_row(record) for record in selected]
    evidence_rows = [row for record in selected for row in _evidence_rows(record)]
    batch_summary = _batch_summary(snapshot, include_all, timestamp)
    batch_rows = [_batch_row(record, include_all) for record in snapshot]
    return {
        'xlsx': _build_xlsx(invoice_rows, evidence_rows, batch_summary, batch_rows),
        'invoices_csv': _csv_bytes(INVOICE_COLUMNS, invoice_rows),
        'evidence_csv': _csv_bytes(EVIDENCE_COLUMNS, evidence_rows),
        'batch_csv': _csv_bytes(BATCH_COLUMNS, batch_rows, summary=batch_summary),
    }


def _is_selected(record: InvoiceRecord, include_all: bool) -> bool:
    if record.excluded:
        return False
    return include_all or record.review_status in AUTO_OR_CONFIRMED


def _selection_status(record: InvoiceRecord, include_all: bool) -> str:
    if record.excluded:
        return 'excluded'
    if _is_selected(record, include_all):
        return 'exported'
    return 'not_exported'


def _invoice_row(record: InvoiceRecord) -> list[str | None]:
    row: list[str | None] = [record.record_id, record.filename, str(record.page_count)]
    row.extend(_main_value(name, record.fields[name].current_value) for name in FIELD_NAMES)
    row.extend(
        [
            record.processing_status,
            record.review_status,
            '; '.join(record.duplicate_group_ids),
            record.review_reason,
        ]
    )
    return row


def _main_value(name: str, value: str | None) -> str | None:
    if value is None or not value.strip():
        return value
    try:
        if name in MONEY_FIELDS:
            return parse_money(value)
        if name == 'invoice_date':
            return parse_date(value)
    except ValueError:
        return value
    return value


def _evidence_rows(record: InvoiceRecord) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    for name in FIELD_NAMES:
        field_value = record.fields[name]
        rows.append(
            _evidence(
                record,
                row_type='field',
                field=name,
                extracted_value=field_value.extracted_value,
                current_value=field_value.current_value,
                edited_by_user='yes' if field_value.edited_by_user else 'no',
            )
        )
        for number, candidate in enumerate(field_value.candidates, start=1):
            rows.append(
                _evidence(
                    record,
                    row_type='candidate',
                    field=name,
                    candidate_no=str(number),
                    page_number=str(candidate.page_number),
                    rule_id=candidate.rule_id,
                    raw_text=candidate.raw_text,
                    context=candidate.context,
                )
            )
    for issue in record.initial_issues or record.original_issues or []:
        rows.append(
            _evidence(
                record,
                row_type='original_issue',
                field=issue.field or '',
                issue_code=issue.code,
                blocking='yes' if issue.blocking else 'no',
            )
        )
    for issue in record.issues:
        rows.append(
            _evidence(
                record,
                row_type='issue',
                field=issue.field or '',
                issue_code=issue.code,
                blocking='yes' if issue.blocking else 'no',
                detail=issue.message,
            )
        )
    for entry in record.edit_history:
        rows.append(
            _evidence(
                record,
                row_type='edit',
                field=str(entry.get('field', '')),
                detail=json.dumps(entry, ensure_ascii=False, sort_keys=True),
            )
        )
    return rows


def _evidence(record: InvoiceRecord, **values: str | None) -> dict[str, str | None]:
    row: dict[str, str | None] = {column: '' for column in EVIDENCE_COLUMNS}
    row['record_id'] = record.record_id
    row['filename'] = record.filename
    row.update(values)
    return row


def _batch_row(record: InvoiceRecord, include_all: bool) -> list[str | None]:
    blocking = sum(1 for issue in record.issues if issue.blocking)
    return [
        record.record_id,
        record.filename,
        record.file_sha256,
        str(record.page_count),
        record.processing_status,
        record.review_status,
        'yes' if record.excluded else 'no',
        _selection_status(record, include_all),
        str(len(record.issues)),
        str(blocking),
        '; '.join(record.duplicate_group_ids),
        record.review_reason,
    ]


def _batch_summary(records: list[InvoiceRecord], include_all: bool, timestamp: str) -> list[tuple[str, str]]:
    limits = Limits()
    statuses = [_selection_status(record, include_all) for record in records]
    return [
        ('Export time (UTC)', timestamp),
        (
            'Selection mode',
            'all non-excluded records' if include_all else 'auto_checked and user_confirmed, not excluded',
        ),
        ('Input files', str(len(records))),
        ('Exported records', str(statuses.count('exported'))),
        ('Not exported records', str(statuses.count('not_exported'))),
        ('Excluded records', str(statuses.count('excluded'))),
        ('Failed processing', str(sum(1 for record in records if record.processing_status != 'text_ready'))),
        ('Records with blocking issues', str(sum(1 for record in records if _has_blocking(record)))),
        ('Records in duplicate groups', str(sum(1 for record in records if record.duplicate_group_ids))),
        ('Limit: files per batch', str(limits.max_files)),
        ('Limit: bytes per file', str(limits.max_file_bytes)),
        ('Limit: bytes per batch', str(limits.max_batch_bytes)),
        ('Limit: pages per file', str(limits.max_pages)),
    ]


def _has_blocking(record: InvoiceRecord) -> bool:
    return any(issue.blocking for issue in record.issues)


def _csv_bytes(
    columns: tuple[str, ...],
    rows: list,
    summary: list[tuple[str, str]] | None = None,
) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if summary is not None:
        for label, value in summary:
            writer.writerow([_csv_cell(label), _csv_cell(value)])
        writer.writerow([])
    writer.writerow(columns)
    for row in rows:
        if isinstance(row, dict):
            writer.writerow([_csv_cell(row.get(column)) for column in columns])
        else:
            writer.writerow([_csv_cell(value) for value in row])
    return buffer.getvalue().encode('utf-8-sig')


def _csv_cell(value: str | None) -> str:
    if value is None:
        return ''
    return _clean_text(_guard_formula(value))


def _build_xlsx(
    invoice_rows: list[list[str | None]],
    evidence_rows: list[dict[str, str | None]],
    batch_summary: list[tuple[str, str]],
    batch_rows: list[list[str | None]],
) -> bytes:
    workbook = Workbook()
    invoices = workbook.active
    invoices.title = 'Invoices'
    _write_header(invoices, INVOICE_COLUMNS)
    money_indexes = {INVOICE_COLUMNS.index(name) for name in MONEY_FIELDS}
    for row_number, row in enumerate(invoice_rows, start=2):
        for column_number, value in enumerate(row, start=1):
            if column_number - 1 in money_indexes:
                _write_money(invoices, row_number, column_number, value)
            else:
                _write_text(invoices, row_number, column_number, value)

    evidence = workbook.create_sheet('Evidence')
    _write_header(evidence, EVIDENCE_COLUMNS)
    for row_number, row in enumerate(evidence_rows, start=2):
        for column_number, column in enumerate(EVIDENCE_COLUMNS, start=1):
            _write_text(evidence, row_number, column_number, row.get(column))

    batch = workbook.create_sheet('Batch')
    for row_number, (label, value) in enumerate(batch_summary, start=1):
        _write_text(batch, row_number, 1, label, bold=True)
        _write_text(batch, row_number, 2, value)
    table_start = len(batch_summary) + 2
    _write_header(batch, BATCH_COLUMNS, row_number=table_start)
    for row_number, row in enumerate(batch_rows, start=table_start + 1):
        for column_number, value in enumerate(row, start=1):
            _write_text(batch, row_number, column_number, value)

    for sheet, header_row in ((invoices, 1), (evidence, 1), (batch, table_start)):
        _format_sheet(sheet, header_row)

    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _format_sheet(sheet, header_row: int) -> None:
    widths = {'record_id': 22, 'filename': 34, 'supplier': 32, 'invoice_number': 22,
              'invoice_date': 18, 'raw_text': 48, 'context': 48, 'detail': 55,
              'review_reason': 48, 'duplicate_groups': 30, 'file_sha256': 26}
    sheet.freeze_panes = f'A{header_row + 1}'
    sheet.auto_filter.ref = f'A{header_row}:{get_column_letter(sheet.max_column)}{sheet.max_row}'
    sheet.sheet_view.showGridLines = False
    sheet.sheet_properties.tabColor = '0F766E'
    for cell in sheet[header_row]:
        cell.fill = PatternFill('solid', fgColor='0F766E')
        cell.font = Font(bold=True, color='FFFFFF')
        cell.alignment = Alignment(vertical='center')
        sheet.column_dimensions[cell.column_letter].width = widths.get(cell.value, 19)
    sheet.row_dimensions[header_row].height = 25


def _write_header(sheet, columns: tuple[str, ...], row_number: int = 1) -> None:
    for column_number, name in enumerate(columns, start=1):
        _write_text(sheet, row_number, column_number, name, bold=True)


def _write_text(sheet, row_number: int, column_number: int, value: str | None, bold: bool = False) -> None:
    cell = sheet.cell(row=row_number, column=column_number)
    cell.value = _xlsx_text(value or '')
    cell.data_type = 's'
    if bold:
        cell.font = Font(bold=True)


def _write_money(sheet, row_number: int, column_number: int, value: str | None) -> None:
    if value is None or not value.strip():
        return
    amount = _money_amount(value)
    if amount is None:
        _write_text(sheet, row_number, column_number, value)
        return
    cell = sheet.cell(row=row_number, column=column_number)
    cell.value = amount
    cell.number_format = MONEY_FORMAT


def _money_amount(value: str) -> Decimal | None:
    try:
        amount = Decimal(parse_money(value.strip()))
    except ValueError:
        return None
    if not amount.is_finite() or amount < 0 or amount > EXCEL_MONEY_LIMIT:
        return None
    if amount != amount.quantize(Decimal('0.01')):
        return None
    return amount


def _xlsx_text(value: str) -> str:
    text = _clean_text(value)
    if len(text) > EXCEL_CELL_LIMIT:
        text = text[: EXCEL_CELL_LIMIT - 3] + '...'
    return text


def _clean_text(value: str) -> str:
    return INVALID_XML_CHARS.sub(lambda match: f'\\x{ord(match.group()):04x}', str(value))


def _guard_formula(text: str) -> str:
    index = 0
    while index < len(text) and (text[index].isspace() or unicodedata.category(text[index])[0] in 'CZ'):
        index += 1
    if index < len(text) and text[index] in FORMULA_PREFIXES:
        return "'" + text
    return text
