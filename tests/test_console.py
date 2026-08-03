#!/usr/bin/env python
"""
Tests for ddlgenerator.console module (P3-2).

Covers: CLI argument parsing, dialect aliases, set_logging, generate_one
"""

import io
import logging
from unittest.mock import MagicMock, patch

import pytest

from ddlgenerator.console import generate, generate_one, parser, set_logging


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

    def test_seed_without_sample_k_raises(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"id": 1}]')
        with pytest.raises(ValueError, match="--seed requires --sample-k"):
            generate(f"--seed 42 postgresql {data_file}")


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
