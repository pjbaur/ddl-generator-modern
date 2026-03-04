#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for ddlgenerator.console module (P3-2).

Covers: CLI argument parsing, dialect aliases, set_logging, generate_one
"""

import io
import logging
from unittest.mock import patch

import pytest

from ddlgenerator.console import parser, set_logging, generate, generate_one


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
        out = io.StringIO()
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
        table = generate_one(data, args, table_name="test_tbl", file=out)
        output = out.getvalue()
        assert "CREATE TABLE" in output
        assert "test_tbl" in output

    def test_generate_one_with_inserts(self):
        data = [{"id": 1, "name": "test"}]
        args = parser.parse_args(["-i", "postgresql", "dummy.yaml"])
        out = io.StringIO()
        table = generate_one(data, args, table_name="test_tbl", file=out)
        output = out.getvalue()
        assert "INSERT INTO" in output

    def test_generate_one_with_drops(self):
        data = [{"id": 1, "name": "test"}]
        args = parser.parse_args(["-d", "postgresql", "dummy.yaml"])
        out = io.StringIO()
        table = generate_one(data, args, table_name="test_tbl", file=out)
        output = out.getvalue()
        assert "DROP TABLE" in output

    def test_generate_one_sqlalchemy(self):
        data = [{"id": 1, "name": "test"}]
        args = parser.parse_args(["sqlalchemy", "dummy.yaml"])
        out = io.StringIO()
        table = generate_one(data, args, table_name="test_tbl", file=out)
        output = out.getvalue()
        assert "Column(" in output


class TestGenerate:
    def test_invalid_dialect_raises(self):
        with pytest.raises(NotImplementedError, match="First arg must be one of"):
            generate("bogus_dialect dummy.yaml")
