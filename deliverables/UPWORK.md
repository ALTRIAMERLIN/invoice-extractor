# Upwork portfolio text

Paste these fields into the portfolio form. This follows the earlier CSV Cleaning Tool and
Safe File Organizer deliverables: an honest personal-demo disclosure, a real screenshot cover,
the demo video, screenshots and a concise description. Do not add client results, accuracy
percentages or time savings that were not measured.

## Project title

PDF Invoice Extractor: Review, Validate and Export to Excel

Characters: 59 (limit: 70).

## Project description

Personal demo with fictional invoices, not client work. Built a local Python app that turns batches of English text-based PDF invoices into Excel and CSV reports. It extracts seven fields, keeps source-page evidence, flags missing or conflicting values, and lets users correct and confirm exceptions before export. The demo processes four PDFs across three layouts and preserves invoice IDs such as 00045 as text. No external AI service or API key is required. Includes automated tests and a real browser demo. OCR, line items and accounting integrations are outside this version.

Characters: 580, including spaces (limit: 600).

## Your role

Python developer (personal project)

Characters: 35 (limit: 100).

## Skills and deliverables

Suggested five tags: Python · Data Extraction · PDF Conversion · Microsoft Excel · Automation.
Select the matching labels offered by the form; the live tag catalog has not been checked.

## Content, in this order

| # | File | Caption / purpose |
| --- | --- | --- |
| 1 | `deliverables/cover.png` | Cover, 2000×1500 (4:3), matching the prior two portfolio covers. The app panel is a crop of the real four-invoice batch. |
| 2 | `video/out/invoice-extractor-demo.mp4` | Real browser demonstration: 67 s, 1920×1080, 60 fps, 11,282,989 bytes. English captions; template interface sound effects; no narration or music. |
| 3 | `deliverables/screenshot-1-batch.png` | Four fictional PDFs: three auto-checked records and one exception requiring review. |
| 4 | `deliverables/screenshot-2-review-reason.png` | A correction is explained before the record is explicitly confirmed. |
| 5 | `deliverables/screenshot-3-export.png` | Batch confirmation and Excel, invoice CSV, evidence CSV and batch-report CSV downloads. |

The screenshots are original 1920×1080 frames from capture 5, decoded to PNG without UI edits.
`media-manifest.json` records the source frame, time and file hashes. The cover crops and scales
the batch screenshot and adds titles and factual demo counts; it does not redraw the UI.

## Video caption

Four fictional PDF invoices are processed in a local Python application. One missing invoice date
is checked against the source, corrected, explained and confirmed. The reviewed batch is exported
to Excel and CSV, preserving invoice IDs such as 00045 as text. Actual app footage is presented
inside MotionGit frames and transitions; the ending table summarizes verified exported data.
This is an edited showcase, not one continuous screen recording. Text-based PDFs only; no OCR.

## Posting notes

- Leave Related Upwork job empty: this is a personal demonstration, not a client contract.
- Use the cover as the thumbnail; preview image order and cropping before publishing.
- The MP4 is ready as a local file. Its acceptance by the current Upwork upload form has not been
  tested. If the form requires a hosted video, upload it to your chosen video host and add that URL.
  No hosted video URL has been created.
- Add the public source link: [github.com/ALTRIAMERLIN/invoice-extractor](https://github.com/ALTRIAMERLIN/invoice-extractor). The repository includes the application, fictional samples, tests and the demo video.
- `sample-exports/invoices.xlsx` and `invoices.csv` are the actual fictional browser downloads,
  included for inspection. They are not required Upwork media uploads.
- Use the repository link for source code; the cover, screenshots and demo are the portfolio media.
- No Upwork item has been published by this preparation.

Current field limits and image dimensions were checked on 2026-11-07 against the
[Upwork Help Center](https://support.upwork.com/hc/en-us/articles/360016144974-How-to-enhance-your-freelancer-profile):
70 characters for title, 100 for role, 600 for description, five skill tags; recommended image
dimensions 1000×750, minimum 400×300 and maximum 4000×4000.
