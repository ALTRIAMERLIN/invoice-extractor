from pathlib import Path

import streamlit as st

from invoice_extractor.dedupe import mark_duplicates
from invoice_extractor.exporter import build_exports
from invoice_extractor.models import FIELD_NAMES, InvoiceRecord, Limits
from invoice_extractor.pipeline import process_batch
from invoice_extractor.review import apply_edits, confirm_record, reset_record

SAMPLE_DIR = Path(__file__).resolve().parent / 'samples'
LIMITS = Limits()
FIELD_LABELS = {
    'supplier': 'Supplier',
    'invoice_number': 'Invoice number',
    'invoice_date': 'Invoice date (YYYY-MM-DD)',
    'subtotal': 'Subtotal',
    'tax': 'Tax',
    'total': 'Total',
    'currency': 'Currency (USD, EUR, GBP, HKD, CNY)',
}
REVIEW_LABELS = {
    'needs_review': 'Needs review',
    'auto_checked': 'Auto-checked',
    'user_confirmed': 'Confirmed',
}
PROCESSING_LABELS = {
    'text_ready': 'Readable',
    'no_text': 'No text layer',
    'encrypted': 'Encrypted',
    'invalid_pdf': 'Invalid PDF',
    'timeout': 'Timed out',
    'over_limit': 'Over limit',
    'failed': 'Failed',
}
EXPORT_MODE_LABELS = {
    False: 'Default: auto-checked and confirmed records, not excluded',
    True: 'All non-excluded records, including records that need review',
}


def _init_state() -> None:
    defaults = {
        'records': [],
        'revision': 0,
        'drafts': {},
        'reason_drafts': {},
        'confirmation': None,
        'message': None,
        'uploader_nonce': 0,
        'uploads_dirty': False,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _display(value: str | None) -> str:
    return value or ''


def _edit_key(record_id: str, name: str) -> str:
    return f'edit::{record_id}::{name}'


def _find(record_id: str) -> InvoiceRecord | None:
    for record in st.session_state.records:
        if record.record_id == record_id:
            return record
    return None


def _unsaved_fields(record: InvoiceRecord) -> list[str]:
    drafts = st.session_state.drafts.get(record.record_id, {})
    return [
        name
        for name, text in drafts.items()
        if text.strip() != _display(record.fields[name].current_value).strip()
    ]


def _has_unsaved(records: list[InvoiceRecord]) -> bool:
    return any(
        _unsaved_fields(record)
        or st.session_state.reason_drafts.get(record.record_id, record.review_reason) != record.review_reason
        for record in records
    )


def _changed() -> None:
    st.session_state.confirmation = None
    st.session_state.revision += 1


def _clear_edit_widgets(record_id: str) -> None:
    prefix = f'edit::{record_id}::'
    for key in list(st.session_state.keys()):
        if key.startswith(prefix):
            del st.session_state[key]


def _clear_record_widgets(record_id: str) -> None:
    prefixes = (f'edit::{record_id}::', f'reason::{record_id}', f'exclude::{record_id}')
    for key in list(st.session_state.keys()):
        if key.startswith(prefixes):
            del st.session_state[key]


def _set_batch(records: list[InvoiceRecord]) -> None:
    for record_id in [record.record_id for record in st.session_state.records]:
        _clear_record_widgets(record_id)
    st.session_state.records = records
    st.session_state.drafts = {}
    st.session_state.reason_drafts = {}
    st.session_state.pop('selected_record_id', None)
    st.session_state.pop('export_mode', None)
    st.session_state.uploads_dirty = False
    st.session_state.uploader_nonce += 1
    _changed()


def _store_draft(record_id: str, name: str) -> None:
    st.session_state.drafts.setdefault(record_id, {})[name] = st.session_state[_edit_key(record_id, name)]


def _store_reason(record_id: str) -> None:
    st.session_state.reason_drafts[record_id] = st.session_state[f'reason::{record_id}']
    st.session_state.confirmation = None


def _clear_reason(record_id: str) -> None:
    st.session_state.pop(f'reason::{record_id}', None)
    st.session_state.reason_drafts.pop(record_id, None)


def _refresh_duplicates() -> None:
    previous = {record.record_id: (record.review_status, tuple(record.duplicate_group_ids))
                for record in st.session_state.records}
    mark_duplicates(st.session_state.records)
    for record in st.session_state.records:
        old_status, old_groups = previous[record.record_id]
        if old_groups != tuple(record.duplicate_group_ids) or (
            old_status == 'user_confirmed' and record.review_status != 'user_confirmed'
        ):
            _clear_reason(record.record_id)


def _save_record(record_id: str) -> None:
    record = _find(record_id)
    drafts = st.session_state.drafts.get(record_id, {})
    edits = {name: drafts[name] for name in _unsaved_fields(record)}
    before = len(record.edit_history)
    try:
        apply_edits(record, edits)
    except ValueError as error:
        st.session_state.message = ('error', f'Not saved. {error}')
        return
    st.session_state.drafts.pop(record_id, None)
    _clear_edit_widgets(record_id)
    if len(record.edit_history) == before:
        st.session_state.message = ('info', 'No changes to save.')
        return
    _clear_reason(record_id)
    _refresh_duplicates()
    _changed()
    st.session_state.message = ('success', 'Changes saved. Review checks and duplicate groups were updated.')


def _restore_record(record_id: str) -> None:
    record = _find(record_id)
    reset_record(record)
    st.session_state.drafts.pop(record_id, None)
    _clear_edit_widgets(record_id)
    _clear_reason(record_id)
    _refresh_duplicates()
    _changed()
    st.session_state.message = ('success', 'Extracted values restored. Edit history is kept.')


def _confirm_record(record_id: str) -> None:
    record = _find(record_id)
    if _unsaved_fields(record):
        st.session_state.message = ('error', 'Save or restore unsaved edits before confirming this record.')
        return
    reason = st.session_state.get(f'reason::{record_id}', '')
    try:
        confirm_record(record, reason)
    except ValueError as error:
        st.session_state.message = ('error', str(error))
        return
    st.session_state.reason_drafts.pop(record_id, None)
    _changed()
    st.session_state.message = ('success', 'Record confirmed for export.')


def _toggle_excluded(record_id: str) -> None:
    record = _find(record_id)
    record.excluded = st.session_state[f'exclude::{record_id}']
    _changed()


def _clear_batch() -> None:
    _set_batch([])
    st.session_state.message = ('info', 'The batch was cleared from this session.')


def _confirm_batch() -> None:
    if st.session_state.uploads_dirty or _has_unsaved(st.session_state.records):
        st.session_state.message = ('error', 'Process or keep pending uploads, and save unsaved edits, before confirming.')
        return
    st.session_state.confirmation = (st.session_state.revision, st.session_state.export_mode)


def _uploads_changed() -> None:
    st.session_state.uploads_dirty = True
    st.session_state.confirmation = None


def _keep_current_batch() -> None:
    st.session_state.uploader_nonce += 1
    st.session_state.uploads_dirty = False
    st.session_state.confirmation = None
    st.session_state.message = ('info', 'Kept the current batch. Pending uploads were discarded.')


def _run_batch(files: list[tuple[str, bytes]]) -> None:
    try:
        records = process_batch(files, LIMITS)
    except ValueError as error:
        st.session_state.message = ('error', f'Batch not processed. {error}')
        return
    _set_batch(records)
    st.session_state.message = ('success', f'Processed {len(records)} file(s).')


def _demo_paths() -> list[Path]:
    if not SAMPLE_DIR.is_dir():
        return []
    return [path for path in sorted(SAMPLE_DIR.glob('*.pdf')) if 'expected' not in path.name.lower()]


def _overview_rows(records: list[InvoiceRecord]) -> list[dict]:
    rows = []
    for record in records:
        if record.processing_status != 'text_ready':
            status = PROCESSING_LABELS.get(record.processing_status, 'Failed')
        else:
            status = REVIEW_LABELS[record.review_status]
        if record.excluded:
            status = f'{status} (excluded)'
        rows.append(
            {
                'File': record.filename,
                'Status': status,
                'Amount': _display(record.fields['total'].current_value),
                'Currency': _display(record.fields['currency'].current_value),
                'Issues': len(record.issues),
            }
        )
    return rows


def _render_message() -> None:
    message = st.session_state.message
    if message is None:
        return
    level, text = message
    getattr(st, level)(text)
    st.session_state.message = None


def _render_sidebar() -> None:
    with st.sidebar:
        st.subheader('About this tool')
        st.markdown(
            '- Runs locally. No invoice data leaves this computer.\n'
            '- Reads English text-based PDFs only. No OCR.\n'
            '- Scanned, image-only, encrypted and damaged PDFs are reported as failed.\n'
            '- Results are held in this browser session only.'
        )
        st.subheader('Limits')
        st.markdown(
            f'- {LIMITS.max_files} files per batch\n'
            f'- {LIMITS.max_file_bytes // (1024 * 1024)} MiB per file\n'
            f'- {LIMITS.max_batch_bytes // (1024 * 1024)} MiB per batch\n'
            f'- {LIMITS.max_pages} pages per file\n'
            f'- {int(LIMITS.timeout_seconds)} seconds per file'
        )


def _render_load(uploads: list) -> None:
    st.subheader('1. Load invoices')
    left, right = st.columns([3, 1])
    with left:
        st.caption('Upload English text PDFs. Each file is one invoice, and multi-page invoices are supported.')
    with right:
        if st.button('Process uploaded files', disabled=not uploads, type='primary', width='stretch'):
            _run_batch([(upload.name, upload.getvalue()) for upload in uploads])
            st.rerun()
    demo = _demo_paths()
    if demo:
        if st.button(f'Load {len(demo)} built-in demo invoice(s)'):
            _run_batch([(path.name, path.read_bytes()) for path in demo])
            st.rerun()
    if st.session_state.uploads_dirty:
        st.warning(
            'New PDFs are selected but not processed. Export stays disabled until you process them '
            'or keep the current batch.'
        )
        st.button('Keep current batch instead', on_click=_keep_current_batch)


def _render_overview(records: list[InvoiceRecord]) -> None:
    st.subheader('2. Batch overview')
    if not records:
        st.info('No invoices in this batch. Upload PDFs above to begin.')
        return
    counts = {
        'Files': len(records),
        'Auto-checked': sum(record.review_status == 'auto_checked' for record in records),
        'Needs review': sum(record.review_status == 'needs_review' for record in records),
        'Confirmed': sum(record.review_status == 'user_confirmed' for record in records),
        'Excluded': sum(record.excluded for record in records),
        'Failed': sum(record.processing_status != 'text_ready' for record in records),
    }
    for column, (label, count) in zip(st.columns(len(counts)), counts.items()):
        column.metric(label, count)
    st.dataframe(_overview_rows(records), hide_index=True, width='stretch')


def _render_problems(record: InvoiceRecord) -> None:
    if record.processing_status != 'text_ready':
        st.error(f'This file could not be read: {PROCESSING_LABELS.get(record.processing_status, "Failed")}.')
    for issue in record.issues:
        if issue.blocking:
            st.error(issue.message)
        else:
            st.warning(issue.message)
    if record.duplicate_group_ids:
        st.warning('Possible duplicate of another record in this batch. Duplicates are not removed.')


def _render_field(record: InvoiceRecord, name: str) -> None:
    field_value = record.fields[name]
    drafts = st.session_state.drafts.get(record.record_id, {})
    left, right = st.columns([3, 2])
    with left:
        st.text_input(
            FIELD_LABELS[name],
            value=drafts.get(name, _display(field_value.current_value)),
            key=_edit_key(record.record_id, name),
            on_change=_store_draft,
            args=(record.record_id, name),
            help='Edit the value here. The original extracted value is shown in Source evidence.',
        )
    with right:
        with st.expander(f'Source evidence ({len(field_value.candidates)})'):
            st.text(f'Original extracted value: {_display(field_value.extracted_value) or "none"}')
            if not field_value.candidates:
                st.caption('No source text matched this field.')
            for candidate in field_value.candidates:
                st.text(f'Page {candidate.page_number}: {candidate.raw_text}')
                if candidate.context:
                    st.text(candidate.context)
            if field_value.edited_by_user:
                st.caption('Edited by user. Restore extracted values to return to the original.')


def _render_record(record: InvoiceRecord) -> None:
    rid = record.record_id
    st.text(record.filename)
    st.caption(f'Pages: {record.page_count} · Status: {REVIEW_LABELS[record.review_status]}')
    _render_problems(record)
    if record.review_status != 'user_confirmed' and any(value.edited_by_user for value in record.fields.values()):
        st.info('Saved edits need record confirmation before they enter the default export.')
    if _unsaved_fields(record):
        st.warning('Unsaved changes. Save or restore before exporting or confirming.')
    for name in FIELD_NAMES:
        _render_field(record, name)
    save_col, restore_col = st.columns(2)
    save_col.button('Save changes', key=f'save::{rid}', on_click=_save_record, args=(rid,), type='primary', width='stretch')
    restore_col.button(
        'Restore extracted values', key=f'restore::{rid}', on_click=_restore_record, args=(rid,), width='stretch'
    )
    st.checkbox(
        'Exclude this record from export',
        value=record.excluded,
        key=f'exclude::{rid}',
        on_change=_toggle_excluded,
        args=(rid,),
    )
    st.text_area(
        'Manual review reason (required to confirm when issues, duplicates or missing values remain)',
        value=st.session_state.reason_drafts.get(rid, record.review_reason),
        key=f'reason::{rid}',
        max_chars=500,
        on_change=_store_reason,
        args=(rid,),
    )
    st.button(
        'Confirm record',
        key=f'confirm::{rid}',
        on_click=_confirm_record,
        args=(rid,),
        disabled=bool(_unsaved_fields(record)),
    )


def _render_review(records: list[InvoiceRecord]) -> None:
    st.subheader('3. Review record')
    if not records:
        st.caption('Records appear here after processing.')
        return
    ids = [record.record_id for record in records]
    if st.session_state.get('selected_record_id') not in ids:
        st.session_state.selected_record_id = ids[0]
    labels = {
        record.record_id: f'{index}. {record.filename} ({record.record_id[:8]})'
        for index, record in enumerate(records, start=1)
    }
    selected = st.selectbox(
        'Invoice',
        ids,
        format_func=labels.get,
        key='selected_record_id',
    )
    _render_record(_find(selected))


def _render_export(records: list[InvoiceRecord]) -> None:
    st.subheader('4. Export')
    if not records:
        st.caption('Process a batch before exporting.')
        return
    include_all = st.radio(
        'Records to include',
        [False, True],
        format_func=EXPORT_MODE_LABELS.get,
        key='export_mode',
        on_change=lambda: st.session_state.update(confirmation=None),
    )
    pending = st.session_state.uploads_dirty
    unsaved = pending or _has_unsaved(records)
    selected_count = sum(not record.excluded and (include_all or record.review_status in ('auto_checked', 'user_confirmed'))
                         for record in records)
    st.caption(f'{selected_count} of {len(records)} records will be exported with this selection.')
    confirmed = st.session_state.confirmation == (st.session_state.revision, include_all)
    if pending:
        st.warning('Pending uploads must be processed or kept before exporting.')
    elif unsaved:
        st.warning('Save or restore field edits, and confirm any changed review reason before exporting.')
    elif confirmed:
        st.success('Batch confirmed for the current selection. Downloads reflect the current records.')
    else:
        st.info('Confirm the batch to enable downloads. Any later change requires confirming again.')
    st.button(
        'Confirm batch for export',
        on_click=_confirm_batch,
        disabled=unsaved,
        type='primary',
    )
    if unsaved or not confirmed:
        return
    files = build_exports(records, include_all=include_all)
    columns = st.columns(4)
    downloads = [
        ('Invoices (.xlsx)', 'xlsx', 'invoices.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
        ('Invoices (.csv)', 'invoices_csv', 'invoices.csv', 'text/csv'),
        ('Evidence (.csv)', 'evidence_csv', 'evidence.csv', 'text/csv'),
        ('Batch report (.csv)', 'batch_csv', 'batch_report.csv', 'text/csv'),
    ]
    for column, (label, key, file_name, mime) in zip(columns, downloads):
        column.download_button(
            label,
            data=files[key],
            file_name=file_name,
            mime=mime,
            on_click='ignore',
            width='stretch',
        )


def main() -> None:
    st.set_page_config(page_title='Invoice Extractor', layout='wide')
    _init_state()
    st.markdown(
        """
        <style>
        .block-container {padding-top: 2.5rem; padding-bottom: 3rem; max-width: 1180px;}
        h1, h2, h3 {color: #0f172a;}
        [data-testid="stMetricValue"] {color: #0f766e; font-size: 1.5rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    _render_sidebar()
    st.title('Invoice Extractor')
    st.caption('Extract key fields from text-based English PDF invoices, review the evidence, then export.')
    st.warning(
        'Work is held in this browser session only. Refreshing the page or restarting the app can lose work. '
        'No OCR is performed. Only text-based PDFs are read. All processing runs locally.'
    )
    _render_message()
    uploads = st.file_uploader(
        'Invoice PDFs',
        type=['pdf'],
        accept_multiple_files=True,
        help='Files over 10 MiB are listed as over-limit and are not parsed. The whole batch is limited to 100 MiB.',
        key=f'uploads::{st.session_state.uploader_nonce}',
        on_change=_uploads_changed,
    )
    _render_load(uploads or [])
    records = st.session_state.records
    _render_overview(records)
    _render_review(records)
    _render_export(records)
    if records:
        st.button('Clear batch', on_click=_clear_batch, type='tertiary')


if __name__ == '__main__':
    main()
