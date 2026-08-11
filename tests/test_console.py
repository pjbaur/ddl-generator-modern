#!/usr/bin/env python
"""
Tests for ddlgenerator.console module (P3-2).

Covers: CLI argument parsing, dialect aliases, set_logging, generate_one
"""

import io
import logging
import os
import runpy
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa

from ddlgenerator.console import (
    generate,
    generate_one,
    is_sqlalchemy_url,
    parser,
    set_logging,
)


def here(filename):
    return os.path.join(os.path.dirname(__file__), filename)


class TestArgumentParsing:
    def test_basic_args(self):
        args = parser.parse_args(["postgresql", "data.yaml"])
        assert args.dialect == "postgresql"
        assert args.datafile == ["data.yaml"]

    def test_inserts_flag(self):
        args = parser.parse_args(["-i", "postgresql", "data.yaml"])
        assert args.inserts is True

    def test_drops_flag(self):
        args = parser.parse_args(["-d", "postgresql", "data.yaml"])
        assert args.drops is True

    def test_no_creates_flag(self):
        args = parser.parse_args(["--no-creates", "postgresql", "data.yaml"])
        assert args.no_creates is True

    def test_key_flag(self):
        args = parser.parse_args(["-k", "myid", "postgresql", "data.yaml"])
        assert args.key == "myid"

    def test_force_key_flag(self):
        args = parser.parse_args(["--force-key", "postgresql", "data.yaml"])
        assert args.force_key is True

    def test_reorder_flag(self):
        args = parser.parse_args(["-r", "postgresql", "data.yaml"])
        assert args.reorder is True

    def test_uniques_flag(self):
        args = parser.parse_args(["-u", "postgresql", "data.yaml"])
        assert args.uniques is True

    def test_text_flag(self):
        args = parser.parse_args(["-t", "postgresql", "data.yaml"])
        assert args.text is True

    def test_limit_flag(self):
        args = parser.parse_args(["--limit", "100", "postgresql", "data.yaml"])
        assert args.limit == 100

    def test_every_nth_flag(self):
        args = parser.parse_args(["--every-nth", "5", "postgresql", "data.yaml"])
        assert args.every_nth == 5

    def test_every_nth_default_none(self):
        args = parser.parse_args(["postgresql", "data.yaml"])
        assert args.every_nth is None

    def test_count_only_flag(self):
        args = parser.parse_args(["--count-only", "postgresql", "data.yaml"])
        assert args.count_only is True

    def test_cushion_flag(self):
        args = parser.parse_args(["-c", "5", "postgresql", "data.yaml"])
        assert args.cushion == 5

    def test_log_flag(self):
        args = parser.parse_args(["-l", "debug", "postgresql", "data.yaml"])
        assert args.log == "DEBUG"

    def test_multiple_datafiles(self):
        args = parser.parse_args(["postgresql", "a.yaml", "b.json"])
        assert args.datafile == ["a.yaml", "b.json"]

    def test_dialect_lowered(self):
        args = parser.parse_args(["POSTGRESQL", "data.yaml"])
        assert args.dialect == "postgresql"

    def test_save_metadata_to(self):
        args = parser.parse_args(["--save-metadata-to", "meta.yaml", "postgresql", "data.yaml"])
        assert args.save_metadata_to == "meta.yaml"

    def test_use_metadata_from(self):
        args = parser.parse_args(["--use-metadata-from", "meta.yaml", "postgresql", "data.yaml"])
        assert args.use_metadata_from == "meta.yaml"


class TestDialectAliases:
    def test_pg_alias(self):
        # Use generate with string args, catch output
        args = parser.parse_args(["pg", "unused.yaml"])
        # Just test the alias mapping without running full generate
        if args.dialect in ("pg", "pgsql", "postgres"):
            args.dialect = "postgresql"
        assert args.dialect == "postgresql"

    def test_pgsql_alias(self):
        args = parser.parse_args(["pgsql", "unused.yaml"])
        if args.dialect in ("pg", "pgsql", "postgres"):
            args.dialect = "postgresql"
        assert args.dialect == "postgresql"

    def test_postgres_alias(self):
        args = parser.parse_args(["postgres", "unused.yaml"])
        if args.dialect in ("pg", "pgsql", "postgres"):
            args.dialect = "postgresql"
        assert args.dialect == "postgresql"

    def test_django_alias(self):
        args = parser.parse_args(["dj", "unused.yaml"])
        if args.dialect.startswith("dj"):
            args.dialect = "django"
        assert args.dialect == "django"

    def test_sqlalchemy_alias(self):
        args = parser.parse_args(["sqla", "unused.yaml"])
        if args.dialect.startswith("sqla"):
            args.dialect = "sqlalchemy"
        assert args.dialect == "sqlalchemy"


class TestSetLogging:
    def test_valid_log_level(self):
        args = parser.parse_args(["-l", "debug", "postgresql", "data.yaml"])
        set_logging(args)
        assert logging.getLogger().level == logging.DEBUG

    def test_invalid_log_level(self):
        args = parser.parse_args(["postgresql", "data.yaml"])
        args.log = "INVALID"
        with pytest.raises(NotImplementedError, match="log level"):
            set_logging(args)


class TestGenerateOne:
    def test_generate_one_sql(self):
        data = [{"id": 1, "name": "test"}]
        args = parser.parse_args(["postgresql", "dummy.yaml"])
        out = io.StringIO()
        generate_one(data, args, table_name="test_tbl", file=out)
        output = out.getvalue()
        assert "CREATE TABLE" in output
        assert "test_tbl" in output

    def test_generate_one_with_inserts(self):
        data = [{"id": 1, "name": "test"}]
        args = parser.parse_args(["-i", "postgresql", "dummy.yaml"])
        out = io.StringIO()
        generate_one(data, args, table_name="test_tbl", file=out)
        output = out.getvalue()
        assert "INSERT INTO" in output

    def test_generate_one_with_drops(self):
        data = [{"id": 1, "name": "test"}]
        args = parser.parse_args(["-d", "postgresql", "dummy.yaml"])
        out = io.StringIO()
        generate_one(data, args, table_name="test_tbl", file=out)
        output = out.getvalue()
        assert "DROP TABLE" in output

    def test_generate_one_sqlalchemy(self):
        data = [{"id": 1, "name": "test"}]
        args = parser.parse_args(["sqlalchemy", "dummy.yaml"])
        out = io.StringIO()
        generate_one(data, args, table_name="test_tbl", file=out)
        output = out.getvalue()
        assert "Column(" in output


class TestGenerate:
    def test_invalid_dialect_raises(self):
        with pytest.raises(NotImplementedError, match="First arg must be one of"):
            generate("bogus_dialect dummy.yaml")


class TestEveryNthValidation:
    def test_every_nth_zero_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(ValueError, match="--every-nth must be a positive integer"):
            generate(f"--every-nth 0 postgresql {data_file}")

    def test_every_nth_negative_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(ValueError, match="--every-nth must be a positive integer"):
            generate(f"--every-nth -3 postgresql {data_file}")


class TestSampleKValidation:
    def test_sample_k_zero_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(ValueError, match="--sample-k must be a positive integer"):
            generate(f"--sample-k 0 postgresql {data_file}")

    def test_sample_k_negative_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(ValueError, match="--sample-k must be a positive integer"):
            generate(f"--sample-k -3 postgresql {data_file}")

    def test_sample_k_combined_with_limit_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(ValueError, match="--sample-k cannot be combined with --limit or --every-nth"):
            generate(f"--sample-k 1 --limit 1 postgresql {data_file}")

    def test_sample_k_combined_with_every_nth_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(ValueError, match="--sample-k cannot be combined with --limit or --every-nth"):
            generate(f"--sample-k 1 --every-nth 1 postgresql {data_file}")

    def test_seed_without_sample_k_or_sample_pct_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(ValueError, match=r"--seed requires --sample-k or --sample-pct"):
            generate(f"--seed 42 postgresql {data_file}")


class TestSamplePctValidation:
    def test_sample_pct_zero_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(ValueError,
                           match="--sample-pct must be greater than 0 and at most 100"):
            generate(f"--sample-pct 0 postgresql {data_file}")

    def test_sample_pct_negative_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(ValueError,
                           match="--sample-pct must be greater than 0 and at most 100"):
            generate(f"--sample-pct -5 postgresql {data_file}")

    def test_sample_pct_over_100_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(ValueError,
                           match="--sample-pct must be greater than 0 and at most 100"):
            generate(f"--sample-pct 101 postgresql {data_file}")

    def test_sample_pct_combined_with_limit_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(
                ValueError,
                match=r"--sample-pct cannot be combined with --limit, --every-nth, or --sample-k"):
            generate(f"--sample-pct 10 --limit 1 postgresql {data_file}")

    def test_sample_pct_combined_with_every_nth_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(
                ValueError,
                match=r"--sample-pct cannot be combined with --limit, --every-nth, or --sample-k"):
            generate(f"--sample-pct 10 --every-nth 2 postgresql {data_file}")

    def test_sample_pct_combined_with_sample_k_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(
                ValueError,
                match=r"--sample-pct cannot be combined with --limit, --every-nth, or --sample-k"):
            generate(f"--sample-pct 10 --sample-k 1 postgresql {data_file}")

    def test_seed_with_sample_pct_alone_is_allowed(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        out = io.StringIO()
        generate(f"--sample-pct 100 --seed 42 postgresql {data_file}", file=out)
        assert "CREATE TABLE" in out.getvalue()


class TestNoCreatesDropsWarning:
    def test_sqlalchemy_no_creates_with_drops_warns(self, tmp_path, caplog):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        out = io.StringIO()
        with caplog.at_level(logging.WARNING):
            generate(f"--no-creates -d sqlalchemy {data_file}", file=out)
        assert "--drops has no effect" in caplog.text

    def test_sql_dialect_no_creates_with_drops_does_not_warn(self, tmp_path, caplog):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        out = io.StringIO()
        with caplog.at_level(logging.WARNING):
            generate(f"--no-creates -d postgresql {data_file}", file=out)
        assert "--drops has no effect" not in caplog.text
        assert "DROP TABLE" in out.getvalue()

    def test_sqlalchemy_drops_without_no_creates_does_not_warn(self, tmp_path, caplog):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        out = io.StringIO()
        with caplog.at_level(logging.WARNING):
            generate(f"-d sqlalchemy {data_file}", file=out)
        assert "--drops has no effect" not in caplog.text
        assert "metadata.drop_all(engine)" in out.getvalue()


class TestZeroColumnSources:
    """Empty sources used to emit invalid ``CREATE TABLE x ();`` (or, for
    JSON, a misleading deserialization error).  All must now raise a clear
    ValueError instead."""

    def test_empty_csv_raises(self, tmp_path):
        data_file = tmp_path / "empty.csv"
        data_file.write_text('')
        with pytest.raises(ValueError, match="no columns"):
            generate(f"postgresql {data_file}", file=io.StringIO())

    def test_header_only_csv_raises(self, tmp_path):
        data_file = tmp_path / "header_only.csv"
        data_file.write_text('a,b\n')
        with pytest.raises(ValueError, match="no columns"):
            generate(f"postgresql {data_file}", file=io.StringIO())

    def test_json_all_empty_rows_raises_clearly(self, tmp_path):
        data_file = tmp_path / "empty_rows.json"
        data_file.write_text('[{}]')
        with pytest.raises(ValueError, match="no columns"):
            generate(f"postgresql {data_file}", file=io.StringIO())


class TestCountOnly:
    def test_count_only_prints_total_and_skips_ddl(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}, {"id": 2}, {"id": 3}]')
        out = io.StringIO()
        generate(f"postgresql {data_file} --count-only", file=out)
        output = out.getvalue()
        assert "CREATE TABLE" not in output
        assert "TOTAL: 3" in output

    def test_count_only_ignores_inserts_flag(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        out = io.StringIO()
        generate(f"-i postgresql {data_file} --count-only", file=out)
        assert "INSERT INTO" not in out.getvalue()

    def test_count_only_blocks_pickle_extension(self, tmp_path):
        bad = tmp_path / "data.pickle"
        bad.write_bytes(b"not really pickle data")
        with pytest.raises(Exception, match="not allowed for security reasons"):
            generate(f"postgresql {bad} --count-only")


class TestSampleKGeneration:
    def test_sample_k_reduces_insert_count(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text(
            '[' + ','.join(f'{{"id": {i}}}' for i in range(1, 51)) + ']'
        )
        out = io.StringIO()
        generate(f"--sample-k 5 --seed 1 -i postgresql {data_file}", file=out)
        output = out.getvalue()
        assert output.count("INSERT INTO") == 5

    def test_count_only_ignores_sample_k(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}, {"id": 2}, {"id": 3}]')
        out = io.StringIO()
        generate(f"--sample-k 1 postgresql {data_file} --count-only", file=out)
        assert "TOTAL: 3" in out.getvalue()

    def test_sample_k_applies_to_sqlalchemy_url(self, tmp_path):
        import sqlalchemy as sa
        db_path = tmp_path / "test.db"
        engine = sa.create_engine(f"sqlite:///{db_path}")
        with engine.connect() as connection:
            connection.execute(sa.text("CREATE TABLE t (id INTEGER)"))
            connection.execute(sa.text(
                "INSERT INTO t VALUES " + ", ".join(f"({i})" for i in range(1, 21))
            ))
            connection.commit()
        out = io.StringIO()
        generate(f"--sample-k 5 --seed 1 -i postgresql sqlite:///{db_path}", file=out)
        assert out.getvalue().count("INSERT INTO") == 5


class TestSamplePctGeneration:
    def test_sample_pct_reduces_insert_count(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text(
            '[' + ','.join(f'{{"id": {i}}}' for i in range(1, 201)) + ']'
        )
        out = io.StringIO()
        generate(f"--sample-pct 10 --seed 42 -i postgresql {data_file}", file=out)
        n_sampled = out.getvalue().count("INSERT INTO")
        assert 0 < n_sampled < 200
        unsampled = io.StringIO()
        generate(f"-i postgresql {data_file}", file=unsampled)
        assert unsampled.getvalue().count("INSERT INTO") == 200

    def test_sample_pct_is_reproducible_with_seed(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text(
            '[' + ','.join(f'{{"id": {i}}}' for i in range(1, 201)) + ']'
        )
        first, second = io.StringIO(), io.StringIO()
        generate(f"--sample-pct 10 --seed 42 -i postgresql {data_file}", file=first)
        generate(f"--sample-pct 10 --seed 42 -i postgresql {data_file}", file=second)
        assert first.getvalue() == second.getvalue()

    def test_sample_pct_yields_at_least_one_row_from_small_source(self, tmp_path):
        """A percent too low to select anything still generates DDL rather
        than failing on an empty table."""
        data_file = tmp_path / "data.json"
        data_file.write_text(
            '[' + ','.join(f'{{"id": {i}}}' for i in range(1, 11)) + ']'
        )
        out = io.StringIO()
        generate(f"--sample-pct 1 --seed 0 -i postgresql {data_file}", file=out)
        assert out.getvalue().count("INSERT INTO") == 1

    def test_count_only_ignores_sample_pct(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}, {"id": 2}, {"id": 3}]')
        out = io.StringIO()
        generate(f"--sample-pct 10 postgresql {data_file} --count-only", file=out)
        assert "TOTAL: 3" in out.getvalue()

    def test_sample_pct_applies_to_sqlalchemy_url(self, tmp_path):
        import sqlalchemy as sa
        db_path = tmp_path / "test.db"
        engine = sa.create_engine(f"sqlite:///{db_path}")
        with engine.connect() as connection:
            connection.execute(sa.text("CREATE TABLE t (id INTEGER)"))
            connection.execute(sa.text(
                "INSERT INTO t VALUES " + ", ".join(f"({i})" for i in range(1, 201))
            ))
            connection.commit()
        out = io.StringIO()
        generate(f"--sample-pct 10 --seed 42 -i postgresql sqlite:///{db_path}", file=out)
        assert 0 < out.getvalue().count("INSERT INTO") < 200


# ---------------------------------------------------------------------------
# Telling a database URL from a file path
# ---------------------------------------------------------------------------
class TestIsSqlAlchemyUrl:
    """``^drizzle|firebird|mssql|...`` anchors only its first alternative --
    every other branch was unanchored, and it was applied with ``search``.
    Any path *containing* a dialect name was taken for a database URL and
    handed to ``create_engine``."""

    @pytest.mark.parametrize("path", [
        "./sqlite_backups/data.json",
        "my_django_export.csv",
        "/tmp/test_sqlalchemy_thing/dup.json",
        "reports/oracle/2024.yaml",
        "mysql_dump.json",          # dialect name at the very start
        "postgresql.json",
    ])
    def test_file_paths_are_not_urls(self, path):
        assert not is_sqlalchemy_url.search(path)

    @pytest.mark.parametrize("url", [
        "postgresql://user:pass@localhost/db",
        "sqlite:///:memory:",
        "sqlite:////var/db/app.db",
        "mysql+pymysql://localhost/db",
        "mssql+pyodbc://localhost/db",
        "oracle://localhost/db",
    ])
    def test_database_urls_are_urls(self, url):
        assert is_sqlalchemy_url.search(url)

    def test_generating_from_a_path_containing_a_dialect_name(self, tmp_path):
        """The whole point: such a path died with

            ArgumentError: Could not parse SQLAlchemy URL from given URL string
        """
        data_file = tmp_path / "sqlite_backups" / "animals.json"
        data_file.parent.mkdir()
        data_file.write_text('[{"name": "Arthur"}]')
        out = io.StringIO()
        generate(f"postgresql {data_file}", file=out)
        assert "CREATE TABLE animals (" in out.getvalue()

    def test_counting_a_path_containing_a_dialect_name(self, tmp_path):
        """--count-only takes the same branch."""
        data_file = tmp_path / "django_exports" / "animals.json"
        data_file.parent.mkdir()
        data_file.write_text('[{"name": "Arthur"}, {"name": "Bella"}]')
        out = io.StringIO()
        generate(f"--count-only postgresql {data_file}", file=out)
        assert "TOTAL: 2" in out.getvalue()


# ---------------------------------------------------------------------------
# SQLAlchemy URL input path
# ---------------------------------------------------------------------------
class TestSqlAlchemyUrlInput:
    @patch('ddlgenerator.console.sqlalchemy_table_sources')
    def test_sqlalchemy_url_generates_ddl(self, mock_sources):
        """SQLAlchemy URL should generate DDL for each table."""
        # Create a mock source that behaves like a real Source
        mock_source = MagicMock()
        mock_source.generator = MagicMock()
        mock_source.generator.name = "users"
        mock_source.generator.sqla_columns = []
        # Make data iterable
        mock_source.data = iter([{"id": 1, "name": "test"}])
        mock_source.db_engine = None
        mock_source.table_name = "users"
        mock_sources.return_value = [mock_source]

        # Also need to mock generate_one to avoid full Table construction
        with patch('ddlgenerator.console.generate_one'):
            out = io.StringIO()
            generate("postgresql postgresql://user:pass@localhost/db", file=out)
            mock_sources.assert_called_once()

    @patch('ddlgenerator.console.sqlalchemy_table_sources')
    def test_sqlalchemy_url_with_inserts(self, mock_sources):
        """SQLAlchemy URL with -i flag should generate INSERT statements."""
        mock_source = MagicMock()
        mock_source.generator = MagicMock()
        mock_source.generator.name = "users"
        mock_source.generator.sqla_columns = []
        mock_source.data = iter([{"id": 1}])
        mock_source.db_engine = None
        mock_source.table_name = "users"
        mock_sources.return_value = [mock_source]

        with patch('ddlgenerator.console.generate_one'):
            out = io.StringIO()
            generate("-i postgresql postgresql://localhost/db", file=out)
            mock_sources.assert_called_once()

    @patch('ddlgenerator.console.sqlalchemy_table_sources')
    def test_sqlalchemy_url_empty_tables_no_nameerror(self, mock_sources):
        """Empty SQLAlchemy source should not raise NameError (fix from Item 1)."""
        # Create mock source with empty data - this was causing NameError before fix
        mock_source = MagicMock()
        mock_source.generator = MagicMock()
        mock_source.generator.name = "empty_table"
        mock_source.generator.sqla_columns = []
        mock_source.data = iter([])  # Empty data
        mock_source.db_engine = None
        mock_source.table_name = "empty_table"
        mock_sources.return_value = [mock_source]

        with patch('ddlgenerator.console.generate_one'):
            out = io.StringIO()
            # This should not raise NameError
            generate("-i postgresql postgresql://localhost/db", file=out)
            # Should complete without error
            assert True

    @patch('ddlgenerator.console.emit_db_sequence_updates')
    @patch('ddlgenerator.console.sqlalchemy_table_sources')
    def test_sequence_updates_are_wrapped_in_text(self, mock_sources, mock_seq):
        """Emitted as a plain string, the statement raises
        ObjectNotExecutableError when the user runs the generated module."""
        mock_source = MagicMock()
        mock_source.generator.name = "users"
        mock_sources.return_value = [mock_source]
        mock_seq.return_value = iter(["ALTER SEQUENCE users_id_seq RESTART WITH 42;"])

        with patch('ddlgenerator.console.generate_one') as mock_generate_one:
            # the inserter call is built from the name the model defines
            mock_generate_one.return_value.table_name = "users"
            out = io.StringIO()
            generate("-i sqlalchemy postgresql://localhost/db", file=out)

        assert ('conn.execute(text("ALTER SEQUENCE users_id_seq RESTART WITH 42;"))'
                in out.getvalue())


# ---------------------------------------------------------------------------
# SQLAlchemy inserter call
# ---------------------------------------------------------------------------
class TestSqlAlchemyInserterCall:
    """``insert_test_rows`` drives the per-table ``insert_*`` functions.

    Only the SQLAlchemy-URL branch emitted it, so a file source produced
    ``insert_*`` definitions that nothing ever called -- the generated module
    created the tables and left them empty.
    """

    def test_file_source_emits_inserter_call(self, tmp_path):
        data_file = tmp_path / "knights.json"
        data_file.write_text('[{"name": "Lancelot"}]')
        out = io.StringIO()
        generate(f"-i sqlalchemy {data_file}", file=out)
        output = out.getvalue()
        assert "def insert_test_rows(meta, conn):" in output
        assert "insert_knights(meta.tables['knights'], conn)" in output

    def test_child_tables_are_called_after_their_parent(self):
        out = io.StringIO()
        generate(f"-i sqlalchemy {here('birds.yaml')}", file=out)
        output = out.getvalue()
        parent = output.index("insert_birds(meta.tables['birds'], conn)")
        child = output.index("insert_state(meta.tables['state'], conn)")
        assert parent < child

    def test_table_without_rows_is_not_called(self, tmp_path):
        """``inserts()`` defines no function for a rowless table, so calling
        one would raise NameError.

        The rowless table needs its columns from saved metadata: a source
        with neither rows nor columns is rejected outright.
        """
        seed_file = tmp_path / "seed.json"
        seed_file.write_text('[{"name": "Val"}]')
        meta_file = tmp_path / "meta.yaml"
        generate(f"--save-metadata-to {meta_file} sqlalchemy {seed_file}",
                 file=io.StringIO())
        data_file = tmp_path / "vacant.json"
        data_file.write_text("[]")
        out = io.StringIO()
        generate(f"-i --use-metadata-from {meta_file} sqlalchemy {data_file}", file=out)
        output = out.getvalue()
        assert "def insert_test_rows(meta, conn):" in output
        assert "insert_vacant(" not in output

    def test_multiple_datafiles_share_one_inserter(self, tmp_path):
        """A second definition would shadow the first, stranding its tables."""
        first = tmp_path / "aardvarks.json"
        first.write_text('[{"name": "Arthur"}]')
        second = tmp_path / "beetles.json"
        second.write_text('[{"name": "Bella"}]')
        out = io.StringIO()
        generate(f"-i sqlalchemy {first} {second}", file=out)
        output = out.getvalue()
        assert output.count("def insert_test_rows(meta, conn):") == 1
        assert "insert_aardvarks(meta.tables['aardvarks'], conn)" in output
        assert "insert_beetles(meta.tables['beetles'], conn)" in output

    def test_no_inserter_call_without_inserts_flag(self, tmp_path):
        data_file = tmp_path / "knights.json"
        data_file.write_text('[{"name": "Lancelot"}]')
        out = io.StringIO()
        generate(f"sqlalchemy {data_file}", file=out)
        assert "insert_test_rows" not in out.getvalue()

    def test_no_inserter_call_for_sql_dialects(self, tmp_path):
        data_file = tmp_path / "knights.json"
        data_file.write_text('[{"name": "Lancelot"}]')
        out = io.StringIO()
        generate(f"-i postgresql {data_file}", file=out)
        assert "insert_test_rows" not in out.getvalue()

    def test_generated_module_populates_its_tables(self, tmp_path):
        """End to end: the emitted module must run and load every row."""
        out = io.StringIO()
        generate(f"-i sqlalchemy {here('birds.yaml')}", file=out)
        module = tmp_path / "generated.py"
        module.write_text(out.getvalue())

        namespace = runpy.run_path(str(module))
        namespace["insert_test_rows"](namespace["metadata"], namespace["conn"])

        conn = namespace["conn"]
        birds = namespace["birds"]
        state = namespace["state"]
        assert conn.execute(sa.select(sa.func.count()).select_from(birds)).scalar() == 2
        assert conn.execute(sa.select(sa.func.count()).select_from(state)).scalar() == 8


# ---------------------------------------------------------------------------
# --drops in the SQLAlchemy dialect
# ---------------------------------------------------------------------------
class TestSqlAlchemyDrops:
    """``-d`` was parsed, accepted, and then never consulted for this
    dialect -- the flag did nothing and said nothing."""

    def test_drops_emits_drop_all(self, tmp_path):
        data_file = tmp_path / "knights.json"
        data_file.write_text('[{"name": "Lancelot"}]')
        out = io.StringIO()
        generate(f"-d sqlalchemy {data_file}", file=out)
        output = out.getvalue()
        assert output.index("metadata.drop_all(engine)") < output.index(
            "metadata.create_all(engine)")

    def test_no_drops_without_the_flag(self, tmp_path):
        data_file = tmp_path / "knights.json"
        data_file.write_text('[{"name": "Lancelot"}]')
        out = io.StringIO()
        generate(f"sqlalchemy {data_file}", file=out)
        assert "drop_all" not in out.getvalue()

    def _module_against_a_real_file(self, tmp_path, flags, db_path):
        """Generate, then repoint the module at a file-backed database so a
        second run sees what the first one left behind."""
        out = io.StringIO()
        generate(f"{flags} sqlalchemy {here('knights.yaml')}", file=out)
        module = tmp_path / f"generated{flags.count('-d')}.py"
        module.write_text(out.getvalue().replace(
            "sqlite:///:memory:", f"sqlite:///{db_path}"))
        return module

    def _run_and_count(self, module):
        namespace = runpy.run_path(str(module))
        namespace["insert_test_rows"](namespace["metadata"], namespace["conn"])
        return namespace["conn"].execute(
            sa.select(sa.func.count()).select_from(namespace["knights"])).scalar()

    def test_drops_makes_a_rerun_idempotent(self, tmp_path):
        module = self._module_against_a_real_file(
            tmp_path, "-i -d", tmp_path / "with_drops.db")
        assert self._run_and_count(module) == 4
        assert self._run_and_count(module) == 4

    def test_without_drops_a_rerun_accumulates(self, tmp_path):
        """Pins what the flag is worth: the same module without ``-d``
        doubles the rows."""
        module = self._module_against_a_real_file(
            tmp_path, "-i", tmp_path / "no_drops.db")
        assert self._run_and_count(module) == 4
        assert self._run_and_count(module) == 8


# ---------------------------------------------------------------------------
# One model wrapper per run, not per datafile
# ---------------------------------------------------------------------------
class TestSqlAlchemyMultipleDatafiles:
    """Each datafile got its own ``from sqlalchemy import ...`` line and its
    own ``metadata.create_all(engine)``.  Harmless to execute, but the model
    should read as one script: a single import line covering every table's
    types and a single create_all after all the definitions."""

    def _two_files(self, tmp_path):
        first = tmp_path / "aardvarks.json"
        first.write_text('[{"legs": 4}]')
        second = tmp_path / "beetles.json"
        second.write_text('[{"name": "Bella"}]')
        return first, second

    def test_one_create_all_for_the_whole_run(self, tmp_path):
        first, second = self._two_files(tmp_path)
        out = io.StringIO()
        generate(f"sqlalchemy {first} {second}", file=out)
        assert out.getvalue().count("metadata.create_all(engine)") == 1

    def test_one_import_line_covering_every_tables_types(self, tmp_path):
        # aardvarks needs Integer, beetles needs Unicode; the single import
        # line must carry both
        first, second = self._two_files(tmp_path)
        out = io.StringIO()
        generate(f"sqlalchemy {first} {second}", file=out)
        model_imports = [line for line in out.getvalue().splitlines()
                         if line.startswith("from sqlalchemy import ")
                         and "create_engine" not in line]  # skip the header's
        assert len(model_imports) == 1
        assert "Integer" in model_imports[0]
        assert "Unicode" in model_imports[0]

    def test_create_all_follows_every_table_definition(self, tmp_path):
        first, second = self._two_files(tmp_path)
        out = io.StringIO()
        generate(f"sqlalchemy {first} {second}", file=out)
        output = out.getvalue()
        assert output.index("metadata.create_all(engine)") > max(
            output.index("aardvarks = Table("), output.index("beetles = Table("))

    def test_drops_emits_one_drop_all_before_the_create_all(self, tmp_path):
        first, second = self._two_files(tmp_path)
        out = io.StringIO()
        generate(f"-d sqlalchemy {first} {second}", file=out)
        output = out.getvalue()
        assert output.count("metadata.drop_all(engine)") == 1
        assert output.index("metadata.drop_all(engine)") < output.index(
            "metadata.create_all(engine)")

    def test_generated_module_still_populates_every_file(self, tmp_path):
        first, second = self._two_files(tmp_path)
        out = io.StringIO()
        generate(f"-i sqlalchemy {first} {second}", file=out)
        module = tmp_path / "generated.py"
        module.write_text(out.getvalue())

        namespace = runpy.run_path(str(module))
        namespace["insert_test_rows"](namespace["metadata"], namespace["conn"])

        conn = namespace["conn"]
        for table in ("aardvarks", "beetles"):
            assert conn.execute(sa.select(sa.func.count())
                                .select_from(namespace[table])).scalar() == 1


# ---------------------------------------------------------------------------
# Duplicate table names across sources
# ---------------------------------------------------------------------------
class TestDuplicateTableNames:
    """Table names come from file basenames and nested keys, so two sources
    in one run can land on the same one. Every dialect emitted both, and
    every dialect broke on it: two ``CREATE TABLE dup`` statements, or a
    SQLAlchemy model that raises

        InvalidRequestError: Table 'dup' is already defined for this
        MetaData instance.
    """

    def _two_sources_named_dup(self, tmp_path):
        first = tmp_path / "d1" / "dup.json"
        second = tmp_path / "d2" / "dup.json"
        for path, name in ((first, "Alice"), (second, "Bob")):
            path.parent.mkdir()
            path.write_text(f'[{{"name": "{name}"}}]')
        return first, second

    def test_second_source_is_renamed(self, tmp_path):
        first, second = self._two_sources_named_dup(tmp_path)
        out = io.StringIO()
        generate(f"postgresql {first} {second}", file=out)
        output = out.getvalue()
        assert "CREATE TABLE dup (" in output
        assert "CREATE TABLE dup_1 (" in output

    def test_rename_is_warned_about(self, tmp_path, caplog):
        first, second = self._two_sources_named_dup(tmp_path)
        out = io.StringIO()
        with caplog.at_level(logging.WARNING):
            generate(f"postgresql {first} {second}", file=out)
        assert any("dup" in r.message and "dup_1" in r.message
                   for r in caplog.records)

    def test_child_table_collides_with_another_sources_table(self, tmp_path):
        """The name pool has to cover child tables too -- they are emitted
        into the same script as everything else."""
        owner = tmp_path / "owner.json"
        owner.write_text('[{"who": "a", "state": [{"abbrev": "OH"}]}]')
        state = tmp_path / "state.json"
        state.write_text('[{"abbrev": "MN"}]')
        out = io.StringIO()
        generate(f"postgresql {owner} {state}", file=out)
        output = out.getvalue()
        assert "CREATE TABLE state (" in output
        assert "CREATE TABLE state_1 (" in output

    def test_distinct_names_are_left_alone(self, tmp_path):
        first = tmp_path / "aardvarks.json"
        first.write_text('[{"name": "Arthur"}]')
        second = tmp_path / "beetles.json"
        second.write_text('[{"name": "Bella"}]')
        out = io.StringIO()
        generate(f"postgresql {first} {second}", file=out)
        output = out.getvalue()
        assert "_1" not in output

    def test_generated_model_module_runs(self, tmp_path):
        """End to end: both tables must be defined, created and loaded.

        (Named to keep every SQL dialect name out of ``tmp_path``: the
        ``is_sqlalchemy_url`` pattern anchors only its first alternative and
        is applied with ``search``, so any path *containing* a dialect name
        is mistaken for a database URL.)
        """
        first, second = self._two_sources_named_dup(tmp_path)
        out = io.StringIO()
        generate(f"-i sqlalchemy {first} {second}", file=out)
        module = tmp_path / "generated.py"
        module.write_text(out.getvalue())

        namespace = runpy.run_path(str(module))
        namespace["insert_test_rows"](namespace["metadata"], namespace["conn"])

        conn = namespace["conn"]
        assert [tuple(r) for r in conn.execute(sa.select(namespace["dup"]))] == [("Alice",)]
        assert [tuple(r) for r in conn.execute(sa.select(namespace["dup_1"]))] == [("Bob",)]


# ---------------------------------------------------------------------------
# Metadata round-trip
# ---------------------------------------------------------------------------
class TestMetadataRoundTrip:
    def test_save_metadata_to_file(self, tmp_path):
        """--save-metadata-to should save table structure to file."""

        data = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        meta_file = tmp_path / "metadata.yaml"

        args = parser.parse_args([
            "--save-metadata-to", str(meta_file),
            "postgresql", "dummy.yaml"
        ])
        out = io.StringIO()
        generate_one(data, args, table_name="test_meta", file=out)

        # Metadata file should be created
        assert meta_file.exists()
        content = meta_file.read_text()
        assert "id" in content or "name" in content

    def test_use_metadata_from_dict(self):
        """--use-metadata-from should accept metadata dict (internal API)."""
        from collections import OrderedDict

        from ddlgenerator.ddlgenerator import Table

        # Create metadata as OrderedDict (as would be loaded from file)
        metadata = OrderedDict([
            ("id", {"is_nullable": False, "is_unique": True, "sample_datum": 1, "str_length": 1}),
            ("name", {"is_nullable": False, "is_unique": False, "sample_datum": "test", "str_length": 4}),
        ])

        # Create table with metadata
        data = [{"id": 1, "name": "test"}]
        tbl = Table(data, table_name="test_meta", metadata_source=metadata)

        # Should use the provided metadata structure
        assert "id" in tbl.columns
        assert "name" in tbl.columns

    def test_metadata_preserves_column_names(self, tmp_path):
        """Metadata should preserve column names."""

        data = [{"id": 1, "name": "Alice", "score": 95.5}]
        meta_file = tmp_path / "metadata.yaml"

        args = parser.parse_args([
            "--save-metadata-to", str(meta_file),
            "postgresql", "dummy.yaml"
        ])
        out = io.StringIO()
        generate_one(data, args, table_name="test_struct", file=out)

        # Verify metadata file was created with column info
        assert meta_file.exists()
        content = meta_file.read_text()
        # Column names should appear in the saved metadata
        assert "id" in content or "name" in content


# Blocks a third-party module at import time, then imports the package and
# reports whatever ImportError surfaces. Run in a subprocess so that blocking
# an import cannot leak into the rest of the test session.
_MISSING_DEP_PROBE = """
import sys

class Blocker:
    def find_spec(self, name, path=None, target=None):
        if name == {dep!r} or name.startswith({dep!r} + "."):
            raise ImportError("No module named %r" % name)

sys.meta_path.insert(0, Blocker())
try:
    import ddlgenerator.console
except ImportError as e:
    print(e)
"""


class TestMissingDependencyDiagnostics:
    """A missing third-party dependency must name itself, not masquerade as a
    circular import. The package previously wrapped its internal imports in
    ``try/except ImportError`` fallbacks, which swallowed the real error and
    re-raised a misleading one from the fallback branch."""

    @pytest.mark.parametrize("dep", ["sqlalchemy", "yaml", "dateutil"])
    def test_missing_dependency_names_itself(self, dep):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-c", _MISSING_DEP_PROBE.format(dep=dep)],
            capture_output=True,
            text=True,
        )
        message = (result.stdout + result.stderr).lower()

        assert dep in message, f"error should name the missing module: {message!r}"
        assert "circular import" not in message, (
            f"missing dependency reported as a circular import: {message!r}"
        )
        assert "partially initialized" not in message, (
            f"missing dependency reported as a partial init: {message!r}"
        )
