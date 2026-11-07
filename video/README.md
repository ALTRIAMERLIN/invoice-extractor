# Invoice Extractor demo

`out/invoice-extractor-demo.mp4` demonstrates the real local application using fictional data.

| Property | Value |
| --- | --- |
| Duration | 67.000 s |
| Video | H.264, 1920×1080, 60 fps, yuv420p |
| Audio | AAC stereo; template interface sound effects only, no narration or music |
| File size | 11,282,989 bytes |
| SHA-256 | `69b38e42b3c0775cde05aca2beb3d4f57cd60512d6d6d8991b6a00da6a7fb7bc` |

The workflow is upload → batch review → source-date correction → explicit confirmation →
Excel/CSV export. All suppliers, dates and amounts are fictional. The footage was recorded in
the browser from the local application. MotionGit
[`adunext/template-03-native`](https://motiongit.com/adunext/template-03-native), version
`2.7.18-alpha.8`, supplies frames and transitions. This is an edited showcase, not a continuous
screen recording. The ending table summarizes verified exported data.

Full FFmpeg decode passed. Prior browser playback reached the end with zero dropped frames;
the final encoded export, table and ending sequences were checked again by sampled frames.
The actual XLSX/CSV downloads match the demonstrated business fields, and invoice numbers
retain their leading zeros. Audio was decoded but not listened to.

Known visual limit: around 47.8–50.0 s, the export scene enters through an empty/loading browser
frame while the download caption is visible; page content appears around 50.2 s. The 67-second
master retains that transition. Application capabilities are limited to English, text-based,
label-driven invoices; there is no OCR or measured arbitrary-template accuracy claim.

`out/invoice-extractor-demo-contact-sheet.jpg` contains timestamped frames from the final MP4.
The personal template and production inputs are not distributed. The application and its tests
run independently of those media-production resources.
