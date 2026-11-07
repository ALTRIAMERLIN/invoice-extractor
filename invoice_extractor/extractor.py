from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from invoice_extractor.models import (
    FIELD_NAMES,
    MAX_TEXT_CHARS,
    MONEY_FIELDS,
    SUPPORTED_CURRENCIES,
    Candidate,
    DocumentText,
    InvoiceRecord,
    Issue,
)
from invoice_extractor.validator import parse_date, parse_money, validate

ISO = '|'.join(SUPPORTED_CURRENCIES)
ISO_RE = re.compile(rf'(?<![A-Za-z])({ISO})(?![A-Za-z])')
MONEY_SUFFIX = rf'(?:\s*\(\s*(?:{ISO})\s*\))?'
FIELD_LABELS = {
    'supplier': r'supplier|vendor|seller|from',
    'invoice_number': r'invoice\s*(?:number|num\.?|no\.?|#)',
    'invoice_date': r'invoice\s+date|date\s+of\s+issue|issue\s+date|date',
    'subtotal': rf'(?:sub[\s-]?total){MONEY_SUFFIX}',
    'tax': rf'(?:(?:total\s+|sales\s+)?(?:tax|vat|gst)(?:\s+amount)?(?:\s*@?\s*\(?\s*\d{{1,2}}(?:\.\d+)?\s*%\s*\)?)?)'
           rf'{MONEY_SUFFIX}',
    'total': rf'(?:grand\s+total|total\s+due|amount\s+due|invoice\s+total|total\s+amount|total)'
             rf'{MONEY_SUFFIX}',
    'currency': r'currency',
}
OTHER_LABELS = (r'bill\s*to|ship\s*to|sold\s*to|invoice\s*to|customer|client|buyer|due\s*date|'
                r'(?:payment\s+)?terms|po\s*(?:number|no\.?|#)|description|qty|quantity|unit\s+price|'
                r'amount|discount|shipping|balance|tax\s+rate|vat\s+rate')
ALL_LABELS = '|'.join([*FIELD_LABELS.values(), OTHER_LABELS])
LABEL_RES = {name: re.compile(rf'^(?:{pattern})(?P<sep>\s*:\s*|\s+|$|(?<=#))(?P<rest>.*)$', re.IGNORECASE)
             for name, pattern in FIELD_LABELS.items()}
LABEL_START_RE = re.compile(rf'^(?:{ALL_LABELS})(?:\s*:|\s*$)', re.IGNORECASE)
EMBEDDED_LABEL_RE = re.compile(rf'\s(?:{ALL_LABELS})\s*:', re.IGNORECASE)
SEGMENT_RE = re.compile(r'\S+(?: \S+)*')
INVOICE_NUMBER_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9\-/._]*')
MONEY_LIKE_RE = re.compile(rf'^(?:(?:{ISO})\s*)?[$€£]?\s*[-(]?\s*\d[\d,.]*\)?\s*(?:{ISO}|-|CR)?$', re.IGNORECASE)
NEGATIVE_RE = re.compile(r'^\s*(?:[A-Z]{3}\s*)?[$€£]?\s*[-(]|-\s*(?:[A-Z]{3})?\s*$|\bCR\s*$', re.IGNORECASE)
CREDIT_NOTE_RE = re.compile(r'\bcredit\s+(?:note|memo)\b', re.IGNORECASE)
ADJUSTMENT_RE = re.compile(r'^(?:discounts?|shipping(?:\s*(?:&|and)\s*handling)?|freight|delivery(?:\s+charges?)?|'
                           r'handling|adjustments?|surcharges?|deposit|amount\s+paid|rounding|credit)'
                           r'(?:\s*\([^)]*\))?(?:\s*:\s*|\s+|$)(?P<rest>.*)$', re.IGNORECASE)
ITEM_HEADER_RE = re.compile(r'\b(?:description|qty|quantity|unit\s+price|item)\b', re.IGNORECASE)
MONEY_ISO_RE = re.compile(rf'(?<![\w/-])({ISO})\s*[$€£]?\s*\d|\d[\d,.]*\s*({ISO})(?![\w-])|\(\s*({ISO})\s*\)')
CONTEXT_CHARS = 160
MAX_BLANK_GAP = 2
MAX_CANDIDATES = 50
LABELS = {
    'supplier': 'Supplier', 'invoice_number': 'Invoice number', 'invoice_date': 'Invoice date',
    'subtotal': 'Subtotal', 'tax': 'Tax', 'total': 'Total', 'currency': 'Currency',
}


@dataclass
class Segment:
    text: str
    start: int
    end: int


@dataclass
class Found:
    raw: str
    page: int
    rule_id: str
    context: str
    ambiguous: bool = False
    codes: list[str] = field(default_factory=list)


def _segments(line: str) -> list[Segment]:
    return [Segment(match.group(), match.start(), match.end()) for match in SEGMENT_RE.finditer(line)]


def _is_label(text: str) -> bool:
    return bool(LABEL_START_RE.match(text.strip()))


def _looks_like(name: str, text: str) -> bool:
    if name in MONEY_FIELDS:
        return bool(MONEY_LIKE_RE.match(text))
    if name == 'invoice_number':
        return bool(INVOICE_NUMBER_RE.fullmatch(text)) and any(char.isdigit() for char in text)
    if name == 'currency':
        return bool(re.fullmatch(r'[A-Za-z]{3}', text))
    if name == 'invoice_date':
        try:
            parse_date(text)
        except ValueError:
            return False
        return True
    return False


def _cut_embedded_label(text: str) -> str:
    match = EMBEDDED_LABEL_RE.search(text)
    return text[:match.start()].strip() if match else text.strip()


def _value_like(name: str, text: str) -> bool:
    if not text or _is_label(text):
        return False
    if name == 'supplier':
        return any(char.isalpha() for char in text)
    if name == 'invoice_date':
        return len(text) <= 40 and any(char.isdigit() for char in text) and bool(re.fullmatch(r'[\w ,./-]+', text))
    return _looks_like(name, text)


def _clean(name: str, text: str) -> str:
    text = ' '.join(text.split())
    if name == 'invoice_number':
        text = text.rstrip('.,;:')
    return text


def _context(*lines: str) -> str:
    return ' | '.join(' '.join(line.split()) for line in lines if line.strip())[:CONTEXT_CHARS]


def _next_line(lines: list[str], index: int) -> str | None:
    for later in range(index + 1, min(len(lines), index + 1 + MAX_BLANK_GAP + 1)):
        if lines[later].strip():
            return lines[later]
    return None


def _below(name: str, lines: list[str], index: int, label: Segment, column_end: float,
           page: int, rule_id: str) -> tuple[list[Found], bool]:
    line = _next_line(lines, index)
    if line is None:
        return [], False
    overlapping = [seg for seg in _segments(line) if seg.end > label.start - 2 and seg.start < column_end]
    if not overlapping:
        return [], False
    if any(_is_label(seg.text) for seg in overlapping):
        return [], name == 'supplier'
    usable = [seg for seg in overlapping if _value_like(name, seg.text)]
    if len(usable) != 1 or (name == 'supplier' and len(overlapping) != 1):
        return [], True
    value = usable[0]
    if value.end > column_end + 1:
        return [], True
    text = _clean(name, value.text)
    return [Found(text, page, f'{rule_id}.next_line', _context(lines[index], line))], False


def _scan_line(lines: list[str], index: int, page: int) -> tuple[list[tuple[str, Found]], set[str]]:
    found: list[tuple[str, Found]] = []
    unresolved: set[str] = set()
    line = lines[index]
    segments = _segments(line)
    item_header = bool(ITEM_HEADER_RE.search(line))
    for position, segment in enumerate(segments):
        if _adjustment_amount(segment, segments[position + 1:]):
            unresolved.add('adjustment')
        for name, label_re in LABEL_RES.items():
            match = label_re.match(segment.text)
            if not match:
                continue
            _scan_label(name, match, segment, segments[position + 1:], lines, index, page, found, unresolved,
                        item_header)
            break
    return found, unresolved


def _adjustment_amount(segment: Segment, following: list[Segment]) -> bool:
    match = ADJUSTMENT_RE.match(segment.text)
    if not match:
        return False
    rest = match.group('rest').strip()
    texts = [rest] if rest else [seg.text for seg in following[:2]]
    return any(MONEY_LIKE_RE.match(text) for text in texts)


def _same_line_text(name: str, following: list[Segment], has_colon: bool) -> str | None:
    texts = [following[0].text]
    if name in MONEY_FIELDS and len(following) > 1 and ISO_RE.fullmatch(following[0].text):
        texts.insert(0, f'{following[0].text} {following[1].text}')
    if name == 'supplier' and not has_colon:
        return None
    return next((text for text in texts if _value_like(name, text)), None)


def _scan_label(name, match, segment, following, lines, index, page, found, unresolved, item_header) -> None:
    line = lines[index]
    rule_id = _rule_id(name, segment.text[:match.start('sep')])
    rest = _cut_embedded_label(match.group('rest'))
    has_colon = ':' in match.group('sep')
    if rest:
        if _is_label(rest):
            unresolved.add(name)
            return
        if _ambiguous_tail(name, rest, [rest, *_unlabelled(following)]):
            unresolved.add(name)
        if (has_colon or name != 'supplier') and _value_like(name, rest):
            found.append((name, Found(_clean(name, rest), page, f'{rule_id}.same_line', _context(line))))
        return
    if following and not _is_label(following[0].text):
        text = _same_line_text(name, following, has_colon)
        if text is not None:
            if _ambiguous_tail(name, text, _unlabelled(following)):
                unresolved.add(name)
            found.append((name, Found(_clean(name, text), page, f'{rule_id}.same_line', _context(line))))
        return
    if item_header:
        return
    column_end = following[0].start if following else float('inf')
    below, ambiguous = _below(name, lines, index, segment, column_end, page, rule_id)
    found.extend((name, item) for item in below)
    if ambiguous:
        unresolved.add(name)


def _rule_id(name: str, label_text: str) -> str:
    if name == 'invoice_date' and re.fullmatch(r'date', label_text.strip(), re.IGNORECASE):
        return 'invoice_date.generic'
    return f'{name}.label'


def _unlabelled(segments: list[Segment]) -> list[str]:
    result = []
    for segment in segments:
        if _is_label(segment.text):
            break
        result.append(segment.text)
    return result


def _ambiguous_tail(name: str, selected: str, parts: list[str]) -> bool:
    if len(parts) < 2:
        return False
    if name in ('supplier', 'invoice_number'):
        return True
    if name in MONEY_FIELDS:
        try:
            return parse_money(' '.join(parts)) != parse_money(selected)
        except ValueError:
            return True
    return False


def _add(issues: list[Issue], code: str, message: str, field_name: str | None = None) -> None:
    issue = Issue(code=code, message=message, field=field_name)
    if issue not in issues:
        issues.append(issue)


def _canonical(name: str, raw: str) -> str:
    if name == 'invoice_date':
        return parse_date(raw)
    if name in MONEY_FIELDS:
        return parse_money(raw)
    if name == 'currency':
        return raw.strip().upper()
    return ' '.join(raw.split())


def _resolve(record: InvoiceRecord, name: str, items: list[Found], unresolved: bool,
             issues: list[Issue]) -> None:
    label = LABELS[name]
    record.fields[name].candidates = [Candidate(item.raw, item.page, item.rule_id, item.context)
                                      for item in items[:MAX_CANDIDATES]]
    if len(items) > MAX_CANDIDATES:
        _add(issues, 'candidate_limit', f'{label} has more candidates than were kept; review required', name)
    if unresolved:
        _add(issues, 'unresolved_layout', f'{label} position could not be resolved; review required', name)
    if name == 'invoice_date':
        explicit = [item for item in items if not item.rule_id.startswith('invoice_date.generic')]
        items = explicit or items
    values: set[str] = set()
    unparsed = False
    for item in items:
        try:
            values.add(_canonical(name, item.raw))
        except ValueError:
            unparsed = True
    if name in MONEY_FIELDS and any(NEGATIVE_RE.search(item.raw) for item in items):
        _add(issues, 'negative_amount', f'{label} appears negative; review required', name)
    if unparsed:
        _add(issues, 'unparsed_value', f'{label} has a value that could not be read safely', name)
    if len(values) > 1:
        if name == 'invoice_number':
            _add(issues, 'multi_invoice', 'document contains more than one invoice number')
        elif name == 'currency':
            _add(issues, 'currency_conflict', 'document contains differing currency codes', name)
        else:
            _add(issues, 'conflicting_values', f'{label} has differing values; review required', name)
    if name == 'currency' and any(value not in SUPPORTED_CURRENCIES for value in values):
        _add(issues, 'unsupported_currency', 'currency code is not supported', name)
    if unresolved or unparsed or len(values) != 1:
        return
    value = values.pop()
    if name == 'currency' and value not in SUPPORTED_CURRENCIES:
        return
    if len(value) > MAX_TEXT_CHARS:
        _add(issues, 'value_too_long', f'{label} is unusually long; review required', name)
    record.fields[name].extracted_value = value
    record.fields[name].current_value = value


def extract(document: DocumentText) -> InvoiceRecord:
    record = InvoiceRecord(
        record_id=str(uuid.uuid4()),
        filename=document.filename,
        file_sha256=document.file_sha256,
        page_count=document.page_count,
        processing_status=document.status,
        issues=list(document.issues),
    )
    if document.status != 'text_ready':
        validate(record)
        return record
    found: dict[str, list[Found]] = {name: [] for name in FIELD_NAMES}
    unresolved: set[str] = set()
    issues: list[Issue] = []
    for page, text in enumerate(document.pages, start=1):
        lines = text.splitlines()
        for index, line in enumerate(lines):
            items, open_names = _scan_line(lines, index, page)
            unresolved |= open_names
            for name, item in items:
                found[name].append(item)
            for match in MONEY_ISO_RE.finditer(line):
                code = next(group for group in match.groups() if group)
                found['currency'].append(Found(code, page, 'currency.money_adjacent', _context(line)))
            if CREDIT_NOTE_RE.search(line):
                _add(issues, 'credit_note', 'document appears to be a credit note; review required')
    if 'adjustment' in unresolved:
        _add(issues, 'adjustment_amount', 'document contains adjustment amounts; review required')
    for name in FIELD_NAMES:
        _resolve(record, name, found[name], name in unresolved, issues)
    record.issues.extend(issue for issue in issues if issue not in record.issues)
    validate(record)
    return record
