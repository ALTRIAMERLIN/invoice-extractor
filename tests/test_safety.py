"""Independent adversarial checks for value validation and exports."""
import csv
import io
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from invoice_extractor.exporter import build_exports
from invoice_extractor.models import Candidate, FieldValue, InvoiceRecord
from invoice_extractor.review import apply_edits, confirm_record, reset_record
from invoice_extractor.validator import parse_date, parse_money, validate


def record():
    values = {'supplier':'Demo Supplier','invoice_number':'000123','invoice_date':'2026-11-06',
              'subtotal':'100.00','tax':'10.00','total':'110.00','currency':'USD'}
    item = InvoiceRecord(record_id='test-record',filename='demo.pdf',file_sha256='abc',page_count=1,
                         fields={name:FieldValue(extracted_value=value,current_value=value)
                                 for name,value in values.items()})
    validate(item)
    return item


@pytest.mark.parametrize('bad',['NaN','Infinity','1e3','-1.00','(1.00)','0.001','999999999.999','1000000000.00','1/2','--1'])
def test_money_invalid_values_never_become_valid(bad):
    with pytest.raises(ValueError):
        parse_money(bad)


@pytest.mark.parametrize('raw,expected',[('0','0.00'),('0.1','0.10'),('1234.50','1234.50'),('999999999.99','999999999.99')])
def test_money_normalization_and_upper_boundary(raw,expected):
    assert parse_money(raw) == expected


@pytest.mark.parametrize('bad',['03/04/2026','2026-02-30','2026-13-01','not a date'])
def test_ambiguous_or_invalid_dates(bad):
    with pytest.raises(ValueError):
        parse_date(bad)


def test_atomic_edits_noop_and_restore():
    item = record()
    validate(item)
    confirm_record(item)
    before = item.fields['supplier'].current_value
    with pytest.raises(ValueError):
        apply_edits(item,{'supplier':'Changed','total':'NaN'})
    assert item.fields['supplier'].current_value == before
    assert item.review_status == 'user_confirmed'
    apply_edits(item,{'total':'110.00'})
    assert item.review_status == 'user_confirmed'
    apply_edits(item,{'supplier':'Changed'})
    assert item.review_status != 'user_confirmed'
    assert item.fields['supplier'].extracted_value == before
    reset_record(item)
    assert item.fields['supplier'].current_value == before
    assert item.edit_history


def test_missing_values_need_override_reason():
    item = record()
    apply_edits(item,{'tax':''})
    with pytest.raises(ValueError):
        confirm_record(item)
    confirm_record(item,'Tax omitted on source; recorded for review only.')
    assert item.review_status == 'user_confirmed'
    assert item.fields['tax'].current_value is None


def test_every_export_text_path_protects_formula_and_controls():
    item = record()
    item.filename = '\t=HYPERLINK("https://example.invalid")\x01.pdf'
    apply_edits(item,{'supplier':'=1+2','invoice_number':'000123'})
    item.fields['supplier'].candidates.append(Candidate(raw_text='\r@SUM(1,2)\x02',page_number=1,rule_id='test',context='\t+1+2'))
    confirm_record(item,'Synthetic hostile text validation')
    exports = build_exports([item])
    for name in ('invoices_csv','evidence_csv','batch_csv'):
        content = exports[name].decode('utf-8-sig')
        for row in csv.reader(io.StringIO(content)):
            for cell in row:
                assert not cell.lstrip(' \t\r\n\x00\x01\x02').startswith(('=','+','-','@')),(name,cell)
    workbook = load_workbook(io.BytesIO(exports['xlsx']),data_only=False)
    assert set(workbook.sheetnames) == {'Invoices','Evidence','Batch'}
    for sheet in workbook:
        for row in sheet:
            for cell in row:
                assert cell.data_type != 'f'
                if isinstance(cell.value,str):
                    assert '\x01' not in cell.value and '\x02' not in cell.value
    headers = [cell.value for cell in workbook['Invoices'][1]]
    identifier = workbook['Invoices'].cell(2,headers.index('invoice_number')+1)
    assert identifier.value == '000123' and identifier.data_type == 's'


@pytest.mark.parametrize('amount',['0.01','0.10','123456789.12','999999999.99'])
def test_excel_numeric_precision_boundaries(amount):
    item = record()
    apply_edits(item,{'subtotal':amount,'tax':'0.00','total':amount})
    validate(item)
    confirm_record(item)
    workbook = load_workbook(io.BytesIO(build_exports([item])['xlsx']))
    sheet = workbook['Invoices']
    headers = [cell.value for cell in sheet[1]]
    value = sheet.cell(2,headers.index('total')+1).value
    assert isinstance(value,(int,float))
    assert Decimal(str(value)).quantize(Decimal('.01')) == Decimal(amount)
