from pathlib import Path

from streamlit.testing.v1 import AppTest

from invoice_extractor.pipeline import process_batch

ROOT = Path(__file__).resolve().parents[1]


def button(app, label):
    return next(item for item in app.button if item.label == label)


def downloads(app):
    return app.get('download_button')


def test_demo_edit_reason_and_export_state_are_consistent():
    app = AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
    assert not app.exception
    assert app.session_state['records'] == []
    button(app,'Load 3 built-in demo invoice(s)').click().run()
    assert not app.exception
    records = app.session_state['records']
    assert len(records) == 3 and all(r.review_status == 'auto_checked' for r in records)
    original = records[0].fields['supplier'].extracted_value
    button(app,'Confirm batch for export').click().run()
    assert len(downloads(app)) == 4
    app.text_input[0].input('Edited Demo Supplier').run()
    assert len(downloads(app)) == 0
    assert button(app,'Confirm batch for export').disabled
    button(app,'Save changes').click().run()
    assert not app.exception
    first = app.session_state['records'][0]
    assert first.fields['supplier'].current_value == 'Edited Demo Supplier'
    assert first.fields['supplier'].extracted_value == original
    assert app.session_state['confirmation'] is None
    button(app,'Confirm batch for export').click().run()
    assert len(downloads(app)) == 4
    app.text_area[0].input('Reviewed against the original invoice.').run()
    assert len(downloads(app)) == 0
    assert button(app,'Confirm batch for export').disabled
    button(app,'Confirm record').click().run()
    first = app.session_state['records'][0]
    assert first.review_status == 'user_confirmed'
    assert first.review_reason == 'Reviewed against the original invoice.'
    history_size = len(first.edit_history)
    button(app,'Save changes').click().run()
    assert first.review_status == 'user_confirmed' and len(first.edit_history) == history_size
    second_id = app.session_state['records'][1].record_id
    app.selectbox[0].select(second_id).run()
    app.selectbox[0].select(first.record_id).run()
    assert app.text_area[0].value == first.review_reason
    button(app,'Confirm batch for export').click().run()
    assert len(downloads(app)) == 4
    button(app,'Clear batch').click().run()
    assert not app.exception
    assert app.session_state['records'] == [] and app.session_state['reason_drafts'] == {}
    assert len(downloads(app)) == 0


def test_manually_completed_failed_source_requires_explicit_confirmation():
    app = AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
    files = [('failed.pdf',b'%PDF-1.4 broken'),('good.pdf',(ROOT/'samples'/'invoice-layout-1-USD.pdf').read_bytes())]
    app.session_state['records'] = process_batch(files)
    app.run()
    assert not app.exception
    assert app.session_state['records'][0].processing_status == 'invalid_pdf'
    values = ['Manual Demo Supplier','000099','2026-11-06','100.00','10.00','110.00','USD']
    for index,value in enumerate(values):
        app.text_input[index].input(value).run()
    button(app,'Save changes').click().run()
    assert not app.exception
    item = app.session_state['records'][0]
    assert item.processing_status == 'invalid_pdf' and item.review_status == 'needs_review'
    button(app,'Confirm record').click().run()
    assert item.review_status == 'needs_review'
    app.text_area[0].input('Entered manually from a separately checked source.').run()
    button(app,'Confirm record').click().run()
    assert item.processing_status == 'invalid_pdf' and item.review_status == 'user_confirmed'
    button(app,'Confirm batch for export').click().run()
    assert len(downloads(app)) == 4


def test_same_filename_records_keep_independent_identity():
    app = AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
    data = (ROOT/'samples'/'invoice-layout-1-USD.pdf').read_bytes()
    app.session_state['records'] = process_batch([('same.pdf',data),('same.pdf',data)])
    app.run()
    assert not app.exception
    records = app.session_state['records']
    assert len({r.record_id for r in records}) == 2
    app.text_input[0].input('Only the first record changed').run()
    button(app,'Save changes').click().run()
    assert records[0].fields['supplier'].current_value == 'Only the first record changed'
    assert records[1].fields['supplier'].current_value == 'Northstar Demo Studio'


def test_edit_clears_old_reason_and_new_batch_resets_uploader():
    app = AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
    nonce = app.session_state['uploader_nonce']
    button(app,'Load 3 built-in demo invoice(s)').click().run()
    assert app.session_state['uploader_nonce'] > nonce
    app.text_area[0].input('Reason for earlier values').run()
    button(app,'Confirm record').click().run()
    app.text_input[0].input('New supplier values').run()
    button(app,'Save changes').click().run()
    assert not app.exception
    assert app.text_area[0].value == ''
    assert app.session_state['records'][0].review_reason == ''


def test_pending_upload_cannot_export_a_previously_confirmed_batch():
    app = AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
    button(app,'Load 3 built-in demo invoice(s)').click().run()
    button(app,'Confirm batch for export').click().run()
    assert len(downloads(app)) == 4
    original_ids = [record.record_id for record in app.session_state['records']]
    app.session_state['uploads_dirty'] = True
    app.run()
    assert len(downloads(app)) == 0
    assert button(app,'Confirm batch for export').disabled
    button(app,'Keep current batch instead').click().run()
    assert [record.record_id for record in app.session_state['records']] == original_ids
    assert not app.session_state['uploads_dirty']
    assert len(downloads(app)) == 0
    button(app,'Confirm batch for export').click().run()
    assert len(downloads(app)) == 4
def test_untrusted_supplier_markdown_never_reaches_tooltip():
    records = process_batch([('demo.pdf', b'%PDF-1.4 x')])
    records[0].fields['supplier'].extracted_value = '![x](https://example.invalid/x)'
    records[0].fields['supplier'].current_value = '![x](https://example.invalid/x)'
    app = AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
    app.session_state['records'] = records
    app.run()
    assert not app.exception
    field = app.text_input[0]
    assert 'example.invalid' not in (field.help or '')
    assert all('example.invalid' not in md.value for md in app.markdown)
