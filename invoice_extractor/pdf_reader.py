from __future__ import annotations

import hashlib
import io
import math
import multiprocessing
import time

from invoice_extractor.models import DocumentText, Issue, Limits

PDF_HEADER = b'%PDF-'
HEADER_WINDOW = 1024
JOIN_GRACE_SECONDS = 2.0


def check_limits(limits: Limits) -> None:
    if not isinstance(limits, Limits):
        raise ValueError('limits must be a Limits instance')
    for name in ('max_files', 'max_file_bytes', 'max_batch_bytes', 'max_pages', 'max_page_chars',
                 'max_document_chars'):
        value = getattr(limits, name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f'{name} must be a positive integer')
    timeout = limits.timeout_seconds
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) \
            or timeout <= 0:
        raise ValueError('timeout_seconds must be a positive finite number')


def _issue(code: str, message: str) -> list[Issue]:
    return [Issue(code=code, message=message)]


def _page_text(page) -> str:
    try:
        text = page.extract_text(extraction_mode='layout')
    except Exception:
        text = page.extract_text()
    lines = (text or '').replace('\x00', '').splitlines()
    return '\n'.join(line.rstrip() for line in lines)


def _parse_pdf(data: bytes, limits: Limits) -> tuple[str, int, list[str], list[Issue]]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            return 'encrypted', 0, [], _issue('pdf_encrypted', 'The PDF is encrypted and cannot be read.')
        page_count = len(reader.pages)
    except Exception:
        return 'invalid_pdf', 0, [], _issue('pdf_unreadable', 'The file is not a readable PDF.')
    if page_count == 0:
        return 'invalid_pdf', 0, [], _issue('pdf_unreadable', 'The PDF has no pages.')
    if page_count > limits.max_pages:
        return 'over_limit', page_count, [], _issue(
            'pdf_too_many_pages', f'The PDF has more than {limits.max_pages} pages.')
    pages: list[str] = []
    total_chars = 0
    for page in reader.pages:
        try:
            text = _page_text(page)
        except Exception:
            return 'failed', page_count, [], _issue('pdf_text_failed', 'Text could not be read from the PDF.')
        if len(text) > limits.max_page_chars:
            return 'over_limit', page_count, [], _issue(
                'pdf_page_text_limit', f'A page has more than {limits.max_page_chars} characters.')
        total_chars += len(text)
        if total_chars > limits.max_document_chars:
            return 'over_limit', page_count, [], _issue(
                'pdf_document_text_limit', f'The PDF has more than {limits.max_document_chars} characters.')
        pages.append(text)
    if not any(text.strip() for text in pages):
        return 'no_text', page_count, [], _issue(
            'pdf_no_text', 'No text layer was found. Scanned PDFs are not supported.')
    return 'text_ready', page_count, pages, []


def _worker(conn, data: bytes, limits: Limits) -> None:
    import logging
    import warnings

    logging.disable(logging.CRITICAL)
    warnings.simplefilter('ignore')
    try:
        status, page_count, pages, issues = _parse_pdf(data, limits)
        result = ('ok', (status, page_count, pages, [(item.code, item.message) for item in issues]))
    except BaseException:
        result = ('error', None)
    try:
        conn.send(result)
    finally:
        conn.close()


def _stop(process, grace_seconds: float) -> None:
    if process.is_alive() and grace_seconds > 0:
        process.join(grace_seconds)
    if process.is_alive():
        process.terminate()
        process.join(JOIN_GRACE_SECONDS)
    if process.is_alive():
        process.kill()
    process.join()


def _run_child(target, args: tuple, timeout_seconds: float) -> tuple[str, object]:
    deadline = time.monotonic() + timeout_seconds
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=target, args=(sender, *args), daemon=True)
    received = False
    try:
        process.start()
        sender.close()
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not receiver.poll(remaining):
            return 'timeout', None
        try:
            message = receiver.recv()
        except (EOFError, OSError):
            return 'crashed', None
        received = True
        return 'ok', message
    finally:
        sender.close()
        receiver.close()
        if process.pid is not None:
            _stop(process, JOIN_GRACE_SECONDS if received else 0)
            process.close()


def _document(filename: str, digest: str, status: str, issues: list[Issue], page_count: int = 0,
              pages: list[str] | None = None) -> DocumentText:
    return DocumentText(filename=filename, file_sha256=digest, page_count=page_count, pages=pages or [],
                        status=status, issues=issues)


def _valid_result(payload: object, limits: Limits) -> bool:
    if not isinstance(payload, tuple) or len(payload) != 4:
        return False
    status, page_count, pages, issues = payload
    return (status in {'text_ready', 'no_text', 'encrypted', 'invalid_pdf', 'over_limit', 'failed'}
            and isinstance(page_count, int) and isinstance(pages, list) and len(pages) <= limits.max_pages
            and all(isinstance(text, str) for text in pages) and isinstance(issues, list)
            and all(isinstance(item, tuple) and len(item) == 2 for item in issues))


def read_pdf(data: bytes, filename: str, limits: Limits = Limits()) -> DocumentText:
    check_limits(limits)
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError('data must be bytes')
    data = bytes(data)
    filename = str(filename)
    digest = hashlib.sha256(data).hexdigest()
    if not filename.lower().endswith('.pdf'):
        return _document(filename, digest, 'invalid_pdf',
                         _issue('unsupported_file_type', 'Only .pdf files are supported.'))
    if len(data) > limits.max_file_bytes:
        return _document(filename, digest, 'over_limit', _issue(
            'file_too_large', f'The file is larger than {limits.max_file_bytes} bytes.'))
    if PDF_HEADER not in data[:HEADER_WINDOW]:
        return _document(filename, digest, 'invalid_pdf',
                         _issue('pdf_unreadable', 'The file does not have a PDF header.'))
    outcome, message = _run_child(_worker, (data, limits), limits.timeout_seconds)
    if outcome == 'timeout':
        return _document(filename, digest, 'timeout', _issue(
            'pdf_timeout', f'Reading the PDF took longer than {limits.timeout_seconds} seconds.'))
    if outcome != 'ok' or not isinstance(message, tuple) or len(message) != 2 or message[0] != 'ok' \
            or not _valid_result(message[1], limits):
        return _document(filename, digest, 'failed',
                         _issue('pdf_reader_failed', 'The PDF reader failed on this file.'))
    status, page_count, pages, raw_issues = message[1]
    issues = [Issue(code=str(code), message=str(text)) for code, text in raw_issues]
    return _document(filename, digest, status, issues, page_count, pages)
