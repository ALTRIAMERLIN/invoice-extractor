import pytest

from invoice_extractor.dedupe import mark_duplicates
from invoice_extractor.models import InvoiceRecord, Issue

DEFAULTS = {
    'supplier': 'Acme',
    'invoice_number': 'INV-1',
    'invoice_date': '2026-11-06',
    'subtotal': '100.00',
    'tax': '10.00',
    'total': '110.00',
    'currency': 'USD',
}


def _record(record_id, file_sha256=None, **values):
    if file_sha256 is None:
        file_sha256 = record_id * 64
    record = InvoiceRecord(record_id=record_id, filename=f'{record_id}.pdf', file_sha256=file_sha256)
    for name, value in {**DEFAULTS, **values}.items():
        record.fields[name].extracted_value = value
        record.fields[name].current_value = value
    return record


def _codes(record):
    return [issue.code for issue in record.issues]


def _snapshot(records):
    return [
        (r.record_id, r.file_sha256, {n: (f.extracted_value, f.current_value) for n, f in r.fields.items()})
        for r in records
    ]


def test_exact_copy_marks_both_records_as_exact_duplicates():
    records = [
        _record('a', file_sha256='f' * 64),
        _record('b', file_sha256='f' * 64, supplier='Other', subtotal='4.00', tax='1.00', total='5.00'),
    ]
    mark_duplicates(records)
    for record in records:
        assert 'duplicate_exact' in _codes(record)
        assert 'duplicate_business' not in _codes(record)
        assert record.review_status == 'needs_review'
        assert all(group.startswith('exact-') for group in record.duplicate_group_ids)


def test_business_key_matches_normalized_values_across_different_files():
    records = [
        _record('a', file_sha256='1' * 64),
        _record('b', file_sha256='2' * 64, supplier='  acme ', invoice_number='inv-1', total='110,00'),
    ]
    mark_duplicates(records)
    for record in records:
        assert 'duplicate_business' in _codes(record)
        assert 'duplicate_exact' not in _codes(record)
        assert all(group.startswith('business-') for group in record.duplicate_group_ids)


@pytest.mark.parametrize(
    'overrides',
    [
        {'supplier': ' '},
        {'invoice_number': ''},
        {'currency': 'XXX'},
        {'currency': 'EUR'},
        {'total': '110.01'},
        {'total': None},
    ],
)
def test_blank_or_different_business_keys_do_not_match(overrides):
    records = [_record('a', file_sha256='1' * 64), _record('b', file_sha256='2' * 64, **overrides)]
    mark_duplicates(records)
    for record in records:
        assert not any(code.startswith('duplicate_') for code in _codes(record))
        assert record.duplicate_group_ids == []


def test_blank_file_hashes_never_match_each_other():
    records = [_record('a', file_sha256=''), _record('b', file_sha256=' ')]
    records[0].fields['supplier'].current_value = 'Acme A'
    records[1].fields['supplier'].current_value = 'Acme B'
    mark_duplicates(records)
    assert all(record.duplicate_group_ids == [] for record in records)


def test_field_edit_removes_record_from_group_and_restores_auto_checked():
    records = [_record('a'), _record('b', file_sha256='b' * 64)]
    mark_duplicates(records)
    old_ids = list(records[0].duplicate_group_ids)
    assert old_ids and records[0].review_status == 'needs_review'

    edited = records[1]
    edited.fields['subtotal'].current_value = '100.50'
    edited.fields['total'].current_value = '110.50'
    mark_duplicates(records)

    assert edited.duplicate_group_ids == []
    assert 'duplicate_business' not in _codes(edited)
    assert edited.review_status == 'auto_checked'
    assert records[0].duplicate_group_ids == []
    assert records[0].review_status == 'auto_checked'


def test_confirmed_duplicate_survives_rerun_but_clears_when_third_member_added():
    first, second = _record('a'), _record('b', file_sha256='b' * 64)
    mark_duplicates([first, second])
    first.review_status = 'user_confirmed'
    first.review_reason = 'same invoice, reviewed'
    old_ids = list(first.duplicate_group_ids)

    mark_duplicates([first, second])
    assert first.review_status == 'user_confirmed'
    assert first.review_reason == 'same invoice, reviewed'
    assert first.duplicate_group_ids == old_ids

    third = _record('c', file_sha256='c' * 64)
    mark_duplicates([first, second, third])
    assert first.review_status == 'needs_review'
    assert first.review_reason == ''
    assert set(first.duplicate_group_ids).isdisjoint(old_ids)
    assert _codes(first).count('duplicate_business') == 1


def test_removed_member_clears_stale_duplicate_issue_and_restores_auto_checked():
    first, second = _record('a'), _record('b', file_sha256='b' * 64)
    mark_duplicates([first, second])
    mark_duplicates([first])
    assert not any(code.startswith('duplicate_') for code in _codes(first))
    assert first.duplicate_group_ids == []
    assert first.review_status == 'auto_checked'


def test_marking_preserves_values_other_issues_and_records():
    first = _record('a', file_sha256='c' * 64)
    second = _record('b', file_sha256='c' * 64, total='110.00')
    second.processing_status = 'failed'
    second.issues.append(Issue(code='invalid_pdf', message='source could not be parsed', blocking=True))
    records = [first, second]
    before = _snapshot(records)

    mark_duplicates(records)
    mark_duplicates(records)

    assert _snapshot(records) == before
    assert [r.record_id for r in records] == ['a', 'b']
    assert second.processing_status == 'failed'
    assert 'invalid_pdf' in _codes(second)
    assert 'source_not_text_ready' in _codes(second)
    assert _codes(second).count('duplicate_exact') == 1
    assert second.review_status == 'needs_review'
