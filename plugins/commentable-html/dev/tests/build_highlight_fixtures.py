#!/usr/bin/env python3
"""Generate the pre-annotated highlighter golden fixtures.

For every language in `highlight_samples.SAMPLES` this writes two checked-in files under
`fixtures/highlight/`:

  fixtures/highlight/<lang>.sample   - the raw source sample (input to the highlighter)
  fixtures/highlight/<lang>.html     - the pre-annotated highlighted output (the golden to diff against)

`test_highlight_golden.py` re-runs `highlight_code.highlight_code` on each `.sample` and asserts
the result equals the committed `.html`, so any change in highlighter behaviour shows up as a
fixture diff that a human reviews. Regenerate after intentional changes:

    python plugins/commentable-html/dev/tests/build_highlight_fixtures.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import highlight_code as H  # noqa: E402
from highlight_samples import SAMPLES  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures", "highlight")


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def build():
    os.makedirs(FIXTURES, exist_ok=True)
    missing = sorted(set(H.LANGUAGE_CONFIGS) - set(SAMPLES))
    if missing:
        raise SystemExit("no sample for language(s): %s" % ", ".join(missing))
    for language in sorted(SAMPLES):
        sample = SAMPLES[language].replace("\r\n", "\n").replace("\r", "\n")
        _write(os.path.join(FIXTURES, language + ".sample"), sample)
        _write(os.path.join(FIXTURES, language + ".html"), H.highlight_code(language, sample))
    return sorted(SAMPLES)


if __name__ == "__main__":
    built = build()
    sys.stdout.write("wrote %d fixture pair(s) to %s\n" % (len(built), FIXTURES))
