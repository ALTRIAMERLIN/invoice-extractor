import csv
import io
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from invoice_extractor.exporter import build_exports
from invoice_extractor.models import Candidate, FieldValue, InvoiceRecord
from invoice_extractor.review import apply_edits, confirm_record, reset_record
from invoice_extractor.validator import parse_money, validate

BASE_VALUES = {
    'supplier': 'Acme Ltd',
    'invoice_number': 'INV-001',
    'invoice_date': '2026-01-15',
    'subtotal': '100.00',
    'tax': '10.00',
    'total': '110.00',
    'currency': 'USD',
}
FORMULA_PREFIXES = ('=', '+', '-', '@')


def make_record(
    record_id='rec-1',
    filename='invoice.pdf',
    overrides=None,
    processing_status='text_ready',
    file_sha256=None,
):
    values = {**BASE_VALUES, **(overrides or {})}
    record = InvoiceRecord(
        record_id=record_id,
        filename=filename,
        file_sha256=file_sha256 or record_id.ljust(64, '0'),
        page_count=1,
        processing_status=processing_status,
    )
    for name, value in values.items():
        if value is None:
            continue
        record.fields[name] = FieldValue(
            extracted_value=value,
            current_value=value,
            candidates=[Candidate(raw_text=value, page_number=1, rule_id='rule_test', context='ctx')],
        )
    validate(record)
    return record


def csv_rows(data: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(data.decode('utf-8-sig'), newline='')))


def csv_dicts(data: bytes) -> list[dict[str, str]]:
    rows = csv_rows(data)
    header_index = next(index for index, row in enumerate(rows) if row and row[0] == 'record_id')
    header = rows[header_index]
    return [dict(zip(header, row)) for row in rows[header_index + 1 :] if row]


def test_clean_record_is_auto_checked_without_issues():
    record = make_record()
    assert record.review_status == 'auto_checked'
    assert record.issues == []


def test_invalid_edit_is_atomic_and_keeps_all_values():
    record = make_record()
    with pytest.raises(ValueError):
        apply_edits(record, {'supplier': 'Other Ltd', 'subtotal': 'not money'})
    assert record.fields['supplier'].current_value == 'Acme Ltd'
    assert record.fields['subtotal'].current_value == '100.00'
    assert record.edit_history == []
    assert record.review_status == 'auto_checked'


def test_valid_edit_is_saved_when_another_field_is_untouched_and_invalid():
    record = make_record(overrides={'tax': 'broken'})
    apply_edits(record, {'supplier': 'Other Ltd'})
    assert record.fields['supplier'].current_value == 'Other Ltd'
    assert record.fields['tax'].current_value == 'broken'


def test_canonical_noop_edit_keeps_history_and_confirmation():
    record = make_record()
    confirm_record(record)
    apply_edits(record, {'supplier': ' Acme Ltd ', 'total': '110.0', 'currency': 'usd'})
    assert record.edit_history == []
    assert record.review_status == 'user_confirmed'
    assert record.fields['total'].edited_by_user is False


def test_real_edit_unconfirms_and_keeps_original_value():
    record = make_record()
    confirm_record(record)
    apply_edits(record, {'supplier': 'Other Ltd'})
    assert record.review_status != 'user_confirmed'
    assert record.review_reason == ''
    assert record.fields['supplier'].extracted_value == 'Acme Ltd'
    assert record.fields['supplier'].edited_by_user is True
    assert [entry['action'] for entry in record.edit_history] == ['edit']
    assert record.edit_history[0]['from'] == 'Acme Ltd'
    assert record.edit_history[0]['to'] == 'Other Ltd'


def test_reset_restores_extracted_values_and_keeps_history():
    record = make_record()
    apply_edits(record, {'supplier': 'Other Ltd', 'total': '120.00'})
    reset_record(record)
    assert record.fields['supplier'].current_value == 'Acme Ltd'
    assert record.fields['total'].current_value == '110.00'
    assert record.fields['supplier'].edited_by_user is False
    actions = [entry['action'] for entry in record.edit_history]
    assert actions.count('edit') == 2
    assert actions.count('reset') == 2


def test_manual_failed_source_with_all_fields_needs_reason():
    record = make_record(processing_status='failed')
    with pytest.raises(ValueError, match='reason'):
        confirm_record(record, '')
    confirm_record(record, '  Checked against the paper copy.  ')
    assert record.review_status == 'user_confirmed'
    assert record.review_reason == 'Checked against the paper copy.'


def test_missing_field_needs_reason_to_confirm():
    record = make_record(overrides={'subtotal': None})
    assert any(issue.code == 'missing_subtotal' for issue in record.issues)
    with pytest.raises(ValueError, match='reason'):
        confirm_record(record)
    confirm_record(record, 'Subtotal is absent on the source; total confirmed manually.')
    assert record.review_status == 'user_confirmed'


def test_blocking_invalid_field_cannot_be_confirmed():
    record = make_record(overrides={'invoice_date': '2026-02-30'})
    with pytest.raises(ValueError, match='Correct the invalid values'):
        confirm_record(record, 'any reason')
    assert record.review_status != 'user_confirmed'


def test_money_mismatch_is_reported_for_review():
    record = make_record(overrides={'total': '150.00'})
    assert any(issue.code == 'money_mismatch' for issue in record.issues)
    assert record.review_status == 'needs_review'


def test_export_default_selects_auto_checked_and_confirmed_not_excluded():
    auto = make_record('auto', 'auto.pdf')
    confirmed = make_record('confirmed', 'confirmed.pdf', {'subtotal': None})
    confirm_record(confirmed, 'Subtotal absent from source.')
    review = make_record('review', 'review.pdf', {'total': '150.00'})
    excluded = make_record('excluded', 'excluded.pdf')
    excluded.excluded = True
    files = build_exports([auto, confirmed, review, excluded])
    rows = csv_dicts(files['invoices_csv'])
    assert [row['record_id'] for row in rows] == ['auto', 'confirmed']
    evidence_ids = {row['record_id'] for row in csv_dicts(files['evidence_csv'])}
    assert evidence_ids == {'auto', 'confirmed'}


def test_export_include_all_keeps_review_records_but_drops_excluded():
    auto = make_record('auto', 'auto.pdf')
    review = make_record('review', 'review.pdf', {'total': '150.00'})
    excluded = make_record('excluded', 'excluded.pdf')
    excluded.excluded = True
    files = build_exports([auto, review, excluded], include_all=True)
    assert [row['record_id'] for row in csv_dicts(files['invoices_csv'])] == ['auto', 'review']


def test_batch_report_lists_every_record_with_selection_status():
    auto = make_record('auto', 'auto.pdf')
    review = make_record('review', 'review.pdf', {'total': '150.00'})
    excluded = make_record('excluded', 'excluded.pdf')
    excluded.excluded = True
    failed = make_record('failed', 'failed.pdf', processing_status='failed')
    rows = csv_rows(build_exports([auto, review, excluded, failed])['batch_csv'])
    assert rows[0] == ['Export time (UTC)', rows[0][1]]
    labels = {row[0]: row[1] for row in rows if len(row) == 2}
    assert labels['Input files'] == '4'
    assert labels['Exported records'] == '1'
    assert labels['Not exported records'] == '2'
    assert labels['Excluded records'] == '1'
    assert labels['Failed processing'] == '1'
    batch = csv_dicts(build_exports([auto, review, excluded, failed])['batch_csv'])
    statuses = {row['record_id']: row['selection_status'] for row in batch}
    assert statuses == {
        'auto': 'exported',
        'review': 'not_exported',
        'excluded': 'excluded',
        'failed': 'not_exported',
    }


def test_batch_csv_header_is_found_after_summary_prelude():
    files = build_exports([make_record()])
    rows = csv_rows(files['batch_csv'])
    header_index = next(index for index, row in enumerate(rows) if row and row[0] == 'record_id')
    assert header_index > 0
    assert rows[header_index - 1] == []
    assert rows[header_index][:4] == ['record_id', 'filename', 'file_sha256', 'page_count']


def test_empty_batch_produces_valid_reports():
    files = build_exports([])
    assert csv_dicts(files['invoices_csv']) == []
    assert csv_dicts(files['evidence_csv']) == []
    labels = {row[0]: row[1] for row in csv_rows(files['batch_csv']) if len(row) == 2}
    assert labels['Input files'] == '0'
    assert labels['Exported records'] == '0'
    workbook = load_workbook(io.BytesIO(files['xlsx']))
    assert workbook.sheetnames == ['Invoices', 'Evidence', 'Batch']
    assert workbook['Invoices'].max_row == 1


@pytest.mark.parametrize('value', ['=HYPERLINK("http://x")', '+1+1', '-2+3', '@SUM(A1)', '  =cmd'])
def test_formula_like_values_are_neutralised_in_every_csv(value):
    record = make_record('fx', 'fx.pdf', {'supplier': value})
    files = build_exports([record], include_all=True)
    for key in ('invoices_csv', 'evidence_csv', 'batch_csv'):
        for row in csv_rows(files[key]):
            for cell in row:
                assert not cell.lstrip().startswith(FORMULA_PREFIXES) or cell.startswith("'")
    assert "'" + value.strip() in csv_rows(files['invoices_csv'])[1] or any(
        cell == "'" + value for cell in csv_rows(files['invoices_csv'])[1]
    )


def test_formula_in_filename_and_evidence_is_neutralised():
    record = make_record('fn', '=evil.pdf', {'supplier': 'Acme'})
    record.fields['supplier'].candidates[0].raw_text = '=1+1'
    files = build_exports([record], include_all=True)
    batch = csv_dicts(files['batch_csv'])
    assert batch[0]['filename'] == "'=evil.pdf"
    evidence = csv_dicts(files['evidence_csv'])
    assert any(row['raw_text'] == "'=1+1" for row in evidence)


def test_formula_in_xlsx_is_stored_as_text_not_formula():
    record = make_record('xf', 'xf.pdf', {'supplier': '=SUM(1,2)'})
    workbook = load_workbook(io.BytesIO(build_exports([record])['xlsx']))
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                assert cell.data_type != 'f'


def test_control_and_xml_unsafe_characters_are_escaped_not_dropped():
    record = make_record('cc', 'cc.pdf', {'supplier': 'Acme\x07Ltd\x00'})
    files = build_exports([record])
    invoice_row = csv_dicts(files['invoices_csv'])[0]
    assert invoice_row['supplier'] == 'Acme\\x0007Ltd\\x0000'
    assert '\x07' not in files['invoices_csv'].decode('utf-8-sig')
    workbook = load_workbook(io.BytesIO(files['xlsx']))
    assert workbook['Invoices']['D2'].value == 'Acme\\x0007Ltd\\x0000'


def test_front_zero_invoice_number_stays_text():
    record = make_record('zero', 'zero.pdf', {'invoice_number': '00123'})
    files = build_exports([record])
    assert csv_dicts(files['invoices_csv'])[0]['invoice_number'] == '00123'
    cell = load_workbook(io.BytesIO(files['xlsx']))['Invoices']['E2']
    assert cell.value == '00123'
    assert cell.data_type == 's'


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('0', '0.00'),
        ('0.01', '0.01'),
        ('12.5', '12.50'),
        ('999999999.99', '999999999.99'),
    ],
)
def test_money_boundaries_round_trip_through_xlsx(raw, expected):
    assert parse_money(raw) == expected
    record = make_record('mb', 'mb.pdf', {'subtotal': expected, 'tax': '0.00', 'total': expected})
    cell = load_workbook(io.BytesIO(build_exports([record])['xlsx']))['Invoices']['G2']
    assert Decimal(str(cell.value)).quantize(Decimal('0.01')) == Decimal(expected)
    assert cell.number_format == '0.00'


@pytest.mark.parametrize('raw', ['1000000000.00', '-1.00', '(1.00)', '1.234', 'abc', ''])
def test_money_out_of_range_or_malformed_is_rejected(raw):
    with pytest.raises(ValueError):
        parse_money(raw)
