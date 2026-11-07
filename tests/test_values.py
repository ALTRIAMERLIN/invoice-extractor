import pytest

from invoice_extractor.models import Candidate, InvoiceRecord, Issue
from invoice_extractor.validator import parse_date, parse_money, validate


def _record(**values: str | None) -> InvoiceRecord:
    record = InvoiceRecord(record_id='r1', filename='a.pdf', file_sha256='0' * 64)
    defaults = {
        'supplier': 'Acme',
        'invoice_number': 'INV-1',
        'invoice_date': '2026-11-06',
        'subtotal': '100.00',
        'tax': '10.00',
        'total': '110.00',
        'currency': 'USD',
    }
    defaults.update(values)
    for name, value in defaults.items():
        record.fields[name].extracted_value = value
        record.fields[name].current_value = value
    return record


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('0', '0.00'),
        ('0.5', '0.50'),
        ('1,234.56', '1234.56'),
        ('1.234,56', '1234.56'),
        ('1.234.567,89', '1234567.89'),
        ('12,5', '12.50'),
        ('$ 99.99', '99.99'),
        ('USD 10', '10.00'),
        ('999999999.99', '999999999.99'),
    ],
)
def test_parse_money_accepts_canonical_forms(raw, expected):
    assert parse_money(raw) == expected


@pytest.mark.parametrize(
    'raw',
    [
        '',
        '   ',
        '-1.00',
        '+1.00',
        '(10.00)',
        '1000000000.00',
        '1.005',
        '1,2,3,4',
        '1,234,5',
        '1.234',
        '1,234',
        '1e3',
        'NaN',
        'Inf',
        '10%',
        '1$2',
        'abc',
    ],
)
def test_parse_money_rejects_invalid_or_ambiguous(raw):
    with pytest.raises(ValueError):
        parse_money(raw)


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('2026-11-06', '2026-11-06'),
        ('6 Nov 2026', '2026-11-06'),
        ('November 6, 2026', '2026-11-06'),
        ('06 November 2026', '2026-11-06'),
        ('13/04/2026', '2026-04-13'),
        ('04/13/2026', '2026-04-13'),
        ('05/05/2026', '2026-05-05'),
    ],
)
def test_parse_date_accepts_unambiguous_forms(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    'raw',
    ['03/04/2026', '2026-02-30', '31/09/2026', '6 Foo 2026', 'soon', '', '2026/11/06'],
)
def test_parse_date_rejects_ambiguous_or_invalid(raw):
    with pytest.raises(ValueError):
        parse_date(raw)


def test_valid_record_has_no_issues_and_auto_checked_status():
    record = _record()
    assert validate(record) == []
    assert record.review_status == 'auto_checked'


def test_missing_field_is_reviewable_not_blocking():
    record = _record(tax=None)
    issues = validate(record)
    missing = [issue for issue in issues if issue.code == 'missing_tax']
    assert len(missing) == 1
    assert missing[0].blocking is False
    assert record.review_status == 'needs_review'


def test_invalid_money_is_blocking():
    record = _record(total='1.234')
    issues = validate(record)
    invalid = [issue for issue in issues if issue.code == 'invalid_total']
    assert len(invalid) == 1
    assert invalid[0].blocking is True


def test_whitespace_only_value_counts_as_missing():
    record = _record(supplier='   ')
    codes = {issue.code for issue in validate(record)}
    assert 'missing_supplier' in codes
    assert 'invalid_supplier' not in codes


def test_unsupported_currency_is_blocking():
    record = _record(currency='JPY')
    issue = next(issue for issue in validate(record) if issue.field == 'currency')
    assert issue.blocking is True


def test_money_mismatch_outside_tolerance_is_reviewable():
    record = _record(total='111.00')
    issues = validate(record)
    mismatch = [issue for issue in issues if issue.code == 'money_mismatch']
    assert len(mismatch) == 1
    assert mismatch[0].blocking is False


def test_money_mismatch_within_one_cent_is_accepted():
    record = _record(subtotal='100.00', tax='10.00', total='110.01')
    assert not [issue for issue in validate(record) if issue.code == 'money_mismatch']


def test_repeated_validation_keeps_structural_issues_and_confirmation():
    record = _record()
    structural = Issue(code='processing_error', message='could not read page 2')
    record.issues.append(structural)
    record.review_status = 'user_confirmed'
    validate(record)
    validate(record)
    assert structural in record.issues
    assert record.review_status == 'user_confirmed'


def test_blocking_invalid_value_removes_confirmation():
    record = _record()
    record.review_status = 'user_confirmed'
    record.fields['total'].current_value = 'oops'
    validate(record)
    assert record.review_status == 'needs_review'
    assert any(issue.code == 'invalid_total' and issue.blocking for issue in record.issues)


def test_user_edit_resolves_field_extraction_issue():
    record = _record()
    record.issues.append(Issue(code='ambiguous_date', message='two dates', field='invoice_date'))
    validate(record)
    assert any(issue.code == 'ambiguous_date' for issue in record.issues)
    record.fields['invoice_date'].edited_by_user = True
    record.fields['invoice_date'].current_value = '2026-11-06'
    validate(record)
    assert not any(issue.code == 'ambiguous_date' for issue in record.issues)


def test_validate_does_not_mutate_candidates_or_extracted_values():
    record = _record(tax=None)
    candidate = Candidate(raw_text='10.00', page_number=1, rule_id='tax-1')
    record.fields['tax'].candidates.append(candidate)
    validate(record)
    assert record.fields['tax'].extracted_value is None
    assert record.fields['tax'].candidates == [candidate]


def test_failed_source_with_valid_fields_needs_review_with_source_issue():
    record = _record()
    record.processing_status = 'failed'
    record.issues.append(Issue(code='invalid_pdf', message='source could not be parsed', blocking=True))
    validate(record)
    codes = [issue.code for issue in record.issues]
    assert record.review_status == 'needs_review'
    assert 'invalid_pdf' in codes
    assert 'source_not_text_ready' in codes
    assert record.processing_status == 'failed'


def test_user_confirmed_failed_source_keeps_status_and_source_issue_on_repeat():
    record = _record()
    record.processing_status = 'failed'
    record.review_status = 'user_confirmed'
    validate(record)
    validate(record)
    codes = [issue.code for issue in record.issues]
    assert record.review_status == 'user_confirmed'
    assert record.processing_status == 'failed'
    assert codes.count('source_not_text_ready') == 1


def test_source_failure_issue_clears_when_source_is_text_ready():
    record = _record()
    record.processing_status = 'failed'
    validate(record)
    record.processing_status = 'text_ready'
    validate(record)
    assert 'source_not_text_ready' not in [issue.code for issue in record.issues]
    assert record.review_status == 'auto_checked'


def test_invalid_source_code_is_not_regenerated_away():
    record = _record()
    record.issues.append(Issue(code='invalid_pdf', message='source could not be parsed', blocking=True))
    validate(record)
    assert 'invalid_pdf' in [issue.code for issue in record.issues]
    assert record.review_status == 'needs_review'
