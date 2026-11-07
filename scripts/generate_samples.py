"""Generate fictional invoice fixtures with independently specified expected values."""
import json
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
CURRENCIES = ('USD', 'EUR', 'GBP', 'HKD', 'CNY')
VENDORS = ('Northstar Demo Studio', 'Cedar Example Services', 'Harbor Sample Supply')
INK = colors.HexColor('#16343b')
MUTED = colors.HexColor('#61747b')
ACCENT = colors.HexColor('#007f73')


def draw_invoice(path, layout, currency, index):
    subtotal = Decimal(1000 + layout * 25 + index * 10)
    tax = subtotal * Decimal('.10')
    expected = {
        'supplier': VENDORS[layout-1],
        'invoice_number': f'000{layout}{index+1}',
        'invoice_date': '2026-11-06',
        'subtotal': f'{subtotal:.2f}',
        'tax': f'{tax:.2f}',
        'total': f'{subtotal+tax:.2f}',
        'currency': currency,
    }
    c = canvas.Canvas(str(path), pagesize=(595, 842))
    c.setTitle(f'Fictional demo invoice {expected["invoice_number"]}')
    c.setAuthor('Invoice Extractor - fictional demo')

    def line(x, y, text, size=11, bold=False, color=INK):
        c.setFillColor(color)
        c.setFont('Helvetica-Bold' if bold else 'Helvetica', size)
        c.drawString(x, y, text)

    def header(page=1):
        c.setFillColor(ACCENT)
        c.rect(0, 826, 595, 16, fill=1, stroke=0)
        line(44, 778, 'INVOICE', 29, True)
        line(44, 756, 'FICTIONAL DEMO  /  NOT VALID FOR PAYMENT', 8, color=MUTED)
        line(44, 39, f'Public synthetic sample  |  Layout {layout}  |  Page {page}', 8, color=MUTED)

    header()
    supplier_label = ('Supplier', 'Vendor', 'From')[layout-1]
    if layout == 2:
        line(44, 700, supplier_label, 9, True, MUTED)
        line(44, 680, expected['supplier'], 13, True)
    else:
        line(44, 700, f"{supplier_label}: {expected['supplier']}", 12, True)
    line(44, 654, '12 Example Lane, Sample City', 10, color=MUTED)
    line(350, 700, 'Bill To: Example Customer Ltd', 10)
    line(350, 679, '48 Fictional Road', 10, color=MUTED)
    c.setStrokeColor(colors.HexColor('#d9e5e6'))
    c.line(44, 625, 550, 625)
    if layout == 2:
        line(44, 596, 'Invoice #', 9, True, MUTED)
        line(44, 575, expected['invoice_number'], 12)
        line(270, 596, 'Invoice Date', 9, True, MUTED)
        line(270, 575, '6 Nov 2026', 12)
    else:
        label = 'Invoice Number' if layout == 1 else 'Invoice No.'
        line(44, 590, f"{label}: {expected['invoice_number']}")
        line(330, 590, 'Invoice Date: 2026-11-06')
    c.setFillColor(colors.HexColor('#eef6f5'))
    c.rect(44, 512, 506, 30, fill=1, stroke=0)
    line(55, 523, 'DESCRIPTION', 9, True)
    line(412, 523, 'AMOUNT', 9, True)
    line(55, 482, 'Demo workflow setup and documentation', 10)
    line(412, 482, f'{subtotal:.2f}', 10)
    if layout == 3:
        line(44, 135, 'This invoice continues on the following page.', 10, color=MUTED)
        c.showPage()
        header(2)
        line(44, 700, 'AMOUNT SUMMARY', 17, True)
        y = 590
    else:
        y = 350
    subtotal_label = 'Sub-total' if layout == 3 else 'Subtotal'
    tax_label = 'VAT' if layout == 3 else 'Tax'
    total_label = ('Total', 'Grand Total', 'Amount Due')[layout-1]
    line(330, y, f"{subtotal_label}: {expected['subtotal']}")
    line(330, y-28, f"{tax_label}: {expected['tax']}")
    c.setStrokeColor(ACCENT)
    c.line(320, y-44, 550, y-44)
    line(330, y-72, f"{total_label}: {expected['total']}", 13, True)
    line(330, y-100, f'Currency: {currency}', 11)
    line(44, 105, 'Thank you. All names, addresses and amounts are fictional.', 9, color=MUTED)
    c.save()
    pages = {field:1 for field in expected}
    if layout == 3:
        pages.update({field:2 for field in ('subtotal','tax','total','currency')})
    return {'file':path.name,'expected':expected,'pages':pages}


def main():
    fixtures = ROOT/'tests'/'fixtures'
    demo = ROOT/'samples'
    fixtures.mkdir(parents=True, exist_ok=True)
    demo.mkdir(exist_ok=True)
    manifest, demo_manifest = [], []
    for layout in (1,2,3):
        for index,currency in enumerate(CURRENCIES):
            filename = f'invoice-layout-{layout}-{currency}.pdf'
            entry = draw_invoice(fixtures/filename,layout,currency,index)
            manifest.append(entry)
            if (layout,currency) in ((1,'USD'),(2,'EUR'),(3,'HKD')):
                (demo/filename).write_bytes((fixtures/filename).read_bytes())
                demo_manifest.append(entry)
    (fixtures/'expected.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (demo/'expected.json').write_text(json.dumps(demo_manifest,indent=2),encoding='utf-8')
    print(f'Generated {len(manifest)} fixtures and {len(demo_manifest)} public demos.')


if __name__ == '__main__':
    main()
