#!/usr/bin/env python
# -*- coding: utf-8 -*-

from importlib.metadata import version, PackageNotFoundError

__author__ = 'Catherine Devlin'
__email__ = 'catherine.devlin@gmail.com'

try:
    __version__ = version("ddl-generator")
except PackageNotFoundError:
    __version__ = "0.0.0"

from .console import generate  # noqa: F401 - re-exported for public API