import pytest

from invoice_extractor.exporter import build_exports
from invoice_extractor.extractor import MAX_CANDIDATES, extract
from invoice_extractor.models import DocumentText, Issue
from invoice_extractor.review import apply_edits, confirm_record, reset_record

BASE = ['Supplier: Northstar Demo Studio', 'Invoice Number: 00011', 'Invoice Date: 2026-11-06',
        'Subtotal: 1025.00', 'Tax: 102.50', 'Total: 1127.50', 'Currency: USD']


@pytest.mark.parametrize('colon_gap', ['', '  '])
def test_split_money_segments_never_silently_pass_arithmetic(colon_gap):
    lines = BASE[:3] + [f'Subtotal:{colon_gap} 1  000.00', f'Tax:{colon_gap} 0  100.00',
                       f'Total:{colon_gap} 1  100.00', 'Currency: USD']
    record = _run('\n'.join(lines))
    assert record.review_status == 'needs_review'
    assert all(record.fields[name].current_value is None for name in ('subtotal', 'tax', 'total'))


def test_split_invoice_identifier_requires_review():
    lines = [line.replace('00011', '1234  5678') for line in BASE]
    record = _run('\n'.join(lines))
    assert record.review_status == 'needs_review'
    assert record.fields['invoice_number'].current_value is None


@pytest.mark.parametrize('missing', [False, True])
def test_corrected_initial_validation_issue_requires_reason(missing):
    lines = [line for line in BASE if not (missing and line.startswith('Tax:'))]
    if not missing:
        lines = [line.replace('1127.50', '1200.00') for line in lines]
    record = _run('\n'.join(lines))
    apply_edits(record, {'tax':'102.50'} if missing else {'total':'1127.50'})
    with pytest.raises(ValueError):
        confirm_record(record)
    confirm_record(record, 'Corrected against the original source.')
    assert record.review_status == 'user_confirmed'


def test_failed_duplicate_confirmation_cannot_enable_default_export():
    from invoice_extractor.dedupe import mark_duplicates
    records = [_run('\n'.join(BASE)), _run('\n'.join(BASE))]
    mark_duplicates(records)
    with pytest.raises(ValueError):
        confirm_record(records[0])
    assert records[0].review_status == 'needs_review'
    assert any(issue.code.startswith('duplicate_') for issue in records[0].issues)


def _run(*pages, **kwargs):
    return extract(DocumentText('a.pdf', 'abc', len(pages), list(pages), **kwargs))


def _values(record):
    return {name: value.current_value for name, value in record.fields.items()}


def _codes(record):
    return {(issue.code, issue.field) for issue in record.issues}


def _at(left, *columns):
    line = ' ' * 44 + left
    for x, text in columns:
        line = line.ljust(x) + text
    return line


def test_single_page_labels_extract_all_fields_with_evidence():
    record = _run('\n'.join(BASE))
    assert _values(record) == {
        'supplier': 'Northstar Demo Studio', 'invoice_number': '00011', 'invoice_date': '2026-11-06',
        'subtotal': '1025.00', 'tax': '102.50', 'total': '1127.50', 'currency': 'USD'}
    assert record.review_status == 'auto_checked' and record.issues == []
    candidate = record.fields['total'].candidates[0]
    assert (candidate.raw_text, candidate.page_number) == ('1127.50', 1)
    assert record.fields['total'].extracted_value == '1127.50'


def test_two_column_next_line_layout():
    lines = [_at('Vendor', (350, 'Bill To: Example Customer')), _at('Cedar Example Services'),
             _at('Invoice #', (270, 'Invoice Date')), _at('00022', (270, '6 Nov 2026')),
             'Subtotal: 1060.00', 'Tax: 106.00', 'Grand Total: 1166.00', 'Currency: EUR']
    record = _run('\n'.join(lines))
    assert _values(record) == {
        'supplier': 'Cedar Example Services', 'invoice_number': '00022', 'invoice_date': '2026-11-06',
        'subtotal': '1060.00', 'tax': '106.00', 'total': '1166.00', 'currency': 'EUR'}
    assert record.review_status == 'auto_checked'
    assert record.fields['invoice_number'].candidates[0].rule_id.endswith('next_line')


def test_two_page_synonyms_keep_actual_page_numbers():
    record = _run('From: Harbor Sample Supply\nInvoice No.: 00034\nInvoice Date: 2026-11-06',
                  'Sub-total: 1105.00\nVAT: 110.50\nAmount Due: 1215.50\nCurrency: HKD')
    assert _values(record) == {
        'supplier': 'Harbor Sample Supply', 'invoice_number': '00034', 'invoice_date': '2026-11-06',
        'subtotal': '1105.00', 'tax': '110.50', 'total': '1215.50', 'currency': 'HKD'}
    assert record.review_status == 'auto_checked'
    assert record.fields['supplier'].candidates[0].page_number == 1
    assert record.fields['currency'].candidates[0].page_number == 2


def test_each_currency_from_money_adjacent_code():
    for code in ('USD', 'EUR', 'GBP', 'HKD', 'CNY'):
        record = _run('\n'.join(BASE[:5] + [f'Total: {code} 1127.50']))
        assert record.fields['currency'].current_value == code
        assert record.fields['currency'].candidates[0].raw_text == code
        assert record.review_status == 'auto_checked'


def test_bare_dollar_sign_does_not_infer_currency():
    record = _run('\n'.join(BASE[:5] + ['Total: $1127.50']))
    assert record.fields['currency'].current_value is None
    assert ('missing_currency', 'currency') in _codes(record)


def test_differing_and_unsupported_currency_need_review():
    conflict = _run('\n'.join(BASE[:5] + ['Total: EUR 1127.50', 'Currency: USD']))
    assert conflict.fields['currency'].current_value is None
    assert ('currency_conflict', 'currency') in _codes(conflict)
    unsupported = _run('\n'.join(BASE[:6] + ['Currency: JPY']))
    assert unsupported.fields['currency'].current_value is None
    assert ('unsupported_currency', 'currency') in _codes(unsupported)
    assert unsupported.review_status == 'needs_review'


def test_explicit_invoice_date_beats_generic_date_and_conflicts_need_review():
    record = _run('\n'.join(BASE + ['Date: 2026-12-01']))
    assert record.fields['invoice_date'].current_value == '2026-11-06'
    assert len(record.fields['invoice_date'].candidates) == 2
    conflict = _run('\n'.join(BASE + ['Invoice Date: 2026-12-01']))
    assert conflict.fields['invoice_date'].current_value is None
    assert ('conflicting_values', 'invoice_date') in _codes(conflict)


def test_ambiguous_numeric_date_is_not_picked():
    record = _run('\n'.join(BASE[:2] + ['Invoice Date: 03/04/2026'] + BASE[3:]))
    assert record.fields['invoice_date'].current_value is None
    assert record.fields['invoice_date'].candidates[0].raw_text == '03/04/2026'
    assert ('unparsed_value', 'invoice_date') in _codes(record)
    assert record.review_status == 'needs_review'


def test_multiple_invoice_ids_flag_multi_invoice_but_repeated_heading_does_not():
    multi = _run('\n'.join(BASE), 'Invoice Number: 00012')
    assert multi.fields['invoice_number'].current_value is None
    assert ('multi_invoice', None) in _codes(multi)
    repeated = _run('INVOICE\n' + '\n'.join(BASE), 'INVOICE\nInvoice Number: 00011')
    assert repeated.fields['invoice_number'].current_value == '00011'
    assert repeated.review_status == 'auto_checked'


def test_missing_tax_is_not_invented():
    record = _run('\n'.join(line for line in BASE if not line.startswith('Tax')))
    assert record.fields['tax'].current_value is None
    assert record.fields['tax'].candidates == []
    assert ('missing_tax', 'tax') in _codes(record)


def test_negative_amounts_and_credit_note_need_review():
    record = _run('CREDIT NOTE\n' + '\n'.join(BASE[:5] + ['Total: -1127.50', 'Currency: USD']))
    assert record.fields['total'].current_value is None
    assert record.fields['total'].candidates[0].raw_text == '-1127.50'
    assert {('negative_amount', 'total'), ('credit_note', None)} <= _codes(record)
    assert record.review_status == 'needs_review'


def test_adjustment_amount_needs_review_without_unknown_field():
    record = _run('\n'.join(BASE[:4] + ['Discount: 10.00'] + BASE[4:]))
    assert ('adjustment_amount', None) in _codes(record)
    assert all(issue.field in (None, *record.fields) for issue in record.issues)
    assert record.review_status == 'needs_review'


def test_unknown_supplier_long_value_and_candidate_cap():
    missing = _run('\n'.join(BASE[1:]))
    assert missing.fields['supplier'].current_value is None
    assert ('missing_supplier', 'supplier') in _codes(missing)
    long_name = 'Supplier: ' + 'A' * 301
    long_record = _run('\n'.join([long_name] + BASE[1:]))
    assert ('value_too_long', 'supplier') in _codes(long_record)
    assert long_record.review_status == 'needs_review'
    capped = _run('\n'.join(BASE + ['Total: 1127.50'] * MAX_CANDIDATES))
    assert len(capped.fields['total'].candidates) == MAX_CANDIDATES
    assert ('candidate_limit', 'total') in _codes(capped)


def test_non_text_ready_returns_validated_empty_record_with_source_issues():
    source_issue = Issue(code='encrypted_pdf', message='encrypted', blocking=True)
    first = _run(status='failed', issues=[source_issue])
    second = _run(status='failed', issues=[source_issue])
    assert first.record_id != second.record_id
    assert (first.filename, first.file_sha256, first.processing_status) == ('a.pdf', 'abc', 'failed')
    assert all(value is None for value in _values(first).values())
    assert {'encrypted_pdf', 'source_not_text_ready'} <= {issue.code for issue in first.issues}
    assert first.review_status == 'needs_review'
def test_supplier_with_double_space_is_never_auto_checked_as_truncated():
    record = _run('\n'.join(['Supplier: Acme  Corporation'] + BASE[1:]))
    assert record.review_status == 'needs_review'
    assert ('unresolved_layout', 'supplier') in _codes(record)
    assert not (record.review_status == 'auto_checked' and _values(record)['supplier'] == 'Acme')
    assert any(candidate.raw_text == 'Acme' for candidate in record.fields['supplier'].candidates)


def test_edited_flagged_field_suppresses_then_restores_warning():
    record = _run('\n'.join(['Supplier: ' + 'A' * 301] + BASE[1:]))
    assert ('value_too_long', 'supplier') in _codes(record)
    apply_edits(record, {'supplier': 'Short Supplier'})
    assert record.review_status == 'needs_review'
    assert ('value_too_long', 'supplier') not in _codes(record)
    assert any(issue.code == 'value_too_long' for issue in record.original_issues)
    with pytest.raises(ValueError):
        confirm_record(record)
    confirm_record(record, 'Shortened supplier name checked against the source.')
    assert record.review_status == 'user_confirmed'
    reset_record(record)
    assert ('value_too_long', 'supplier') in _codes(record)
    assert record.review_status == 'needs_review'


def test_manual_edit_of_valid_unflagged_record_needs_confirmation_only():
    record = _run('\n'.join(BASE))
    assert record.review_status == 'auto_checked'
    apply_edits(record, {'invoice_number': '00012'})
    assert record.review_status == 'needs_review'
    confirm_record(record)
    assert record.review_status == 'user_confirmed'


def test_conflicting_total_edit_needs_reason_and_export_excludes_until_confirmed():
    record = _run('\n'.join(BASE + ['Total: 999.00']))
    assert ('conflicting_values', 'total') in _codes(record)
    apply_edits(record, {'total': '1127.50'})
    assert record.review_status == 'needs_review'
    with pytest.raises(ValueError):
        confirm_record(record)
    assert b'00011' not in build_exports([record])['invoices_csv']
    confirm_record(record, 'Total corrected to the matching value on the source.')
    evidence = build_exports([record])['evidence_csv'].decode('utf-8-sig')
    assert 'original_issue' in evidence and 'conflicting_values' in evidence
