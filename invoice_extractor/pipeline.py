from __future__ import annotations

import hashlib
import uuid

from invoice_extractor.dedupe import mark_duplicates
from invoice_extractor.extractor import extract
from invoice_extractor.models import InvoiceRecord, Issue, Limits
from invoice_extractor.pdf_reader import check_limits, read_pdf
from invoice_extractor.validator import validate


def process_batch(files: list[tuple[str, bytes]], limits: Limits = Limits()) -> list[InvoiceRecord]:
    check_limits(limits)
    if not isinstance(files, list) or len(files) > limits.max_files:
        raise ValueError(f'A batch may contain at most {limits.max_files} files.')
    for item in files:
        if not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[0], str) \
                or not isinstance(item[1], (bytes, bytearray)):
            raise ValueError('Each input must be a filename and PDF bytes.')
    if sum(len(data) for _, data in files) > limits.max_batch_bytes:
        raise ValueError(f'The batch exceeds {limits.max_batch_bytes // (1024 * 1024)} MiB.')
    records = []
    for filename, data in files:
        try:
            record = extract(read_pdf(data, filename, limits))
        except Exception:
            record = InvoiceRecord(
                record_id=str(uuid.uuid4()), filename=filename,
                file_sha256=hashlib.sha256(data).hexdigest(), processing_status='failed',
                issues=[Issue(code='processing_failed', message='This file could not be processed.')],
            )
        validate(record)
        records.append(record)
    mark_duplicates(records)
    return records
