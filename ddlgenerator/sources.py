#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Data source handling for ddlgenerator.

This module provides the Source class, a universal data generator that returns
one "row" at a time as OrderedDicts from various data sources.

Supported formats:
- CSV files (.csv)
- JSON files (.json)
- YAML files (.yaml, .yml)
- HTML tables (.html, .htm)
- Excel files (.xls) - requires xlrd
- URLs (http/https) - with SSRF protection via url_utils
- SQLAlchemy MetaData
- MongoDB collections - requires pymongo
- Python iterators/generators
- Inline data strings (JSON or YAML)

Security notes:
- Uses yaml.safe_load instead of yaml.load to prevent code execution
- Does not support .py, .pickle, .pkl files (blocked at ddlgenerator level)
- URL fetching uses SSRF-safe methods from url_utils
"""

from collections import OrderedDict
from io import StringIO
import csv
import itertools
import json
import logging
import os.path
import urllib.parse

try:
    import yaml
except ImportError:
    logging.info("Could not import pyyaml; YAML support disabled")
    yaml = None

try:
    import sqlalchemy
except ImportError:
    logging.info("Could not import sqlalchemy; database support disabled")
    sqlalchemy = None

try:
    from pymongo.collection import Collection as MongoCollection
except ImportError:
    logging.info("Could not import pymongo; MongoDB support disabled")
    MongoCollection = None.__class__

try:
    import xlrd
except ImportError:
    logging.info("Could not import xlrd; Excel support disabled")
    xlrd = None

try:
    import bs4
except ImportError:
    logging.info("Could not import beautifulsoup4; HTML support disabled")
    bs4 = None

try:
    from ddlgenerator import url_utils
except ImportError:
    import url_utils


class ParseException(Exception):
    """Raised when data parsing fails."""
    pass


def _ensure_rows(result):
    """
    Transform data into row-like format.

    If the data is a single dict, wrap it in a list.
    If it's a dict of dicts, convert to a list of dicts with name_ key.

    >>> _ensure_rows({"a": 1, "b": 2})
    [{'a': 1, 'b': 2}]
    >>> _ensure_rows({"a": {"a1": 1, "a2": 2}, "b": {"b1": 1, "b2": 2}})
    [{'a1': 1, 'a2': 2, 'name_': 'a'}, {'b1': 1, 'b2': 2, 'name_': 'b'}]
    >>> _ensure_rows([{"a1": 1, "a2": 2}, {"b1": 1, "b2": 2}])
    [{'a1': 1, 'a2': 2}, {'b1': 1, 'b2': 2}]
    """
    if isinstance(result, dict):
        if not result:
            result = []
        # if it's a dict of dicts, convert to a list of dicts
        if not [s for s in result.values() if not hasattr(s, 'keys')]:
            result = [dict(name_=k, **result[k]) for k in result]
        else:
            result = [result, ]
    return result


def _ordered_yaml_load(stream, **kwargs):
    """
    Load YAML preserving order with OrderedDict.
    Uses safe_load to prevent arbitrary code execution.
    """
    if yaml is None:
        raise ImportError('pyyaml not installed')

    # Use SafeLoader for security
    class OrderedLoader(yaml.SafeLoader):
        pass

    def construct_mapping(loader, node):
        return OrderedDict(loader.construct_pairs(node))

    OrderedLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping
    )

    result = yaml.load(stream, OrderedLoader)
    result = _ensure_rows(result)
    return iter(result)


def _json_loader(target, **kwargs):
    """Load JSON file returning iterator of OrderedDicts."""
    result = json.load(target, object_pairs_hook=OrderedDict)
    result = _ensure_rows(result)
    return iter(result)


def _interpret_fieldnames(target, fieldnames):
    """Interpret fieldnames parameter for CSV loading."""
    try:
        fieldname_line_number = int(fieldnames)
    except (ValueError, TypeError):
        return fieldnames
    reader = csv.reader(target)
    if fieldnames == 0:
        num_columns = len(next(reader))
        fieldnames = ['Field%d' % (i+1) for i in range(num_columns)]
    else:
        for i in range(fieldname_line_number):
            fieldnames = next(reader)
    return fieldnames


def _eval_csv(target, fieldnames=None, **kwargs):
    """Yield OrderedDicts from a CSV file."""
    fieldnames = _interpret_fieldnames(target, fieldnames)
    reader = csv.DictReader(target, fieldnames=fieldnames)
    for row in reader:
        yield OrderedDict((k, row[k]) for k in reader.fieldnames)


def _table_score(tbl):
    """Score an HTML table by how likely it contains useful data."""
    n_rows = len((tbl.tbody or tbl).find_all('tr', recursive=False))
    n_headings = len((tbl.thead or tbl).tr.find_all('th', recursive=False))
    n_columns = len(tbl.tr.find_all('td', recursive=False))
    score = n_columns * 3 + n_headings * 10 + n_columns
    if tbl.thead:
        score += 3
    return score


def _html_to_odicts(html, **kwargs):
    """Parse HTML and extract table data as OrderedDicts."""
    if not bs4:
        raise ImportError("BeautifulSoup4 not installed")
    soup = bs4.BeautifulSoup(html, 'html.parser')
    tables = sorted(soup.find_all('table'), key=_table_score, reverse=True)
    if not tables:
        raise ParseException('No HTML tables found')
    tbl = tables[0]
    skips = 1
    if (tbl.thead or tbl).tr.th:
        headers = [th.text for th in (tbl.thead or tbl).tr.find_all('th', recursive=False)]
    else:
        headers = [td.text for td in (tbl.tbody or tbl).tr.find_all('td', recursive=False)]
    for col_num, header in enumerate(headers):
        if not header:
            headers[col_num] = "Field%d" % (col_num + 1)
    for tr in (tbl.tbody or tbl).find_all('tr', recursive=False):
        if skips > 0:
            skips -= 1
            continue
        row = [td.text for td in tr.find_all('td')]
        yield OrderedDict(zip(headers, row))


class NamedIter:
    """Wrapper to attach a name attribute to an iterator."""

    def __init__(self, unnamed_iterator, name=None):
        self.__iter__ = unnamed_iterator.__iter__
        self.__next__ = unnamed_iterator.__next__
        self.name = name


def filename_from_url(url):
    """Extract filename from URL path."""
    return os.path.splitext(os.path.basename(urllib.parse.urlsplit(url).path))[0]


# Deserializers by file extension
_DESERIALIZERS = {
    '.json': [_json_loader],
    '.yaml': [_ordered_yaml_load],
    '.yml': [_ordered_yaml_load],
    '.csv': [_eval_csv],
    '.html': [_html_to_odicts],
    '.htm': [_html_to_odicts],
}

# Fallback deserializers to try when extension is unknown
_FALLBACK_DESERIALIZERS = [
    _json_loader,
    _ordered_yaml_load,
    _eval_csv,
    _html_to_odicts,
]


class Source:
    """
    Universal data source that yields OrderedDict rows.

    Usage::

        src = Source('mydata.csv')
        for row in src:
            print(row)

    Supported sources:
    - File paths: .csv, .json, .yaml, .yml, .html, .htm, .xls
    - URLs: http:// and https:// (with SSRF protection)
    - File-like objects with .read() method
    - SQLAlchemy MetaData objects
    - MongoDB Collection objects
    - Python iterators/generators
    - Inline data strings (JSON or YAML)

    Attributes:
        table_name: Name inferred from source (for DDL generation)
        generator: The underlying iterator
        db_engine: SQLAlchemy engine if source is a database
        limit: Maximum rows to yield
    """

    table_count = 0

    def __init__(self, src, limit=None, fieldnames=None, table='*'):
        """
        Initialize a data source.

        Args:
            src: Data source (path, URL, file object, iterator, etc.)
            limit: Maximum number of rows to read
            fieldnames: For CSV, override header row
            table: For Excel/SQLAlchemy, specific table/sheet name
        """
        self.counter = 0
        self.limit = limit
        self.table_name = 'Table%d' % (Source.table_count)
        self.fieldnames = fieldnames
        self.db_engine = None
        self.generator = None
        self.file = None
        self._file_opened_by_us = False  # Track if we opened the file
        Source.table_count += 1

        # SQLAlchemy MetaData
        if sqlalchemy and isinstance(src, sqlalchemy.sql.schema.MetaData):
            self._source_is_sqlalchemy_metadata(src, table)
            return

        # MongoDB Collection
        if isinstance(src, MongoCollection):
            self._source_is_mongo(src)
            return

        # URL
        if isinstance(src, str) and (src.startswith("http://") or src.startswith("https://")):
            self._source_is_url(src)
            return

        # File-like object
        if hasattr(src, 'read'):
            self._source_is_open_file(src)
            return

        # Iterator/generator
        if hasattr(src, '__next__'):
            self._source_is_generator(src)
            return

        # File path
        try:
            if os.path.isfile(src):
                if src.lower().endswith('.xls'):
                    self._source_is_excel(src, sheet=table)
                else:
                    self._source_is_path(src)
                return
        except TypeError:
            pass

        # Glob pattern
        try:
            import glob
            sources = sorted(glob.glob(src))
            if sources:
                self._multiple_sources(sources)
                return
        except (TypeError, ValueError, OSError):
            pass

        # Inline data string (try JSON then YAML)
        try:
            string_file = StringIO(src.strip())
            self._source_is_open_file(string_file)
            return
        except (TypeError, ValueError, SyntaxError, ParseException):
            pass

        raise NotImplementedError('Could not read data source %s of type %s' %
                                  (str(src), str(type(src))))

    def _source_is_generator(self, src):
        """Handle iterator/generator sources."""
        if hasattr(src, 'name'):
            self.table_name = src.name
        self.generator = src

    def _source_is_mongo(self, src):
        """Handle MongoDB collection sources."""
        self.table_name = src.name
        self.generator = src.find()

    def _source_is_sqlalchemy_metadata(self, meta, table):
        """Handle SQLAlchemy MetaData sources using SA 2.x API."""
        self.db_engine = meta.bind
        connection = meta.bind.connect()
        slct = sqlalchemy.sql.select(meta.tables[table])
        result = connection.execute(slct)
        self.generator = NamedIter(iter(result), name=table)
        self.table_name = table

    def _deserialize(self, open_file, deserializers):
        """Try deserializers in order until one succeeds."""
        errors = []
        for deserializer in deserializers:
            open_file.seek(0)
            try:
                self.generator = deserializer(open_file, fieldnames=self.fieldnames)
                row_1 = next(self.generator)
                open_file.seek(0)
                if row_1:
                    if deserializer == _ordered_yaml_load and isinstance(row_1, str) and len(row_1) == 1:
                        logging.info('false hit: reading yaml as a single string')
                        continue
                    open_file.seek(0)
                    self.generator = deserializer(open_file, fieldnames=self.fieldnames)
                    return
                else:
                    logging.info('%s found no items in first row of %s', deserializer, open_file)
            except StopIteration:
                open_file.seek(0)
                self.generator = deserializer(open_file, fieldnames=self.fieldnames)
                return
            except (ValueError, TypeError, SyntaxError, OSError) as e:
                # Catch specific parsing/file errors, let system exceptions propagate
                logging.info('%s failed to deserialize %s', deserializer, open_file)
                logging.info(str(e))
                errors.append(str(e))

        raise SyntaxError("%s: Could not deserialize %s (tried %s)\nErrors:\n%s" % (
            self.table_name, open_file, ", ".join(str(s) for s in deserializers), "\n".join(errors)))

    def _source_is_path(self, src):
        """Handle file path sources."""
        file_path, file_extension = os.path.splitext(src)
        self.table_name = os.path.split(file_path)[1]
        logging.info('Reading data from %s', src)
        file_extension = file_extension.lower()

        deserializers = _DESERIALIZERS.get(file_extension, _FALLBACK_DESERIALIZERS)
        # Keep file open during iteration - stored in self.file
        self.file = open(src, 'r', encoding='utf-8')
        self._file_opened_by_us = True
        self._deserialize(self.file, deserializers)

    def _source_is_open_file(self, src):
        """Handle file-like object sources."""
        if hasattr(src, 'name'):
            name = src.name
            self.table_name = os.path.splitext(os.path.basename(name))[0]
            ext = os.path.splitext(name)[1].lower()
            deserializers = _DESERIALIZERS.get(ext, _FALLBACK_DESERIALIZERS)
        else:
            deserializers = _FALLBACK_DESERIALIZERS

        self.file = src
        self._deserialize(src, deserializers)

    def _source_is_url(self, src):
        """Handle URL sources with SSRF protection."""
        self.table_name = filename_from_url(src) or 'url_data'

        core_url, ext = os.path.splitext(src)
        ext = ext.lower() if ext else '.html'

        # Use safe fetch with SSRF protection
        content = url_utils.safe_fetch_text(src)

        if ext.endswith('.xls'):
            self._source_is_excel(content.encode())
        elif ext == '.json':
            self._deserialize(StringIO(content), [_json_loader])
        elif ext in ('.yaml', '.yml'):
            self._deserialize(StringIO(content), [_ordered_yaml_load])
        elif ext in ('.html', '.htm'):
            self._deserialize(StringIO(content), [_html_to_odicts])
        elif ext == '.csv':
            self._deserialize(StringIO(content), [_eval_csv])
        else:
            # Try all deserializers
            self._deserialize(StringIO(content), _FALLBACK_DESERIALIZERS)

    def _source_is_excel_worksheet(self, sheet, name):
        """Extract data from an Excel worksheet."""
        headings = ["Col%d" % c for c in range(1, sheet.ncols + 1)]
        start_row = 0
        for row_n in range(sheet.nrows):
            row_has_data = any(bool(v) for v in sheet.row_values(row_n))
            if row_has_data:
                headings = [heading if heading else default_heading
                            for (heading, default_heading)
                            in itertools.zip_longest(sheet.row_values(row_n), headings)]
                start_row = row_n + 1
                break

        data = [OrderedDict(zip(headings, sheet.row_values(r)))
                for r in range(start_row, sheet.nrows)]
        generator = NamedIter(iter(data), name="%s-%s" % (name, sheet.name))
        return generator

    def _source_is_excel(self, spreadsheet, sheet='*'):
        """Handle Excel file sources."""
        if not xlrd:
            raise ImportError('must pip install xlrd for Excel support')

        if isinstance(spreadsheet, bytes):
            workbook = xlrd.open_workbook(file_contents=spreadsheet)
            name = "excel"
        elif len(spreadsheet) < 84 and spreadsheet.endswith('xls'):
            workbook = xlrd.open_workbook(spreadsheet)
            name = spreadsheet
        else:
            workbook = xlrd.open_workbook(file_contents=spreadsheet)
            name = "excel"

        if sheet == '*':
            generators = [self._source_is_excel_worksheet(s, name) for s in workbook.sheets()]
            self._multiple_sources(generators)
        else:
            try:
                sheet_obj = workbook.sheets()[int(sheet)]
            except ValueError:
                try:
                    sheet_idx = workbook.sheet_names().index(sheet)
                    sheet_obj = workbook.sheets()[sheet_idx]
                except ValueError:
                    raise Exception("Sheet name or index %s not in workbook %s" % (sheet, name))
            self.generator = self._source_is_excel_worksheet(sheet_obj, name)
            self.table_name = self.generator.name

    def _multiple_sources(self, sources):
        """Combine multiple sources into one iterator."""
        subsources = [Source(s, limit=self.limit) for s in sources]
        self.limit = None  # limit already applied to subsources
        self.generator = itertools.chain.from_iterable(subsources)

    def __iter__(self):
        return self

    def __next__(self):
        self.counter += 1
        if self.limit and (self.counter > self.limit):
            raise StopIteration
        return next(self.generator)

    def close(self):
        """Close any file opened by this Source."""
        if self._file_opened_by_us and self.file is not None:
            self.file.close()
            self.file = None
            self._file_opened_by_us = False

    def __enter__(self):
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager, ensuring file is closed."""
        self.close()
        return False


def sqlalchemy_table_sources(url):
    """
    Yield Source objects for each table in a SQLAlchemy database.

    Uses SQLAlchemy 2.x API (MetaData without bind parameter).

    Args:
        url: SQLAlchemy database URL

    Yields:
        Source objects, one per table
    """
    if sqlalchemy is None:
        raise ImportError('sqlalchemy not installed')

    engine = sqlalchemy.create_engine(url)
    meta = sqlalchemy.MetaData()
    meta.reflect(bind=engine)

    for table in meta.sorted_tables:
        yield Source(meta, table=table.name)
