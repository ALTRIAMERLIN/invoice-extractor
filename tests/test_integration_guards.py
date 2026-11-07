import pytest

from invoice_extractor.models import Limits
from invoice_extractor.pipeline import process_batch
from invoice_extractor.extractor import extract
from invoice_extractor.models import DocumentText
from invoice_extractor.review import confirm_record


def test_mixed_oversize_and_good_files_report_failed_and_continue():
    good = b'%PDF-1.4\n' + b'x' * 16
    records = process_batch(
        [('big.pdf', b'%PDF-' + b'x' * 64), ('good.pdf', good)],
        Limits(max_file_bytes=32),
    )
    assert [record.filename for record in records] == ['big.pdf', 'good.pdf']
    assert records[0].processing_status == 'over_limit'
    assert records[0].review_status == 'needs_review'
    assert records[1].filename == 'good.pdf'


def test_oversized_source_field_cannot_bypass_the_manual_value_limit():
    document = DocumentText(filename='long.pdf',file_sha256='long-source',page_count=1,pages=[
        'Supplier: '+'S'*400+'\nInvoice Number: 000123\nInvoice Date: 2026-11-06\n'
        'Subtotal: 100.00\nTax: 10.00\nTotal: 110.00\nCurrency: USD'])
    record = extract(document)
    assert record.review_status == 'needs_review'
    with pytest.raises(ValueError):
        confirm_record(record,'Reviewed, but the value is still outside the supported limit.')
