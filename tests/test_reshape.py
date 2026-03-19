#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for ddlgenerator.reshape module (P3-2).

Covers: walk_and_clean, _id_fieldname, UniqueKey, unnest_child_dict,
        unnest_children, ParentTable
"""

from collections import OrderedDict, namedtuple

import pytest

from ddlgenerator.reshape import (
    walk_and_clean,
    _id_fieldname,
    UniqueKey,
    unnest_child_dict,
    unnest_children,
    ParentTable,
    all_values_for,
    unused_field_name,
)


# ---------------------------------------------------------------------------
# walk_and_clean
# ---------------------------------------------------------------------------
class TestWalkAndClean:
    def test_simple_dicts(self):
        data = [{"a": 1}, {"b": 2}]
        result = walk_and_clean(data)
        assert list(result[0].keys()) == ["a"]
        assert result[0]["a"] == 1

    def test_uppercase_keys_lowered(self):
        data = [{"Name": "Alice", "AGE": 30}]
        result = walk_and_clean(data)
        assert "name" in result[0]
        assert "age" in result[0]

    def test_nested_dict(self):
        data = [{"F": {"G": 4}}]
        result = walk_and_clean(data)
        assert "f" in result[0]
        assert "g" in result[0]["f"]

    def test_namedtuple_converted(self):
        Point = namedtuple("Point", ["x", "y"])
        data = Point(3, 4)
        result = walk_and_clean(data)
        assert isinstance(result, OrderedDict)
        assert result["x"] == 3
        assert result["y"] == 4

    def test_nested_list(self):
        data = [[{"A": 1}, {"A": 2}]]
        result = walk_and_clean(data)
        assert len(result[0]) == 2
        assert "a" in result[0][0]

    def test_duplicate_keys_after_clean_raises(self):
        # Two keys that collapse to the same name after cleaning
        data = [OrderedDict([("a-b", 1), ("a b", 2)])]
        with pytest.raises(KeyError, match="duplicates"):
            walk_and_clean(data)

    def test_empty_list(self):
        result = walk_and_clean([])
        assert result == []

    def test_special_chars_in_keys(self):
        data = [{"my column": 1, "other-col": 2}]
        result = walk_and_clean(data)
        assert "my_column" in result[0]
        assert "other_col" in result[0]


# ---------------------------------------------------------------------------
# _id_fieldname
# ---------------------------------------------------------------------------
class TestIdFieldname:
    def test_finds_id(self):
        assert _id_fieldname({"bar": True, "id": 1}, "foo") == "id"

    def test_finds_prefixed_id(self):
        assert _id_fieldname({"bar": True, "foo_id": 1, "goo_id": 2}, "foo") == "foo_id"

    def test_none_when_no_id(self):
        assert _id_fieldname({"bar": True, "baz": 1, "baz_id": 3}, "foo") is None

    def test_finds_num(self):
        assert _id_fieldname({"num": 5}, "test") == "num"

    def test_finds_number(self):
        assert _id_fieldname({"number": 5}, "test") == "number"


# ---------------------------------------------------------------------------
# UniqueKey
# ---------------------------------------------------------------------------
class TestUniqueKey:
    def test_int_key_increments(self):
        uk = UniqueKey("id", int, start=4)
        assert uk.next() == 5
        assert uk.next() == 6

    def test_str_key_returns_hash(self):
        uk = UniqueKey("id", str)
        val = uk.next()
        assert isinstance(val, str)
        assert len(val) == 32  # md5 hexdigest length

    def test_unsupported_type_raises(self):
        with pytest.raises(NotImplementedError):
            UniqueKey("id", float)


# ---------------------------------------------------------------------------
# unnest_child_dict
# ---------------------------------------------------------------------------
class TestUnnestChildDict:
    def test_basic_unnest(self):
        parent = {"province": "Québec", "capital": {"name": "Québec City", "pop": 491140}}
        unnest_child_dict(parent, "capital", "provinces")
        assert "capital_name" in parent
        assert "capital_pop" in parent
        assert "capital" not in parent

    def test_unnest_with_id(self):
        parent = {"province": "Québec", "capital": {"id": 1, "name": "Québec City"}}
        unnest_child_dict(parent, "capital", "provinces")
        # With id + 1 other field → 2 fields total, id removed, 1 left → scalar
        assert parent["capital"] == "Québec City"

    def test_empty_after_id_removal(self):
        parent = {"province": "Québec", "capital": {"id": 1}}
        unnest_child_dict(parent, "capital", "provinces")
        assert "capital" not in parent


# ---------------------------------------------------------------------------
# ParentTable
# ---------------------------------------------------------------------------
class TestParentTable:
    def test_with_pk(self):
        data = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        pt = ParentTable(data, "test", pk_name="id")
        assert pt.pk is not None
        assert pt.pk.name == "id"

    def test_without_pk(self):
        data = [{"name": "a"}, {"name": "b"}]
        pt = ParentTable(data, "test")
        assert pt.pk is None

    def test_force_pk(self):
        data = [{"id": 10, "name": "a"}, {"name": "b"}]
        pt = ParentTable(data, "test", pk_name="id", force_pk=True)
        assert pt.pk is not None
        # Second row should have been assigned an ID
        assert "id" in pt[1]

    def test_duplicate_pk_raises(self):
        data = [{"id": 1, "name": "a"}, {"id": 1, "name": "b"}]
        with pytest.raises(Exception, match="Duplicate"):
            ParentTable(data, "test", pk_name="id")

    def test_suitability_absent(self):
        data = [{"name": "a"}, {"name": "b"}]
        pt = ParentTable(data, "test")
        (result, key_type) = pt.suitability_as_key("id")
        assert result == "absent"

    def test_suitability_unique(self):
        data = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        pt = ParentTable(data, "test")
        (result, key_type) = pt.suitability_as_key("id")
        assert result is True


# ---------------------------------------------------------------------------
# unnest_children
# ---------------------------------------------------------------------------
class TestUnnestChildren:
    def test_basic_unnest(self):
        data = [
            {"id": 10, "name": "parent", "items": [{"val": "a"}, {"val": "b"}]},
        ]
        (parent, pk_name, children, child_fk_names) = unnest_children(
            data, parent_name="test", pk_name="id"
        )
        assert "items" in children
        assert len(children["items"]) == 2

    def test_nested_dict_unnested(self):
        data = [
            {"id": 10, "info": {"x": 100, "y": 200}},
        ]
        (parent, pk_name, children, child_fk_names) = unnest_children(
            data, parent_name="test", pk_name="id"
        )
        # Dict should be unnested into parent
        assert "info_x" in parent[0]
        assert "info_y" in parent[0]

    def test_no_children(self):
        data = [{"id": 10, "name": "flat"}]
        (parent, pk_name, children, child_fk_names) = unnest_children(
            data, parent_name="test", pk_name="id"
        )
        assert len(children) == 0


# ---------------------------------------------------------------------------
# all_values_for
# ---------------------------------------------------------------------------
class TestAllValuesFor:
    def test_basic(self):
        data = [{"a": 1, "b": 2}, {"a": 3}]
        assert all_values_for(data, "a") == [1, 3]

    def test_missing_key(self):
        data = [{"a": 1}, {"b": 2}]
        assert all_values_for(data, "a") == [1]

    def test_no_matches(self):
        data = [{"a": 1}]
        assert all_values_for(data, "z") == []


# ---------------------------------------------------------------------------
# unused_field_name (bug fix tests)
# ---------------------------------------------------------------------------
class TestUnusedFieldName:
    def test_returns_first_unused(self):
        data = [{"a": 1}]
        result = unused_field_name(data, ["z", "y"])
        assert result == "z"

    def test_skips_used_names(self):
        data = [{"a": 1, "b": 2}]
        result = unused_field_name(data, ["a", "c"])
        assert result == "c"

    def test_raises_keyerror_when_all_taken(self):
        """Test that unused_field_name raises KeyError (not NameError) when all names are taken."""
        data = [{"a": 1, "b": 2, "c": 3}]
        with pytest.raises(KeyError, match="already taken"):
            unused_field_name(data, ["a", "b", "c"])


# ---------------------------------------------------------------------------
# unnest_child_dict error path (bug fix tests)
# ---------------------------------------------------------------------------
class TestUnnestChildDictErrorPath:
    def test_overlap_logs_error_without_typeerror(self, caplog):
        """Test that unnest_child_dict logs an error (not TypeError) on field overlap."""
        import logging
        # Create a parent with a field that will overlap when unnesting
        parent = {
            "province": "Québec",
            "capital_name": "Existing",  # This will conflict
            "capital": {"name": "Québec City", "pop": 491140}
        }
        # This should log an error, not raise TypeError
        with caplog.at_level(logging.DEBUG):
            unnest_child_dict(parent, "capital", "provinces")
        # The function should return early without modifying parent
        assert "capital" in parent  # Key should still exist
        assert parent["capital_name"] == "Existing"  # Should not be overwritten
        # Check that an error was logged
        assert any("Could not unnest" in record.message for record in caplog.records if record.levelno >= logging.ERROR)
