#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for ddlgenerator.typehelpers module (P3-2).

Covers: coerce_to_specific, precision_and_scale, best_representative,
        is_scalar, worst_decimal, set_worst, best_coercable, sqla_datatype_for
"""

import datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa

from ddlgenerator.typehelpers import (
    coerce_to_specific,
    precision_and_scale,
    best_representative,
    is_scalar,
    worst_decimal,
    set_worst,
    best_coercable,
    sqla_datatype_for,
    _places_b4_and_after_decimal,
)


# ---------------------------------------------------------------------------
# is_scalar
# ---------------------------------------------------------------------------
class TestIsScalar:
    def test_string_is_scalar(self):
        assert is_scalar("hello") is True

    def test_int_is_scalar(self):
        assert is_scalar(42) is True

    def test_float_is_scalar(self):
        assert is_scalar(3.14) is True

    def test_none_is_scalar(self):
        assert is_scalar(None) is True

    def test_list_is_not_scalar(self):
        assert is_scalar([1, 2]) is False

    def test_dict_is_not_scalar(self):
        assert is_scalar({"a": 1}) is False

    def test_tuple_is_not_scalar(self):
        assert is_scalar((1, 2)) is False

    def test_bool_is_scalar(self):
        assert is_scalar(True) is True

    def test_decimal_is_scalar(self):
        assert is_scalar(Decimal("3.14")) is True


# ---------------------------------------------------------------------------
# precision_and_scale
# ---------------------------------------------------------------------------
class TestPrecisionAndScale:
    def test_float_with_fraction(self):
        assert precision_and_scale(54.2) == (3, 1)

    def test_integer_value(self):
        assert precision_and_scale(9) == (1, 0)

    def test_zero(self):
        (p, s) = precision_and_scale(0)
        assert s == 0

    def test_decimal_with_fraction(self):
        assert precision_and_scale(Decimal("54.212")) == (5, 3)

    def test_decimal_integer(self):
        assert precision_and_scale(Decimal("100")) == (3, 0)

    def test_negative_decimal_exponent(self):
        # Decimal('1E+2') has exponent=2, digits=(1,)
        assert precision_and_scale(Decimal("1E+2")) == (3, 0)

    def test_large_integer(self):
        (p, s) = precision_and_scale(99999999999999)
        assert p == 14
        assert s == 0

    def test_very_large_integer(self):
        (p, s) = precision_and_scale(999999999999999)
        assert p >= 14
        assert s == 0


# ---------------------------------------------------------------------------
# _places_b4_and_after_decimal
# ---------------------------------------------------------------------------
class TestPlacesB4AndAfterDecimal:
    def test_basic(self):
        assert _places_b4_and_after_decimal(Decimal("54.212")) == (2, 3)

    def test_integer(self):
        assert _places_b4_and_after_decimal(Decimal("100")) == (3, 0)

    def test_fractional_only(self):
        assert _places_b4_and_after_decimal(Decimal("0.5")) == (0, 1)


# ---------------------------------------------------------------------------
# coerce_to_specific
# ---------------------------------------------------------------------------
class TestCoerceToSpecific:
    def test_none_returns_none(self):
        assert coerce_to_specific(None) is None

    def test_date_string(self):
        result = coerce_to_specific("Jan 17 2012")
        assert isinstance(result, datetime.datetime)
        assert result.year == 2012
        assert result.month == 1
        assert result.day == 17

    def test_date_compact(self):
        result = coerce_to_specific("20141010")
        assert isinstance(result, datetime.datetime)
        assert result.year == 2014

    def test_boolean_false_variants(self):
        for val in ("0", "false", "f", "n", "no", "False", "NO"):
            assert coerce_to_specific(val) is False, f"Failed for {val}"

    def test_boolean_true_variants(self):
        for val in ("1", "true", "t", "y", "yes", "True", "YES"):
            assert coerce_to_specific(val) is True, f"Failed for {val}"

    def test_integer(self):
        result = coerce_to_specific("42")
        assert result == 42
        assert isinstance(result, (int, bool))

    def test_integer_from_int(self):
        result = coerce_to_specific(7)
        # int 7 → first tries date parse (fails), then bool check ("7" not in bool set),
        # then int("7") → 7
        assert result == 7

    def test_decimal(self):
        result = coerce_to_specific("-000000001854.60")
        assert isinstance(result, Decimal)
        assert result == Decimal("-1854.60")

    def test_float_to_decimal(self):
        result = coerce_to_specific(7.2)
        assert isinstance(result, Decimal)
        assert result == Decimal("7.2")

    def test_plain_string(self):
        result = coerce_to_specific("something else")
        assert result == "something else"
        assert isinstance(result, str)

    def test_leading_zeros_integer(self):
        result = coerce_to_specific("010")
        assert result == 10
        assert isinstance(result, int)

    def test_long_digit_string(self):
        result = coerce_to_specific("001210107")
        assert result == 1210107


# ---------------------------------------------------------------------------
# worst_decimal
# ---------------------------------------------------------------------------
class TestWorstDecimal:
    def test_basic(self):
        result = worst_decimal(Decimal("762.1"), Decimal("-1.983"))
        assert result == Decimal("999.999")

    def test_same_scale(self):
        result = worst_decimal(Decimal("1.5"), Decimal("9.9"))
        assert result == Decimal("9.9")

    def test_different_precision(self):
        result = worst_decimal(Decimal("100.1"), Decimal("1.123"))
        assert result == Decimal("999.999")


# ---------------------------------------------------------------------------
# set_worst
# ---------------------------------------------------------------------------
class TestSetWorst:
    def test_string_padding(self):
        assert set_worst(311920, "48-49") == "48-490"

    def test_negative(self):
        assert set_worst(98, -2) == -20

    def test_bool_passthrough(self):
        assert set_worst(42, True) is True
        assert set_worst(42, False) is False

    def test_longer_new_value(self):
        result = set_worst(5, 123)
        assert result == 123


# ---------------------------------------------------------------------------
# best_representative
# ---------------------------------------------------------------------------
class TestBestRepresentative:
    def test_decimal_pair(self):
        result = best_representative(Decimal("-37.5"), Decimal("0.9999"))
        assert result == Decimal("-99.9999")

    def test_none_with_value(self):
        result = best_representative(None, Decimal("6.1"))
        assert result == Decimal("6.1")

    def test_int_and_string(self):
        result = best_representative(311920, "48-49")
        assert result == "48-490"

    def test_string_wins_over_int(self):
        result = best_representative(6, "foo")
        assert result == "foo"

    def test_decimal_same_type(self):
        result = best_representative(Decimal("4.95"), Decimal("6.1"))
        assert result == Decimal("9.99")

    def test_negative_decimal(self):
        result = best_representative(Decimal("-1.9"), Decimal("6.1"))
        assert result == Decimal("-9.9")

    def test_empty_string_ignored(self):
        result = best_representative(42, "   ")
        assert result == 42


# ---------------------------------------------------------------------------
# best_coercable
# ---------------------------------------------------------------------------
class TestBestCoercable:
    def test_integers(self):
        result = best_coercable((6, "2", 9))
        assert result == 6

    def test_decimal_wins(self):
        result = best_coercable((Decimal("6.1"), 2, 9))
        assert isinstance(result, Decimal)

    def test_dates(self):
        result = best_coercable(("2014 jun 7", "2011 may 2"))
        assert isinstance(result, datetime.datetime)

    def test_string_wins(self):
        result = best_coercable((7, 21.4, "ruining everything"))
        assert result == "ruining everything"


# ---------------------------------------------------------------------------
# sqla_datatype_for
# ---------------------------------------------------------------------------
class TestSqlaDataTypeFor:
    def test_float_returns_decimal(self):
        result = sqla_datatype_for(7.2)
        assert isinstance(result, sa.DECIMAL)

    def test_date_string_returns_datetime(self):
        result = sqla_datatype_for("Jan 17 2012")
        assert result is sa.DATETIME

    def test_plain_string_returns_unicode(self):
        result = sqla_datatype_for("something else")
        assert isinstance(result, sa.Unicode)
        assert result.length == 14

    def test_short_string(self):
        result = sqla_datatype_for("hi")
        assert isinstance(result, sa.Unicode)
        assert result.length == 2
