import argparse
import logging
import re
from typing import IO, Any

from ddlgenerator.ddlgenerator import (
    Table,
    dialect_names,
    emit_db_sequence_updates,
    sqla_head,
    sqla_inserter_call,
)
from ddlgenerator.sources import sqlalchemy_table_sources

parser = argparse.ArgumentParser(description='Generate DDL based on data')
parser.add_argument('dialect', help='SQL dialect to output', type=str.lower)
parser.add_argument('datafile', help='Path to file storing data (.yaml, .json, .csv, .xls, .xlsx, .html, URL, or SQLAlchemy URL)', nargs='+')
parser.add_argument('-k', '--key', help='If primary key needed, name it this', type=str.lower)
parser.add_argument('--force-key', help='Force every table to have a primary key',
                    action='store_true')
parser.add_argument('-r', '--reorder', help='Reorder fields alphabetically, ``key`` first',
                    action='store_true')
parser.add_argument('-u', '--uniques', action='store_true',
                    help='Include UNIQUE constraints where data is unique')
parser.add_argument('-t', '--text', action='store_true',
                    help='Use variable-length TEXT columns instead of VARCHAR')

parser.add_argument('-d', '--drops', action='store_true', help='Include DROP TABLE statements')
parser.add_argument('-i', '--inserts', action='store_true', help='Include INSERT statements')
parser.add_argument('--no-creates', action='store_true', help='Do not include CREATE TABLE statements')
parser.add_argument('--limit', type=int, default=None, help='Max number of rows to read from each source file')
parser.add_argument('-c', '--cushion', type=int, default=0, help='Extra length to pad column sizes with')
parser.add_argument('--save-metadata-to', type=str, metavar='FILENAME',
                    help='Save table definition in FILENAME for later --use-saved-metadata run')
parser.add_argument('--use-metadata-from', type=str, metavar='FILENAME',
                    help='Use metadata saved in FROM for table definition, do not re-analyze table structure')
parser.add_argument('-l', '--log', type=str.upper,
                    help='log level (CRITICAL, FATAL, ERROR, DEBUG, INFO, WARN)', default='WARN')


def set_logging(args: argparse.Namespace) -> None:
    try:
        loglevel = int(getattr(logging, args.log))
    except (AttributeError, TypeError) as err:
        raise NotImplementedError(
            f'log level "{args.log}" not one of CRITICAL, FATAL, ERROR, DEBUG, INFO, WARN'
        ) from err
    logging.getLogger().setLevel(loglevel)


is_sqlalchemy_url = re.compile("^{}".format("|".join(dialect_names)))


def generate_one(tbl: Any, args: argparse.Namespace,
                 table_name: str | None = None, file: IO[str] | None = None) -> Table:
    """
    Prints code (SQL, SQLAlchemy, etc.) to define a table.
    """
    table = Table(tbl, table_name=table_name, varying_length_text=args.text, uniques=args.uniques,
                  pk_name=args.key, force_pk=args.force_key, reorder=args.reorder, data_size_cushion=args.cushion,
                  save_metadata_to=args.save_metadata_to, metadata_source=args.use_metadata_from,
                  loglevel=args.log, limit=args.limit)
    if args.dialect.startswith('sqla'):
        if not args.no_creates:
            print(table.sqlalchemy(), file=file)
        if args.inserts:
            print("\n".join(table.inserts(dialect=args.dialect)), file=file)
    elif args.dialect.startswith('dj'):
        table.django_models()
    else:
        print(table.sql(dialect=args.dialect, inserts=args.inserts,
                        creates=(not args.no_creates), drops=args.drops,
                        metadata_source=args.use_metadata_from), file=file)
    return table


def generate(args: str | list[str] | None = None,
             namespace: argparse.Namespace | None = None,
             file: IO[str] | None = None) -> None:
    """
    Generate DDL from data sources named.

    :args:      String or list of strings to be parsed for arguments
    :namespace: Namespace to extract arguments from
    :file:      Write to this open file object (default stdout)
    """
    if isinstance(args, str):
        args = args.split()
    parsed = parser.parse_args(args, namespace)
    set_logging(parsed)
    logging.info(str(parsed))
    if parsed.dialect in ('pg', 'pgsql', 'postgres'):
        parsed.dialect = 'postgresql'
    if parsed.dialect.startswith('dj'):
        parsed.dialect = 'django'
    elif parsed.dialect.startswith('sqla'):
        parsed.dialect = 'sqlalchemy'

    if parsed.dialect not in dialect_names:
        raise NotImplementedError('First arg must be one of: {}'.format(", ".join(dialect_names)))
    if parsed.dialect == 'sqlalchemy':
        print(sqla_head, file=file)
    for datafile in parsed.datafile:
        if is_sqlalchemy_url.search(datafile):
            table_names_for_insert = []
            t = None
            for tbl in sqlalchemy_table_sources(datafile):
                t = generate_one(tbl, parsed, table_name=tbl.generator.name, file=file)
                if t.data:
                    table_names_for_insert.append(tbl.generator.name)
            if parsed.inserts and parsed.dialect == 'sqlalchemy':
                print(sqla_inserter_call(table_names_for_insert), file=file)
            if t is not None and parsed.inserts:
                for seq_update in emit_db_sequence_updates(t.source.db_engine):
                    if parsed.dialect == 'sqlalchemy':
                        print(f'    conn.execute("{seq_update}")', file=file)
                    elif parsed.dialect == 'postgresql':
                        print(seq_update, file=file)
        else:
            generate_one(datafile, parsed, file=file)
