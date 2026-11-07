"""Coordinator-owned acceptance tests. Expected fields do not come from the parser."""
import csv
import io
import json
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook
from reportlab.pdfgen import canvas

from invoice_extractor.exporter import build_exports
from invoice_extractor.models import Limits
from invoice_extractor.pipeline import process_batch

ROOT = Path(__file__).resolve().parent


def test_fifteen_supported_invoice_layouts_and_evidence():
    manifest = json.loads((ROOT/'fixtures'/'expected.json').read_text())
    files = [(entry['file'],(ROOT/'fixtures'/entry['file']).read_bytes()) for entry in manifest]
    records = process_batch(files)
    assert len(records) == 15
    for record,entry in zip(records,manifest):
        assert record.processing_status == 'text_ready', (entry['file'],record.issues)
        assert record.review_status == 'auto_checked', (entry['file'],record.issues)
        for field,value in entry['expected'].items():
            assert record.fields[field].current_value == value,(entry['file'],field)
            pages = [candidate.page_number for candidate in record.fields[field].candidates]
            assert pages and all(page == entry['pages'][field] for page in pages), (entry['file'], field)


def test_predeclared_label_and_amount_variation_roundtrip():
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer)
    lines = ['Vendor: Juniper Independent Demo', 'Invoice No: 000099',
             'Invoice Date: 14 December 2026', 'Subtotal: 2,345.60',
             'GST: 234.56', 'Grand Total: 2,580.16', 'Currency: GBP']
    for i,line in enumerate(lines):
        c.drawString(50,750-i*27,line)
    c.save()
    records = process_batch([('variation.pdf',buffer.getvalue())])
    record = records[0]
    expected = {'supplier':'Juniper Independent Demo','invoice_number':'000099','invoice_date':'2026-12-14','subtotal':'2345.60','tax':'234.56','total':'2580.16','currency':'GBP'}
    assert record.review_status == 'auto_checked',record.issues
    assert {name:item.current_value for name,item in record.fields.items()} == expected
    exports = build_exports(records)
    rows = list(csv.DictReader(io.StringIO(exports['invoices_csv'].decode('utf-8-sig'))))
    assert rows[0]['invoice_number'] == '000099'
    assert rows[0]['invoice_date'] == '2026-12-14'
    workbook = load_workbook(io.BytesIO(exports['xlsx']),data_only=False)
    sheet = workbook['Invoices']
    headers = [cell.value for cell in sheet[1]]
    row = {name:sheet.cell(2,index+1).value for index,name in enumerate(headers)}
    for field in ('subtotal','tax','total'):
        assert Decimal(str(row[field])).quantize(Decimal('.01')) == Decimal(expected[field])


def test_batch_limit_is_checked_before_any_parse(monkeypatch):
    from invoice_extractor import pipeline
    invoked = []
    monkeypatch.setattr(pipeline,'read_pdf',lambda *args,**kwargs: invoked.append(True))
    import pytest
    with pytest.raises(ValueError):
        process_batch([('1.pdf',b'x'),('2.pdf',b'y')],Limits(max_files=1))
    with pytest.raises(ValueError):
        process_batch([('1.pdf',b'xx')],Limits(max_batch_bytes=1))
    assert invoked == []
