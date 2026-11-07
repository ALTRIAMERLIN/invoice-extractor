# Validation notes

Verified on Windows with Python 3.11.9, 2026-11-07.

- Application suite: 173 automated tests, covering PDF reading in real spawned processes,
  extraction, validation, duplicate handling, review, safe export and Streamlit workflows.
- Fifteen fictional PDFs cover three layouts and five explicit currencies. The seven fields
  and source pages match their expected data. Label/date/amount variations are also checked.
- Process tests cover malformed, encrypted and textless PDFs, size/page/time limits, worker
  termination, child crashes and a large IPC result without pipe deadlock.
- Review/export checks cover original values and warnings, confirmation invalidation,
  duplicate membership, failed-source manual entry, formula-like text, leading zeros,
  monetary bounds and selected-record consistency.
- Real browser downloads were independently opened. The four demonstrated invoice IDs
  `00011`, `00022`, `00034` and `00045` are Excel text cells, and XLSX/CSV business fields
  match the reviewed fictional data. Copies are in `deliverables/sample-exports/`.
- A separate environment installed with only `requirements.txt` ran the application. Production
  code does not need the development-only PDF generator.
- Ruff static checks passed. Run the commands in the README to repeat the application tests.

These checks establish behavior on the stated fixtures, not an accuracy percentage on arbitrary
supplier PDFs. This version has no OCR, line-item extraction, credit-note support or accounting
integration. Text limits are enforced after extraction in a time-bounded process; there is no
claim of a hard operating-system memory limit for hostile PDFs. Other operating systems require
their own checks.

The demo's decode, provenance and remaining visual limitation are recorded in `video/README.md`.
