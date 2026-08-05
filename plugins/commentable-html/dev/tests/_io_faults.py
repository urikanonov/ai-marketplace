#!/usr/bin/env python3
"""Fault-injecting file objects shared by the write-safety tests.

One definition, so the disk-full contract the atomic-write regressions rely on cannot drift
between the modules that simulate it.
"""


class HalfWriter(object):
    """A file object that writes half of what it is given and then fails, like a full disk."""

    def __init__(self, fh):
        self._fh = fh

    def write(self, text):
        self._fh.write(text[:len(text) // 2])
        raise IOError("simulated disk-full")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._fh.close()
        return False

    def __getattr__(self, name):
        return getattr(self._fh, name)


def half_writing_opener(real_open):
    """Wrap `real_open` so every WRITE it hands back fails halfway.

    Sabotaging by mode rather than by path matters: a truncating implementation writes the target
    itself while an atomic one writes a staged temp file by DESCRIPTOR, so a path-based condition
    would silently stop testing the moment the write became atomic.
    """
    def opener(path, mode="r", *args, **kwargs):
        fh = real_open(path, mode, *args, **kwargs)
        return HalfWriter(fh) if "w" in mode else fh
    return opener
