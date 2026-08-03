========
Usage
========

Command Line
------------

Generate DDL from data files or inline JSON::

    $ ddlgenerator postgresql mydata.yaml

    $ ddlgenerator postgresql '[{"name": "Alice", "age": 30}]'

With INSERT statements::

    $ ddlgenerator -i postgresql mydata.json

With DROP TABLE statements::

    $ ddlgenerator -d postgresql mydata.yaml

Specify a primary key::

    $ ddlgenerator -k id postgresql mydata.yaml

Python API
----------

Basic usage::

    from ddlgenerator.ddlgenerator import Table

    # From a list of dictionaries
    data = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
    table = Table(data, table_name="users")

    # Generate SQL for different dialects
    sql = table.sql('postgresql')
    print(sql)

    # With INSERT statements
    sql_with_inserts = table.sql('postgresql', inserts=True)

    # Just the INSERT statements
    inserts = table.inserts('postgresql')

    # Generate SQLAlchemy models
    sqla_code = table.sqlalchemy()

Supported Dialects
------------------

The following SQL dialects are supported via SQLAlchemy:

- ``postgresql`` (aliases: ``pg``, ``pgsql``, ``postgres``)
- ``mysql``
- ``sqlite``
- ``oracle``
- ``mssql`` (Microsoft SQL Server)
- ``sqlalchemy`` (generates Python SQLAlchemy model code)
- ``django`` (generates Django model code, requires Django installed)

Supported Data Formats
----------------------

- **YAML** (``.yaml``, ``.yml``)
- **JSON** (``.json``)
- **CSV** (``.csv``)
- **HTML** (``.html``, ``.htm``) - parses HTML tables
- **Excel** (``.xls``) - requires ``xlrd``
- **URLs** - fetch data from HTTP/HTTPS URLs
- **Python objects** - lists, dictionaries, generators

Options
-------

``-k``, ``--key``
    Name for primary key column

``--force-key``
    Force every table to have a primary key

``-r``, ``--reorder``
    Reorder fields alphabetically, key first

``-u``, ``--uniques``
    Include UNIQUE constraints where data is unique

``-t``, ``--text``
    Use TEXT columns instead of VARCHAR

``-d``, ``--drops``
    Include DROP TABLE statements

``-i``, ``--inserts``
    Include INSERT statements

``--no-creates``
    Do not include CREATE TABLE statements

``--count-only``
    Report row counts per source and skip DDL/INSERT generation. Always
    reports the true total, ignoring ``--limit``/``--every-nth``. Cheap for
    xlsx/SQLAlchemy/MongoDB sources; requires a full read for CSV/JSON/YAML/
    HTML/``.xls`` sources.

``--limit``
    Maximum number of rows to read from each source

``--every-nth``
    Sample every Nth row instead of reading all rows (e.g. ``--every-nth 3``
    keeps rows 3, 6, 9, ...). Combines with ``--limit`` by striding first,
    then capping the surviving rows.

``--sample-k``
    Reservoir-sample exactly K rows per source (Algorithm R) instead of
    reading all rows. Gives an unbiased random sample without needing to
    know the source's total row count upfront. Cannot be combined with
    ``--limit`` or ``--every-nth``. Applies K independently per matched
    file when a source expands to multiple files (glob patterns) or
    multiple sheets/tables (xlsx, HTML).

``--seed``
    Random seed for ``--sample-k`` reproducibility. Optional; omit for an
    unseeded (non-reproducible) sample. Requires ``--sample-k``.

``-c``, ``--cushion``
    Extra length to pad column sizes

``--save-metadata-to``
    Save table structure for later reuse

``--use-metadata-from``
    Use saved table structure instead of analyzing data

``-l``, ``--log``
    Log level (DEBUG, INFO, WARN, ERROR)

Nested Data
-----------

DDL Generator handles nested data structures by creating child tables::

    data = [
        {"name": "Alice", "orders": [
            {"product": "Widget", "qty": 2},
            {"product": "Gadget", "qty": 1}
        ]}
    ]

    table = Table(data)
    # Creates: parent_table and parent_table_orders

Large Tables
------------

For large tables, use ``--save-metadata-to`` to save the table structure
from a sample, then use ``--use-metadata-from`` with ``--no-creates``
to generate INSERTs without re-analyzing::

    $ ddlgenerator --save-metadata-to meta.yaml postgresql sample.json
    $ ddlgenerator --use-metadata-from meta.yaml --no-creates -i postgresql full_data.json
