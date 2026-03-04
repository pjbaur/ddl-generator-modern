#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__ = 'Catherine Devlin'
__email__ = 'catherine.devlin@gmail.com'
__version__ = '0.1.9'

# Monkey-patch data_dispenser's _open to fix removed 'rU' file mode (Python 3.12+)
# data_dispenser 0.2.5.1 is the latest release and is unmaintained.
try:
    import data_dispenser.sources as _ds_sources
    if hasattr(_ds_sources, '_open'):
        _ds_original_open = _ds_sources._open
        def _patched_open(filename):
            if filename.lower().endswith('.pickle'):
                return open(filename, 'rb')
            return open(filename, 'r')
        _ds_sources._open = _patched_open
except ImportError:
    pass

from .console import generate  # noqa: F401 - re-exported for public API