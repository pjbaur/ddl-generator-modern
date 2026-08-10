#!/usr/bin/env python
"""
Given data, automatically guess-generates DDL to create SQL tables.

Invoke with one table's worth of data at a time, from command line::

    $ ddlgenerator postgresql sourcedata.yaml

The ``-i`` flag generates INSERT statements as well::

    $ ddlgenerator -i postgresql sourcedata.yaml

or from Python::

    >>> menu = Table('../tests/menu.json')
    >>> ddl = menu.ddl('postgresql')
    >>> inserts = menu.inserts('postgresql')
    >>> all_sql = menu.sql('postgresql', inserts=True)

Use ``-k <keyname>`` or ``--key=<keyname>`` to set ``keyname`` as the table's
primary key.  If the field does not exist, it will be added.  If ``-k`` is not given,
no primary key will be created, *unless* it is required to set up child tables
(split out from sub-tables nested inside the original data).

You will need to hand-edit the resulting SQL to add indexes.

You can use wildcards to generate from multiple files at once::

    $ ddlgenerator postgresql "*.csv"

Remember to enclose the file path in quotes to prevent the shell
from expanding the argument (if it does, ddlgenerator will run
against each file *separately*, setting up one table for each).
"""
from __future__ import annotations

import copy
import datetime
import doctest
import logging
import os.path
import pprint
import re
import secrets
import textwrap
from collections import OrderedDict
from collections.abc import Iterable, Iterator
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import dateutil.parser
import sqlalchemy as sa
import yaml
from sqlalchemy.schema import CreateTable

if TYPE_CHECKING:
    pymongo: Any = None
else:
    try:
        import pymongo
    except ImportError:
        pymongo = None
import ddlgenerator.typehelpers as th
from ddlgenerator import reshape, url_utils
from ddlgenerator.sources import Source

# Module-level logger - libraries should never call logging.basicConfig()
# as it configures the root logger and affects all logging in the application.
# Instead, we create our own logger and let the application configure handlers.
logger = logging.getLogger(__name__)

# Security: File extensions that are blocked to prevent arbitrary code execution
# These extensions use eval() or pickle deserialization in data_dispenser
BLOCKED_EXTENSIONS = frozenset(['.py', '.pyw', '.pickle', '.pkl'])


class UnsafeInputError(ValueError):
    """Raised when input file type is blocked for security reasons."""
    pass


def _validate_data_source(data: Any) -> None:
    """
    Validate data source to prevent arbitrary code execution.

    Blocks file extensions that use eval() or pickle deserialization.
    Safe extensions include: .json, .yaml, .yml, .csv, .html, .htm, .xls, .xlsx

    Args:
        data: Input data (file path, file object, or other)

    Raises:
        UnsafeInputError: If data source uses a blocked file extension
    """
    if isinstance(data, str):
        # Check if it's a file path with a blocked extension
        ext = os.path.splitext(data.lower())[1]
        if ext in BLOCKED_EXTENSIONS:
            raise UnsafeInputError(
                f"File extension '{ext}' is not allowed for security reasons. "
                f"Blocked extensions: {', '.join(sorted(BLOCKED_EXTENSIONS))}. "
                f"Safe alternatives: .json, .yaml, .yml, .csv, .html, .xls, .xlsx"
            )
    elif hasattr(data, 'name') and isinstance(data.name, str):
        # File-like object with a name attribute
        ext = os.path.splitext(data.name.lower())[1]
        if ext in BLOCKED_EXTENSIONS:
            raise UnsafeInputError(
                f"File extension '{ext}' is not allowed for security reasons. "
                f"Blocked extensions: {', '.join(sorted(BLOCKED_EXTENSIONS))}. "
                f"Safe alternatives: .json, .yaml, .yml, .csv, .html, .xls, .xlsx"
            )


class KeyAlreadyExists(KeyError):
    pass


dialect_names = '''drizzle firebird mssql mysql oracle postgresql
                   sqlite sybase sqlalchemy django'''.split()


def _dump(sql: Any, *multiparams: Any, **params: Any) -> None:
    pass


mock_engines = {}
for engine_name in ('postgresql', 'sqlite', 'mysql', 'oracle', 'mssql'):
    mock_engines[engine_name] = sa.create_mock_engine(f'{engine_name}://',
                                                      executor=_dump)


# Cache for literal processors per dialect to avoid repeated creation
_literal_processor_cache: dict[str, Any] = {}


def _get_literal_processor(dialect_name: str) -> Any:
    """
    Get a SQLAlchemy literal processor for safe string escaping.

    Uses the dialect's native escaping rules to prevent SQL injection.
    Caches processors for performance.

    Args:
        dialect_name: Name of the SQL dialect (e.g., 'postgresql', 'mysql')

    Returns:
        A function that escapes values for safe SQL literal rendering
    """
    if dialect_name not in _literal_processor_cache:
        engine = mock_engines.get(dialect_name)
        if engine:
            from sqlalchemy.types import String
            str_type = String()
            _literal_processor_cache[dialect_name] = str_type.literal_processor(engine.dialect)
        else:
            # Fallback for unknown dialects - use PostgreSQL-style escaping
            from sqlalchemy.dialects import postgresql
            from sqlalchemy.types import String
            str_type = String()
            _literal_processor_cache[dialect_name] = str_type.literal_processor(postgresql.dialect())
    return _literal_processor_cache[dialect_name]


def _escape_string_value(value: str, dialect_name: str) -> str:
    """
    Safely escape a string value for use in SQL statements.

    Uses SQLAlchemy's dialect-specific literal processor to ensure
    proper escaping per database type.

    Args:
        value: The string value to escape
        dialect_name: Name of the SQL dialect

    Returns:
        The safely escaped string ready for SQL literal use
    """
    processor = _get_literal_processor(dialect_name)
    return str(processor(value))


# Whitelist of Python types that can appear as an inferred column's
# ``sample_datum``.  Metadata files store type *names* (strings); on load we
# resolve a name back to a type through this registry only -- never by
# importing arbitrary modules -- so a crafted metadata file cannot trigger
# arbitrary code execution the way ``yaml.unsafe_load`` could.
_METADATA_PYTYPE_REGISTRY: dict[str, type] = {
    'builtins.str': str,
    'builtins.int': int,
    'builtins.float': float,
    'builtins.bool': bool,
    'builtins.NoneType': type(None),
    'decimal.Decimal': Decimal,
    'datetime.datetime': datetime.datetime,
    'datetime.date': datetime.date,
}


def _pytype_name(pytype: type) -> str:
    """Fully-qualified, registry-stable name for a Python type."""
    return f"{pytype.__module__}.{pytype.__qualname__}"


def _column_metadata_to_safe(col: dict[str, Any]) -> dict[str, Any]:
    """
    Convert one in-memory column descriptor into plain YAML-safe scalars.

    Only ``Decimal`` / ``datetime`` samples are non-native for YAML; those are
    stringified and rebuilt on load using the stored ``pytype`` name.
    """
    sample = col.get('sample_datum')
    pytype = col.get('pytype') or type(sample)
    if isinstance(sample, (datetime.datetime, datetime.date)):
        sample_repr: Any = sample.isoformat()
    elif isinstance(sample, Decimal):
        sample_repr = str(sample)
    else:
        sample_repr = sample
    return {
        'pytype': _pytype_name(pytype),
        'sample_datum': sample_repr,
        'str_length': col.get('str_length'),
        'is_nullable': col.get('is_nullable'),
        'is_unique': col.get('is_unique'),
    }


def _column_metadata_from_safe(col: dict[str, Any]) -> dict[str, Any]:
    """Reverse of :func:`_column_metadata_to_safe` for a single column."""
    try:
        pytype = _METADATA_PYTYPE_REGISTRY[col['pytype']]
    except KeyError:
        # Reject anything outside the whitelist rather than importing it --
        # a tampered metadata file must not be able to name arbitrary code.
        raise ValueError(
            f"Unknown column type {col['pytype']!r} in metadata file; "
            f"not a recognized ddlgenerator column type.") from None
    sample: Any = col['sample_datum']
    if pytype is Decimal:
        sample = Decimal(str(sample))
    elif pytype is datetime.datetime:
        sample = datetime.datetime.fromisoformat(str(sample))
    elif pytype is datetime.date:
        sample = datetime.date.fromisoformat(str(sample))
    # native scalars (str/int/float/bool/None) round-trip via safe_load as-is
    return {
        'sample_datum': sample,
        'pytype': pytype,
        'str_length': col['str_length'],
        'is_nullable': col['is_nullable'],
        'is_unique': col['is_unique'],
    }


def _metadata_to_safe(mixed: OrderedDict) -> dict[str, Any]:
    """
    Serialize a table's in-memory column metadata to a plain, YAML-safe dict.

    The in-memory structure interleaves leaf columns (plain ``dict`` values)
    with child-table metadata (``OrderedDict`` values).  We split them into an
    explicit ``columns`` / ``children`` shape so the file round-trips through
    ``yaml.safe_dump`` / ``yaml.safe_load`` without relying on Python object
    tags (which ``safe_load`` refuses and which would be unsafe to restore).
    """
    columns: dict[str, Any] = {}
    children: dict[str, Any] = {}
    for name, value in mixed.items():
        if isinstance(value, OrderedDict):
            children[name] = _metadata_to_safe(value)
        else:
            columns[name] = _column_metadata_to_safe(value)
    return {'columns': columns, 'children': children}


def _metadata_from_safe(node: dict[str, Any]) -> OrderedDict:
    """Reverse of :func:`_metadata_to_safe`, returning the mixed OrderedDict."""
    result: OrderedDict = OrderedDict()
    for name, col in (node or {}).get('columns', {}).items():
        result[name] = _column_metadata_from_safe(col)
    for name, child_node in (node or {}).get('children', {}).items():
        result[name] = _metadata_from_safe(child_node)
    return result


class Table:
    """
    >>> data = '''
    ... -
    ...   name: Lancelot
    ...   kg: 69.4
    ...   dob: 9 jan 461
    ... -
    ...   name: Gawain
    ...   kg: 69.4  '''
    >>> print(Table(data, "knights").ddl('postgresql').strip()) # doctest: +NORMALIZE_WHITESPACE
    DROP TABLE IF EXISTS knights;
    <BLANKLINE>
    CREATE TABLE knights (
        name VARCHAR(8) NOT NULL,
        kg DECIMAL(3, 1) NOT NULL,
        dob TIMESTAMP WITHOUT TIME ZONE
    );
    """

    table_index: int = 0

    table_name: str
    metadata: sa.MetaData
    comments: dict[str, str]

    def _find_table_name(self, data: Any) -> None:
        if not self.table_name:
            if pymongo and isinstance(data, pymongo.collection.Collection):
                self.table_name = data.name
            elif hasattr(data, 'lower'):  # duck-type string test
                if os.path.isfile(data):
                    (file_path, file_extension) = os.path.splitext(data)
                    self.table_name = os.path.split(file_path)[1].lower()
        self.table_name = (self.table_name
                           or f'generated_table{Table.table_index}')
        self.table_name = reshape.clean_key_name(self.table_name)
        Table.table_index += 1

    def __init__(
        self,
        data: Any,
        table_name: str | None = None,
        default_dialect: str | None = None,
        save_metadata_to: str | None = None,
        metadata_source: str | OrderedDict | None = None,
        varying_length_text: bool = False,
        uniques: bool = False,
        pk_name: str | None = None,
        force_pk: bool = False,
        data_size_cushion: int = 0,
        _parent_table: Table | None = None,
        _fk_field_name: str | None = None,
        reorder: bool = False,
        loglevel: int = logging.WARNING,
        limit: int | None = None,
        every_nth: int | None = None,
        sample_k: int | None = None,
        seed: int | None = None,
        sample_pct: float | None = None,
    ) -> None:
        """
        Initialize a Table and load its data.

        If ``varying_length_text`` is ``True``,
        text columns will be TEXT rather than VARCHAR.
        This *improves* performance in PostgreSQL.

        If a ``metadata<timestamp>`` YAML file generated
        from a previous ddlgenerator run is
        provided, *only* ``INSERT`` statements will be produced,
        and the table structure
        determined during the previous run will be assumed.
        """
        self.source = data
        logging.getLogger().setLevel(loglevel)
        self.varying_length_text = varying_length_text
        self.table_name = table_name or ''
        self.data_size_cushion = data_size_cushion
        self._find_table_name(data)
        if _parent_table is not None:
            self.metadata = _parent_table.metadata
        else:
            self.metadata = sa.MetaData()
        # Security: Validate data source before processing
        _validate_data_source(data)
        # Send anything but Python data objects to
        # data_dispenser.sources.Source
        if isinstance(data, Source):
            self.data = data
        elif isinstance(data, str) or hasattr(data, 'read'):
            # Validate URLs for SSRF prevention before passing to Source
            if isinstance(data, str) and url_utils.is_url(data):
                url_utils.validate_url(data)
            self.data = Source(data, limit=limit, every_nth=every_nth,
                               sample_k=sample_k, seed=seed,
                               sample_pct=sample_pct)
        else:
            try:
                self.data = iter(data)
            except TypeError:
                self.data = Source(data)

        if (self.table_name.startswith('generated_table')
                and hasattr(self.data, 'table_name')):
            self.table_name = self.data.table_name
        self.table_name = self.table_name.lower()

        if hasattr(self.data, 'generator') and hasattr(self.data.generator, 'sqla_columns'):
            children: dict[str, Any] = {}
            self.pk_name = next(col.name for col in self.data.generator.sqla_columns if col.primary_key)
        else:
            self.data = reshape.walk_and_clean(self.data)
            (self.data, self.pk_name, children,
             child_fk_names) = reshape.unnest_children(data=self.data,
                                                       parent_name=self.table_name,
                                                       pk_name=pk_name,
                                                       force_pk=force_pk)

        self.default_dialect = default_dialect
        self.comments = {}
        child_metadata_sources = {}
        if metadata_source:
            if isinstance(metadata_source, OrderedDict):
                logger.info('Column metadata passed in as OrderedDict')
                self.columns = metadata_source
            else:
                logger.info(f'Pulling column metadata from file {metadata_source}')
                with open(metadata_source) as infile:
                    self.columns = _metadata_from_safe(yaml.safe_load(infile.read()))
            for (col_name, col) in list(self.columns.items()):
                if isinstance(col, OrderedDict):
                    child_metadata_sources[col_name] = col
                    self.columns.pop(col_name)
                else:
                    self._fill_metadata_from_sample(col)
        else:
            self._determine_types()

        if reorder:
            ordered_columns = OrderedDict()
            if pk_name and pk_name in self.columns:
                ordered_columns[pk_name] = self.columns.pop(pk_name)
            for (c, v) in sorted(self.columns.items()):
                ordered_columns[c] = v
            self.columns = ordered_columns

        if _parent_table:
            fk = sa.ForeignKey(f'{_parent_table.table_name}.{_parent_table.pk_name}')
        else:
            fk = None

        self.table = sa.Table(self.table_name, self.metadata,
                              *[sa.Column(cname, col['satype'],
                                          *([fk] if fk and (_fk_field_name == cname)
                                            else []),
                                          primary_key=(cname == self.pk_name),
                                          unique=(uniques and col['is_unique']),
                                          nullable=col['is_nullable'],
                                          doc=self.comments.get(cname))
                                for (cname, col) in self.columns.items()
                                ])

        self.children = {child_name: Table(child_data, table_name=child_name,
                                           default_dialect=self.default_dialect,
                                           varying_length_text=varying_length_text,
                                           uniques=uniques, pk_name=pk_name,
                                           force_pk=force_pk, data_size_cushion=data_size_cushion,
                                           _parent_table=self, reorder=reorder,
                                           _fk_field_name=child_fk_names[child_name],
                                           metadata_source=child_metadata_sources.get(child_name),
                                           loglevel=loglevel)
                         for (child_name, child_data) in children.items()}

        if save_metadata_to:
            if not save_metadata_to.endswith(('.yml', 'yaml')):
                save_metadata_to += '.yaml'
            with open(save_metadata_to, 'w') as outfile:
                outfile.write(yaml.safe_dump(
                    _metadata_to_safe(self._saveable_metadata()),
                    default_flow_style=False, sort_keys=False, allow_unicode=True))
            logger.info(f'Pass ``--save-metadata-to {save_metadata_to}`` next time to re-use structure')

    def _saveable_metadata(self) -> OrderedDict:
        result = copy.copy(self.columns)
        for v in result.values():
            v.pop('satype')  # yaml chokes on sqla classes
        for (child_name, child) in self.children.items():
            result[child_name] = child._saveable_metadata()
        return result

    def _dialect(self, dialect: str | None) -> str:
        if not dialect and not self.default_dialect:
            raise KeyError("No SQL dialect specified")
        dialect = dialect or self.default_dialect
        if dialect not in mock_engines:
            raise NotImplementedError(f"SQL dialect '{dialect}' unknown")
        return dialect

    _supports_if_exists = {k: False for k in dialect_names}
    _supports_if_exists['postgresql'] = _supports_if_exists['sqlite'] = True
    _supports_if_exists['mysql'] = _supports_if_exists['sybase'] = True

    def _dropper(self, dialect: str) -> str:
        template = "DROP TABLE %s %s"
        if_exists = "IF EXISTS" if self._supports_if_exists[dialect] else ""
        return template % (if_exists, self.table_name)

    _comment_wrapper = textwrap.TextWrapper(initial_indent='-- ', subsequent_indent='-- ')

    def ddl(self, dialect: str | None = None, creates: bool = True, drops: bool = True) -> str:
        """
        Returns SQL to define the table.
        """
        dialect = self._dialect(dialect)
        compiled = CreateTable(self.table).compile(mock_engines[dialect])
        creator = "\n".join(line for line in str(compiled).splitlines() if line.strip())  # remove empty lines
        comments = "\n\n".join(self._comment_wrapper.fill(f"in {col}: {self.comments[col]}")
                               for col in self.comments)
        result = []
        if drops:
            result.append(self._dropper(dialect) + ';')
        if creates:
            result.append(f"{creator};\n{comments}")
        for child in self.children.values():
            result.append(child.ddl(dialect=dialect, creates=creates,
                          drops=drops))
        return '\n\n'.join(result)

    table_backref_remover = re.compile(r',\s+table\s*\=\<.*?\>')
    capitalized_words = re.compile(r"\b[A-Z]\w+")
    sqlalchemy_setup_template = textwrap.dedent("""
        from sqlalchemy import %s

        %s

        metadata.create_all(engine)""")

    def sqlalchemy(self, is_top: bool = True) -> str:
        """Dumps Python code to set up the table's  SQLAlchemy model"""
        table_def = self.table_backref_remover.sub('', self.table.__repr__())

        # inject UNIQUE constraints into table definition
        # self.table.constraints is a plain set, so iterating it directly
        # orders entries by object id rather than any deterministic key;
        # sort by creation order (same key SQLAlchemy's own DDL compiler
        # uses for constraints) to keep output stable across runs.
        unique_constraints = sorted(
            (c for c in self.table.constraints
             if isinstance(c, sa.sql.schema.UniqueConstraint)),
            key=lambda c: c._creation_order)
        constraint_defs = [
            'UniqueConstraint({})'.format(
                ', '.join(f"'{c.name}'" for c in constraint.columns))
            for constraint in unique_constraints
        ]
        if constraint_defs:
            constraint_block = ',\n  '.join(constraint_defs) + ','
            table_def = table_def.replace('schema=None', '\n  ' + constraint_block + 'schema=None')

        table_def = table_def.replace("MetaData()", "metadata")
        table_def = table_def.replace("Column(", "\n  Column(")
        table_def = table_def.replace("schema=", "\n  schema=")
        parts = [table_def, ]
        parts.extend(c.sqlalchemy(is_top=False) for c in self.children.values())
        result = "\n{} = {}".format(self.table_name, "\n".join(parts))
        if is_top:
            found_imports = set(self.capitalized_words.findall(table_def))
            found_imports &= set(dir(sa))
            result = self.sqlalchemy_setup_template % (
                ", ".join(sorted(found_imports)), result)
            result = textwrap.dedent(result)
        return result

    def django_models(self, metadata_source: str | None = None) -> None:
        sql = self.sql(dialect='postgresql', inserts=False, creates=True,
                       drops=True, metadata_source=metadata_source)
        u = sql.split(';\n')

        try:
            import django
        except ImportError:
            print('Cannot find Django on the current path. Is it installed?')
            django = None

        if django:
            import os
            import sqlite3

            from django.conf import settings
            from django.core import management

            db_filename = 'generated_db.db'
            conn = None
            try:
                conn = sqlite3.connect(db_filename)
                c = conn.cursor()
                for i in u:
                    c.execute(i)
                conn.commit()

                if not settings.configured:
                    settings.configure(
                        DEBUG='on',
                        # Throwaway key for inspectdb only - not used for any security-sensitive operations
                        SECRET_KEY=secrets.token_hex(32),
                        ALLOWED_HOSTS='localhost',
                        DATABASES={'default': {'NAME': db_filename, 'ENGINE': 'django.db.backends.sqlite3'}},
                    )
                    django.setup()
                management.call_command('inspectdb')
            finally:
                if conn is not None:
                    conn.close()
                if os.path.exists(db_filename):
                    os.remove(db_filename)

    def _prep_datum(self, datum: Any, dialect: str, col: str, needs_conversion: bool) -> str:
        """Puts a value in proper format for a SQL string using safe escaping."""
        if datum is None or (needs_conversion and not str(datum).strip()):
            return 'NULL'
        pytype = self.columns[col]['pytype']

        if needs_conversion:
            if pytype is datetime.datetime:
                datum = dateutil.parser.parse(datum)
            elif pytype is bool:
                datum = th.coerce_to_specific(datum)
                if dialect.startswith('sqlite'):
                    datum = 1 if datum else 0
            else:
                datum = pytype(str(datum))

        if isinstance(datum, datetime.datetime) or isinstance(datum, datetime.date):
            # Standard ISO format works across most databases
            return f"'{datum}'"
        elif hasattr(datum, 'lower'):
            # Use SQLAlchemy's safe literal processor for string escaping
            return _escape_string_value(datum, dialect)
        else:
            return str(datum)

    _insert_template = "INSERT INTO {table_name} ({cols}) VALUES ({vals});"

    def inserts(self, dialect: str | None = None) -> Iterator[str]:
        if dialect and dialect.startswith("sqla"):
            if self.data:
                yield f"\ndef insert_{self.table_name}(tbl, conn):"
                yield "    inserter = tbl.insert()"
                for row in self.data:
                    # SQLAlchemy 2.x takes bind parameters as a mapping
                    # argument, not as keyword arguments
                    yield textwrap.indent(f"conn.execute(inserter, {str(dict(row))})",
                                          "    ")
                # only a Source reading from a live database has an engine
                for seq_updater in emit_db_sequence_updates(
                        getattr(self.source, 'db_engine', None)):
                    yield f'    conn.execute("{seq_updater}")'
            else:
                yield f"\n# No data for {self.table.name}"
        else:
            dialect = self._dialect(dialect)
            needs_conversion = not hasattr(self.data, 'generator') or not hasattr(self.data.generator, 'sqla_columns')
            for row in self.data:
                cols = ", ".join(c for c in row.keys())
                vals = ", ".join(str(self._prep_datum(val, dialect, key, needs_conversion))
                                 for (key, val) in row.items())
                yield self._insert_template.format(table_name=self.table_name,
                                                   cols=cols, vals=vals)
            for child in self.children.values():
                for row in child.inserts(dialect):
                    yield row

    def sql(self, dialect: str | None = None, inserts: bool = False, creates: bool = True,
            drops: bool = True, metadata_source: str | OrderedDict | None = None) -> str:
        """
        Combined results of ``.ddl(dialect)`` and, if ``inserts==True``,
        ``.inserts(dialect)``.
        """
        result = [self.ddl(dialect, creates=creates, drops=drops)]
        if inserts:
            for row in self.inserts(dialect):
                result.append(row)
        return '\n'.join(result)

    def __str__(self) -> str:
        if self.default_dialect:
            return self.ddl()
        else:
            return self.__repr__()

    def _fill_metadata_from_sample(self, col: dict[str, Any]) -> dict[str, Any]:
        col['pytype'] = type(col['sample_datum'])
        if isinstance(col['sample_datum'], Decimal):
            (precision, scale) = th.precision_and_scale(col['sample_datum'])
            col['satype'] = sa.DECIMAL(precision + self.data_size_cushion * 2,
                                       scale + self.data_size_cushion)
        elif isinstance(col['sample_datum'], str):
            if self.varying_length_text:
                col['satype'] = sa.Text()
            else:
                str_len = max(len(col['sample_datum']), col['str_length'])
                col['satype'] = sa.Unicode(str_len + self.data_size_cushion * 2)
        else:
            col['satype'] = self.types2sa[type(col['sample_datum'])]
            if col['satype'] == sa.Integer and (
                    col['sample_datum'] > (2147483647 - self.data_size_cushion * 1000000000)
                    or col['sample_datum'] < (-2147483647 + self.data_size_cushion * 1000000000)):
                col['satype'] = sa.BigInteger
        return col

    types2sa = {datetime.datetime: sa.DateTime, int: sa.Integer,
                float: sa.Numeric, bool: sa.Boolean,
                type(None): sa.Text}

    def _determine_types(self) -> None:
        self.columns = OrderedDict()
        if hasattr(self.data, 'generator') and hasattr(self.data.generator, 'sqla_columns'):
            for col in self.data.generator.sqla_columns:
                self.columns[col.name] = {'is_nullable': col.nullable,
                                          'is_unique': col.unique,
                                          'satype': col.type,
                                          'pytype': col.pytype}
            return
        self.comments = {}
        rowcount = 0
        for row in self.data:
            rowcount += 1
            keys = row.keys()
            for col_name in self.columns:
                if col_name not in keys:
                    self.columns[col_name]['is_nullable'] = True
            if not isinstance(row, OrderedDict):
                keys = sorted(keys)
            for k in keys:
                v_raw = row[k]
                if not th.is_scalar(v_raw):
                    self.comments[k] = f'nested values! example:\n{pprint.pformat(str(v_raw))}'
                    logger.warning(f'in {k}: {self.comments[k]}')
                v = th.coerce_to_specific(v_raw)
                if k not in self.columns:
                    self.columns[k] = {'sample_datum': v,
                                       'str_length': len(str(v_raw)),
                                       'is_nullable': not (rowcount == 1
                                                           and v is not None
                                                           and str(v).strip()),
                                       'is_unique': set([v, ])}
                else:
                    col = self.columns[k]
                    col['str_length'] = max(col['str_length'], len(str(v_raw)))
                    col['sample_datum'] = th.best_representative(
                        col['sample_datum'], v)
                    if (v is None) or (not str(v).strip()):
                        col['is_nullable'] = True
                    if (col['is_unique'] is not False):
                        if v in col['is_unique']:
                            col['is_unique'] = False
                        else:
                            col['is_unique'].add(v)
        for col_name in self.columns:
            col = self.columns[col_name]
            self._fill_metadata_from_sample(col)
            col['is_unique'] = bool(col['is_unique'])


sqla_head = """
import datetime
# check for other imports you may need, like your db driver
from sqlalchemy import create_engine, MetaData, ForeignKey
engine = create_engine(r'sqlite:///:memory:')
metadata = MetaData()
conn = engine.connect()"""


def sqla_inserter_call(table_names: Iterable[str]) -> str:
    """Generate Python code string that defines an insert_test_rows function.

    Returns a string containing a function definition (not a callable function).
    The generated function inserts test rows into the specified tables.
    This is a code generator used by the SQLAlchemy output workflow.
    """
    return '''

def insert_test_rows(meta: Any, conn: Any) -> None:
    """Calls insert_* functions to create test data.

    Given a SQLAlchemy metadata object ``meta`` and
    a SQLAlchemy connection ``conn``, populate the tables
    in ``meta`` with test data.

    Call ``meta.reflect()`` before passing calling this."""

{}
    conn.commit()
'''.format('\n'.join(f"    insert_{t}(meta.tables['{t}'], conn)"
                     for t in table_names))


def emit_db_sequence_updates(engine: Any) -> Iterator[str]:
    """Set database sequence objects to match the source db

       Relevant only when generated from SQLAlchemy connection.
       Needed to avoid subsequent unique key violations after DB build."""

    if engine and engine.name == 'postgresql':
        # not implemented for other RDBMS; necessity unknown
        conn = engine.connect()
        seq_query = """SELECT 'SELECT last_value FROM ' || n.nspname ||
                         '.' || c.relname || ';' AS qry,
                        n.nspname || '.' || c.relname AS qual_name
                 FROM   pg_namespace n
                 JOIN   pg_class c ON (n.oid = c.relnamespace)
                 WHERE  c.relkind = 'S'"""
        for (qry, qual_name) in list(conn.execute(seq_query)):
            (lastval, ) = conn.execute(qry).first()
            nextval = int(lastval) + 1
            yield f"ALTER SEQUENCE {qual_name} RESTART WITH {nextval};"


if __name__ == '__main__':
    doctest.testmod(optionflags=doctest.NORMALIZE_WHITESPACE)
