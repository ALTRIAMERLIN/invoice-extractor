import io
import multiprocessing
import os
import time
from pathlib import Path

import pytest
from pypdf import PdfWriter

from invoice_extractor.models import Limits
from invoice_extractor.pdf_reader import _run_child, read_pdf

FIXTURES = Path(__file__).parent/'fixtures'


def _sleep_worker(connection):
    time.sleep(10)


def _crash_worker(connection):
    os._exit(3)


def _large_worker(connection):
    connection.send('x'*800_000)
    connection.close()


def pdf_bytes():
    return (FIXTURES/'invoice-layout-1-USD.pdf').read_bytes()


def test_actual_spawn_reads_text_and_source_pages():
    data = (FIXTURES/'invoice-layout-3-HKD.pdf').read_bytes()
    result = read_pdf(data,'two-pages.pdf')
    assert result.status == 'text_ready'
    assert result.page_count == 2 and len(result.pages) == 2
    assert 'Harbor Sample Supply' in result.pages[0]
    assert 'Amount Due' in result.pages[1]
    assert len(result.file_sha256) == 64


def test_unreadable_input_has_generic_error_and_no_log_leak(capfd):
    result = read_pdf(b'%PDF-1.4\nsecret-supplier-12345','private-invoice-12345.pdf')
    assert result.status == 'invalid_pdf'
    captured = capfd.readouterr()
    assert '12345' not in captured.out+captured.err
    assert all('12345' not in issue.message for issue in result.issues)


def test_encrypted_and_no_text_inputs_are_reported():
    writer = PdfWriter()
    writer.add_blank_page(width=100,height=100)
    blank = io.BytesIO()
    writer.write(blank)
    assert read_pdf(blank.getvalue(),'blank.pdf').status == 'no_text'
    writer.encrypt('fictional-demo-password')
    encrypted = io.BytesIO()
    writer.write(encrypted)
    assert read_pdf(encrypted.getvalue(),'encrypted.pdf').status == 'encrypted'


def test_individual_limits_and_actual_pdf_type_check():
    assert read_pdf(pdf_bytes(),'disguised.txt').status == 'invalid_pdf'
    assert read_pdf(b'not a pdf','disguised.pdf').status == 'invalid_pdf'
    assert read_pdf(pdf_bytes(),'large.pdf',Limits(max_file_bytes=10)).status == 'over_limit'
    assert read_pdf((FIXTURES/'invoice-layout-3-HKD.pdf').read_bytes(),'pages.pdf',Limits(max_pages=1)).status == 'over_limit'
    assert read_pdf(pdf_bytes(),'page-text.pdf',Limits(max_page_chars=10)).status == 'over_limit'
    assert read_pdf(pdf_bytes(),'document-text.pdf',Limits(max_document_chars=10)).status == 'over_limit'


@pytest.mark.parametrize('limits',[Limits(max_pages=0),Limits(max_files=True),
                                  Limits(timeout_seconds=0),Limits(timeout_seconds=float('inf'))])
def test_invalid_limits_fail_before_process_start(limits):
    with pytest.raises(ValueError):
        read_pdf(pdf_bytes(),'demo.pdf',limits)


def test_timeout_really_stops_and_reaps_the_child():
    before = {p.pid for p in multiprocessing.active_children()}
    started = time.monotonic()
    outcome,_ = _run_child(_sleep_worker,(),.15)
    assert outcome == 'timeout'
    assert time.monotonic()-started < 5
    assert not ({p.pid for p in multiprocessing.active_children()}-before)
    assert read_pdf(pdf_bytes(),'deadline.pdf',Limits(timeout_seconds=.000001)).status == 'timeout'
    assert not ({p.pid for p in multiprocessing.active_children()}-before)


def test_child_crash_and_large_pipe_response_cannot_deadlock():
    started = time.monotonic()
    assert _run_child(_crash_worker,(),5)[0] == 'crashed'
    outcome,payload = _run_child(_large_worker,(),5)
    assert outcome == 'ok' and len(payload) == 800_000
    assert time.monotonic()-started < 10


def test_reader_remains_usable_after_a_failed_file():
    first = read_pdf(b'%PDF-1.4 broken','broken.pdf')
    second = read_pdf(pdf_bytes(),'good.pdf')
    assert first.status == 'invalid_pdf' and second.status == 'text_ready'
