import argparse
import logging
import re
from typing import IO, Any

from ddlgenerator import url_utils
from ddlgenerator.ddlgenerator import (
    Table,
    _validate_data_source,
    dialect_names,
    emit_db_sequence_updates,
    sqla_head,
    sqla_inserter_call,
)
from ddlgenerator.sources import Source, count_sqlalchemy_tables, sqlalchemy_table_sources

parser = argparse.ArgumentParser(description='Generate DDL based on data')
parser.add_argument('dialect', help='SQL dialect to output', type=str.lower)
parser.add_argument('datafile', help='Path to file storing data (.yaml, .json, .csv, .xls, .xlsx, .html, URL, or SQLAlchemy URL)', nargs='+')  # noqa: E501
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
parser.add_argument('--count-only', action='store_true',
                    help='Report row counts per source and skip DDL/INSERT generation')
parser.add_argument('--limit', type=int, default=None, help='Max number of rows to read from each source file')
parser.add_argument('--every-nth', type=int, default=None,
                    help='Sample every Nth row instead of reading all rows')
parser.add_argument('--sample-k', type=int, default=None,
                    help='Randomly sample exactly K rows per source (reservoir sampling)')
parser.add_argument('--sample-pct', type=float, default=None,
                    help='Randomly sample approximately this percent (0-100) of rows '
                         'per source (Bernoulli sampling)')
parser.add_argument('--seed', type=int, default=None,
                    help='Random seed for --sample-k/--sample-pct reproducibility')
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
                 table_name: str | None = None, file: IO[str] | None = None,
                 used_table_names: set[str] | None = None) -> Table:
    """
    Prints code (SQL, SQLAlchemy, etc.) to define a table.

    ``used_table_names`` is the pool of names already emitted this run; pass
    one so that two sources landing on the same name do not collide.
    """
    table = Table(tbl, table_name=table_name, varying_length_text=args.text, uniques=args.uniques,
                  pk_name=args.key, force_pk=args.force_key, reorder=args.reorder, data_size_cushion=args.cushion,
                  save_metadata_to=args.save_metadata_to, metadata_source=args.use_metadata_from,
                  loglevel=args.log, limit=args.limit, every_nth=args.every_nth,
                  sample_k=args.sample_k, seed=args.seed, sample_pct=args.sample_pct,
                  _used_table_names=used_table_names)
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


def run_count_only(args: argparse.Namespace, file: IO[str] | None = None) -> None:
    """
    Report row counts per source and exit without generating DDL/INSERTs.

    Always reports the true total record count, ignoring --limit/--every-nth/
    --sample-k/--sample-pct/--seed (this mode exists to help pick a sampling
    value for a subsequent run). xlsx, SQLAlchemy, and MongoDB sources use a cheap count;
    CSV/JSON/YAML/HTML/xls and generator sources must be fully read to count
    them.
    """
    logging.info(
        "--count-only: xlsx, SQLAlchemy, and MongoDB sources use a cheap count; "
        "CSV/JSON/YAML/HTML/xls and generator sources must be fully read to count them."
    )
    grand_total = 0
    for datafile in args.datafile:
        _validate_data_source(datafile)
        if is_sqlalchemy_url.search(datafile):
            pairs = count_sqlalchemy_tables(datafile)
        else:
            if url_utils.is_url(datafile):
                url_utils.validate_url(datafile)
            pairs = Source.count(datafile)
        subtotal = sum(n for (_name, n) in pairs)
        for (name, n) in pairs:
            print(f"{name}: {n}", file=file)
        if len(pairs) > 1:
            print(f"{datafile} subtotal: {subtotal}", file=file)
        grand_total += subtotal
    print(f"TOTAL: {grand_total}", file=file)


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
    if parsed.every_nth is not None and parsed.every_nth < 1:
        raise ValueError(f"--every-nth must be a positive integer, got {parsed.every_nth}")
    if parsed.sample_k is not None and parsed.sample_k < 1:
        raise ValueError(f"--sample-k must be a positive integer, got {parsed.sample_k}")
    if parsed.sample_k is not None and (parsed.limit is not None or parsed.every_nth is not None):
        raise ValueError("--sample-k cannot be combined with --limit or --every-nth")
    if parsed.sample_pct is not None and not 0 < parsed.sample_pct <= 100:
        raise ValueError(
            f"--sample-pct must be greater than 0 and at most 100, got {parsed.sample_pct}")
    if parsed.sample_pct is not None and (parsed.limit is not None
                                          or parsed.every_nth is not None
                                          or parsed.sample_k is not None):
        raise ValueError("--sample-pct cannot be combined with --limit, --every-nth, or --sample-k")
    if parsed.seed is not None and parsed.sample_k is None and parsed.sample_pct is None:
        raise ValueError("--seed requires --sample-k or --sample-pct")
    if parsed.count_only:
        run_count_only(parsed, file=file)
        return
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
    # One ``insert_test_rows`` covers every table from every datafile; a
    # second definition would shadow the first and strand its tables.  The
    # sequence updates trail the function body, so they are held back until
    # it has been written out.
    table_names_for_insert: list[str] = []
    sqla_sequence_updates: list[str] = []
    # Every table emitted this run shares one namespace -- one script, or one
    # target database -- so they are named out of a single pool.
    used_table_names: set[str] = set()
    for datafile in parsed.datafile:
        if is_sqlalchemy_url.search(datafile):
            t = None
            for tbl in sqlalchemy_table_sources(datafile, limit=parsed.limit,
                                                every_nth=parsed.every_nth,
                                                sample_k=parsed.sample_k,
                                                seed=parsed.seed,
                                                sample_pct=parsed.sample_pct):
                t = generate_one(tbl, parsed, table_name=tbl.generator.name, file=file,
                                 used_table_names=used_table_names)
                if t.data:
                    # the name the model defines, which is not always the name
                    # the source gave: it is cleaned, and may be uniquified
                    table_names_for_insert.append(t.table_name)
            if t is not None and parsed.inserts:
                for seq_update in emit_db_sequence_updates(t.source.db_engine):
                    if parsed.dialect == 'sqlalchemy':
                        sqla_sequence_updates.append(seq_update)
                    elif parsed.dialect == 'postgresql':
                        print(seq_update, file=file)
        else:
            t = generate_one(datafile, parsed, file=file,
                             used_table_names=used_table_names)
            if parsed.inserts and parsed.dialect == 'sqlalchemy':
                # nested data splits into child tables, which get their own
                # ``insert_*`` functions and so must be called as well
                table_names_for_insert.extend(t.insertable_table_names())
    if parsed.inserts and parsed.dialect == 'sqlalchemy':
        print(sqla_inserter_call(table_names_for_insert), file=file)
        for seq_update in sqla_sequence_updates:
            print(f'    conn.execute(text("{seq_update}"))', file=file)
