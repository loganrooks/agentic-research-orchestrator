# Runner Guide: Claude Desktop (Research mode) (v1)

## Expected output shape
Typically: one markdown research report with citations.

## Why we don’t assume multi-file output
Some UIs constrain output to a single response. Over-assuming leads to missing artifacts and a broken synthesis pipeline.

## What to request
- Report-first output.
- If possible, include JSON registers in fenced code blocks.
- If not possible, include tables with stable IDs.
- Always include a “Residuals / Open Questions” section.

