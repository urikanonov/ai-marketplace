"""Commentable-html validator support package.

The shipped `tools/validate.py` stays the entry point and keeps the layer/chart
checks; the new content-syntax checks live here as focused modules so the
validator does not grow into one giant script:

  - mermaid   : mermaid diagram syntax checks (zero false positives)
  - jsonblocks: embedded application/json script-block validity

Pure standard library, no third-party packages. Deeper, library-accurate
validation (real mermaid + Chart.js parsing) is a repo-side dev/CI tool
(dev/tools/validate_render.mjs), never shipped to consumers.
"""
