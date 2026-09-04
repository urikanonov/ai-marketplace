"""Environment isolation helpers for tests."""
import contextlib
import os


@contextlib.contextmanager
def patch(values=None, clear=False):
    original = os.environ
    replacement = {} if clear else dict(original)
    replacement.update(values or {})
    os.environ = replacement
    try:
        yield replacement
    finally:
        os.environ = original
