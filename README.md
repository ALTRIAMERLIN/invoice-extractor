# Invoice Extractor

**Personal demo project. All invoices are fictional. Not a client project.**

中文启动说明: [docs/QUICKSTART.zh-CN.md](docs/QUICKSTART.zh-CN.md)

A local PDF invoice workbench: extract fields, inspect the source evidence, resolve exceptions, and export consistent Excel and CSV files.

Built for small batches of English invoices with a text layer. Processing happens on your computer; no external AI service or API key is required.

## What it does

- Upload a batch of PDFs or load the three fictional demo invoices.
- Extract supplier, invoice number, date, subtotal, tax, total and currency using explicit English labels.
- Inspect candidate text and page numbers. Ambiguous or missing values remain visible for review.
- Edit records, explain manual overrides, flag duplicates and choose which records to export.
- Download an Excel workbook and CSV reports from the same final data snapshot.
- Continue a batch when a file is damaged, encrypted, scanned or over a per-file limit.

## Quick start (Windows, Python 3.11)

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

Open the local address shown in the terminal. The app binds to `127.0.0.1`; usage statistics are disabled in `.streamlit/config.toml`. You can stop it with Ctrl+C.

## Review and export

1. Add text-based PDF invoices and start processing, or load the public demos.
2. Review the batch table. Open a record to see issues and the source evidence for each field.
3. Save corrections. Changing a confirmed record removes its old confirmation. Original extraction values remain available.
4. Confirm each edited record. Explain the correction when the source originally had issues, or when an exception remains; invalid values cannot be confirmed.
5. Choose the export scope, confirm the selected batch and download the files.

Automatic checks are rules, not a guarantee of accuracy. Check the results against the source before using them for payment or accounting.

## Supported inputs and limits

The initial version supports English label-based PDFs, one invoice per file (including invoices spanning multiple pages), and explicit `USD`, `EUR`, `GBP`, `HKD`, or `CNY` currency codes. A bare `$` does not determine a currency. Scans, handwritten documents and unfamiliar layouts need manual handling; there is no OCR or universal template recognition.

Default limits: 50 PDFs and 100 MiB per batch, 10 MiB and 20 pages per file, 30 seconds of parsing per file. Money must be finite, nonnegative, at most two decimal places and no more than `999,999,999.99`. Ambiguous dates and amount formats are not guessed. Line items, credit notes, exchange rates and accounting integrations are outside this version.

## Privacy and exports

Uploaded PDF bytes, review state and generated exports stay in the application's current in-memory session. The app does not deliberately save or restore invoice batches. Refreshing, disconnecting or restarting may lose work. Operating-system paging or caching is outside this application-level promise.

The app makes no external model calls. Avoid exposing the local server to a network without separately designing authentication and deployment controls. Use only fictional samples in screenshots, bug reports and the public repository.

Excel contains `Invoices`, `Evidence` and `Batch` sheets. Separate CSV downloads provide the main table, evidence and batch report. IDs retain leading zeros; text exports guard against spreadsheet formula interpretation. Numeric money is exported with two decimal places. CSV text protection may add a leading apostrophe to potentially executable text.

## Development

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
```

`scripts/generate_samples.py` regenerates public fictional PDFs and their expected data. Production modules are in `invoice_extractor/`; UI is in `app.py`. Validation notes and supported limits are in `docs/`.

Validation evidence and remaining limits are recorded in `docs/VALIDATION.md`. Windows/Python 3.11 is the verification target; other platforms require their own checks.

## Demo video

`video/out/invoice-extractor-demo.mp4`: 67 seconds, 1920×1080, 60 fps, H.264, AAC. The audio is the template's interface sound effects only. There is no narration and no music.

The picture is a real local run of this app. It was recorded in the browser and assembled with the [MotionGit](https://motiongit.com/adunext/template-03-native) template `adunext/template-03-native` version `2.7.18-alpha.8`. The final video and contact sheet are included; the personal template and production inputs are not distributed.

Checked before publishing:

- FFmpeg decoded the whole file with no errors.
- Browser playback reached 67.0 seconds and dropped 0 frames.
- `video/verify_downloads.py` matched the downloaded Excel and CSV to the expected business fields. Invoice numbers stayed text, including leading zeros.

One limit was left in: from about 47.8 to 50.0 seconds the export scene opens on an empty dark frame while the download caption is already visible. The page content appears at about 50.2 seconds. `video/README.md` records the file hash, the checks and this limit.

## Project layout

Upwork-ready title, description, cover and screenshots: [deliverables/UPWORK.md](deliverables/UPWORK.md).
The delivery checks and review boundaries are in [docs/DELIVERY.md](docs/DELIVERY.md).

```
app.py                      Streamlit page
invoice_extractor/          PDF reading, extraction, review and export
samples/                    three fictional demo invoices
scripts/generate_samples.py regenerates those invoices and their expected data
tests/                      pytest
docs/                       spec, validation, screenshots, Chinese quick start
deliverables/               Upwork copy, cover, real screenshots, sample exports
run.ps1, run.cmd            start the local page after the virtual environment exists
video/out/                  final demo video
video/                      demo media and provenance notes
```

## License

MIT. The included demo invoices are fictional and may be shared under the same license.
