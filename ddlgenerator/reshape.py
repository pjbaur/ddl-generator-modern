#!/usr/bin/python
import copy  # noqa: F401 - used in doctests
import doctest
import logging
import re
from collections import OrderedDict, defaultdict
from hashlib import md5
from pprint import pprint  # noqa: F401 - used in doctests
from typing import Any

import ddlgenerator.typehelpers as th
from ddlgenerator.reserved import sql_reserved_words

_illegal_in_column_name = re.compile(r'[^a-zA-Z0-9_$#]')


def clean_key_name(key: Any) -> str:
    """
    Makes ``key`` a valid and appropriate SQL column name:

    1. Replaces illegal characters in column names with ``_``

    2. Prevents name from beginning with a digit (prepends ``_``)

    3. Lowercases name.  If you want case-sensitive table
    or column names, you are a bad person and you should feel bad.
    """
    result = _illegal_in_column_name.sub("_", key.strip())
    if not result:
        return 'unnamed_column'
    if result[0].isdigit():
        result = f'_{result}'
    if result.upper() in sql_reserved_words:
        result = f'_{key}'
    return result.lower()


def walk_and_clean(data: Any) -> Any:
    """
    Recursively walks list of dicts (which may themselves embed lists and dicts),
    transforming namedtuples to OrderedDicts and
    using ``clean_key_name(k)`` to make keys into SQL-safe column names

    >>> data = [{'a': 1}, [{'B': 2}, {'B': 3}], {'F': {'G': 4}}]
    >>> pprint(walk_and_clean(data))
        [OrderedDict([('a', 1)]),
         [OrderedDict([('b', 2)]), OrderedDict([('b', 3)])],
          OrderedDict([('f', OrderedDict([('g', 4)]))])]
    """
    # transform namedtuples to OrderedDicts
    if hasattr(data, '_fields'):
        data = OrderedDict((k, v) for (k, v) in zip(data._fields, data, strict=True))
    # Recursively clean up child dicts and lists
    if hasattr(data, 'items') and hasattr(data, '__setitem__'):
        for (key, val) in data.items():
            data[key] = walk_and_clean(val)
    elif (isinstance(data, list) or isinstance(data, tuple)
          or hasattr(data, '__next__') or hasattr(data, 'next')):
        data = [walk_and_clean(d) for d in data]

    # Clean up any keys in this dict itself
    if hasattr(data, 'items'):
        original_keys = data.keys()
        tup = ((clean_key_name(k), v) for (k, v) in data.items())
        data = OrderedDict(tup)
        if len(data) < len(original_keys):
            raise KeyError(f'Cleaning up {original_keys} created duplicates')
    return data


def _id_fieldname(fieldnames: Any, table_name: str = '') -> str | None:
    """
    Finds the field name from a dict likeliest to be its unique ID

    >>> _id_fieldname({'bar': True, 'id': 1}, 'foo')
    'id'
    >>> _id_fieldname({'bar': True, 'foo_id': 1, 'goo_id': 2}, 'foo')
    'foo_id'
    >>> _id_fieldname({'bar': True, 'baz': 1, 'baz_id': 3}, 'foo')
    """
    templates = [f'{table_name}_%s', '%s', '_%s']
    for stub in ['id', 'num', 'no', 'number']:
        for t in templates:
            if t % stub in fieldnames:
                return str(t % stub)
    return None


class UniqueKey:
    """
    Provides unique IDs.

    >>> idp1 = UniqueKey('id', int, start=4)
    >>> idp1.next()
    5
    >>> idp1.next()
    6
    >>> idp2 = UniqueKey('id', str)
    >>> id2 = idp2.next()
    >>> (len(id2), type(id2))
    (32, <class 'str'>)
    """
    def __init__(self, key_name: str, key_type: type, start: int = 0) -> None:
        self.name = key_name
        if key_type is not int and not hasattr(key_type, 'lower'):
            raise NotImplementedError(f"Primary key field {key_name} is {key_type}, must be string or integer")
        self.type = key_type
        self._counter = start

    def next(self) -> int | str:
        if self.type is int:
            self._counter += 1
            return self._counter
        else:
            return md5().hexdigest()


def unnest_child_dict(parent: dict, key: str, parent_name: str = '') -> None:
    """
    If ``parent`` dictionary has a ``key`` whose ``val`` is a dict,
    unnest ``val``'s fields into ``parent`` and remove ``key``.

    >>> parent = {'province': 'Québec', 'capital': {'name': 'Québec City', 'pop': 491140}}
    >>> unnest_child_dict(parent, 'capital', 'provinces')
    >>> pprint(parent)
    {'capital_name': 'Québec City', 'capital_pop': 491140, 'province': 'Québec'}

    >>> parent = {'province': 'Québec', 'capital': {'id': 1, 'name': 'Québec City', 'pop': 491140}}
    >>> unnest_child_dict(parent, 'capital', 'provinces')
    >>> pprint(parent)
    {'capital_id': 1,
     'capital_name': 'Québec City',
     'capital_pop': 491140,
     'province': 'Québec'}

    >>> parent = {'province': 'Québec', 'capital': {'id': 1, 'name': 'Québec City'}}
    >>> unnest_child_dict(parent, 'capital', 'provinces')
    >>> pprint(parent)
    {'capital': 'Québec City', 'province': 'Québec'}

    """
    val = parent[key]
    name = f"{parent_name}['{key}']"
    logging.debug(f"Unnesting dict {name}")
    id = _id_fieldname(val, parent_name)
    if id:
        logging.debug(f"{id} is {key}'s ID")
        if len(val) <= 2:
            logging.debug(f'Removing ID column {key}.{id}')
            val.pop(id)
    if len(val) == 0:
        logging.debug(f'{name} is empty, removing from {parent_name}')
        parent.pop(key)
        return
    elif len(val) == 1:
        logging.debug(f'Nested one-item dict in {name}, making scalar.')
        parent[key] = list(val.values())[0]
        return
    else:
        logging.debug(f'Pushing all fields from {name} up to {parent_name}')
        new_field_names = ['{}_{}'.format(key, child_key.strip('_')) for child_key in val]
        overlap = (set(new_field_names) & set(parent)) - set(id or [])
        if overlap:
            logging.error("Could not unnest child {}; {} already present in {} (child key: {})".format(name, ','.join(overlap), parent_name, key))  # noqa: E501
            return
        for (child_key, child_val) in val.items():
            new_field_name = '{}_{}'.format(key, child_key.strip('_'))
            parent[new_field_name] = child_val
        parent.pop(key)


_sample_data = [{'province': 'Québec', 'capital': {'name': 'Québec City', 'pop': 491140},
                 'id': 1, 'province_id': 1,
                 'cities': [{'name': 'Montreal', 'pop': 1649519}, {'name': 'Laval', 'pop': 401553}]},
                {'province': 'Ontario', 'capital': {'name': 'Toronto', 'pop': 2615060}, 'province_id': 2,
                 'cities': [{'name': 'Ottawa', 'pop': 883391}, {'name': 'Missisauga', 'pop': 713443}]},
                {'province': 'New Brunswick', 'capital': {'name': 'Fredricton', 'pop': 56224},
                 'id': 3, 'province_id': 3,
                 'cities': [{'name': 'Saint John', 'pop': 70063}, {'name': 'Moncton', 'pop': 69074}]},
                ]


def all_values_for(data: Any, field_name: str) -> list:
    return [row.get(field_name) for row in data if field_name in row]


def unused_field_name(data: Any, preferences: list[str]) -> str:
    for pref in preferences:
        if not all_values_for(data, pref):
            return pref
    raise KeyError(f"All desired names already taken in {str(preferences)}")


class ParentTable(list):
    """
    List of ``dict``s that knows (or creates) its own primary key field.

    >>> provinces = ParentTable(_sample_data, 'province', pk_name='province_id')
    >>> provinces.pk.name
    'province_id'
    >>> [p[provinces.pk.name] for p in provinces]
    [1, 2, 3]
    >>> provinces.pk.max
    3

    Now if province_id is unusable because it's nonunique:
    >>> data2 = copy.deepcopy(_sample_data)
    >>> for row in data2: row['province_id'] = 4
    >>> provinces2 = ParentTable(data2, 'province', pk_name='id', force_pk=True)
    >>> provinces2.pk.name
    'id'
    >>> [p[provinces2.pk.name] for p in provinces2]
    [1, 4, 3]

    """
    def is_in_all_rows(self, value: str) -> bool:
        return len([1 for r in self if r.get(value)]) == len(self)

    def __init__(self, data: Any, singular_name: str,
                 pk_name: str | None = None, force_pk: bool = False) -> None:
        self.name = singular_name
        super().__init__(data)
        self.pk_name = pk_name
        self.pk: UniqueKey | None = None
        if force_pk or (self.pk_name and self.is_in_all_rows(self.pk_name)):
            self.assign_pk()
        else:
            self.pk = None

    def suitability_as_key(self, key_name: str) -> tuple[Any, type | None]:
        """
        Returns: (result, key_type)
        ``result`` is True, False, or 'absent' or 'partial' (both still usable)
        ``key_type`` is ``int`` for integer keys or ``str`` for hash keys

        """
        pk_values = all_values_for(self, key_name)
        if not pk_values:
            return ('absent', int)  # could still use it
        key_type = type(th.best_coercable(pk_values))
        num_unique_values = len(set(pk_values))
        if num_unique_values < len(pk_values):
            return (False, None)     # non-unique
        if num_unique_values == len(self):
            return (True, key_type)  # perfect!
        return ('partial', key_type)  # unique, but some rows need populating

    def use_this_pk(self, pk_name: str, key_type: type) -> UniqueKey:
        if key_type is int:
            self.pk = UniqueKey(pk_name, key_type, max([0, ] + all_values_for(self, pk_name)))
        else:
            self.pk = UniqueKey(pk_name, key_type)
        return self.pk

    def assign_pk(self) -> UniqueKey:
        """

        """
        if not self.pk_name:
            self.pk_name = f'{self.name}_id'
            logging.warning(f'Primary key {self.name}.{self.pk_name} not requested, but nesting demands it')
        (suitability, key_type) = self.suitability_as_key(self.pk_name)
        if not suitability or key_type is None:
            raise Exception(f'Duplicate values in {self.name}.{self.pk_name}, unsuitable primary key')
        pk = self.use_this_pk(self.pk_name, key_type)
        if suitability in ('absent', 'partial'):
            for row in self:
                if self.pk_name not in row:
                    row[self.pk_name] = pk.next()
        return pk


def unnest_children(data: Any, parent_name: str = '', pk_name: str | None = None,
                    force_pk: bool = False) -> tuple[Any, str | None, dict, dict]:
    """
    For each ``key`` in each row of ``data`` (which must be a list of dicts),
    unnest any dict values into ``parent``, and remove list values into separate lists.

    Return (``data``, ``pk_name``, ``children``, ``child_fk_names``) where

    ``data``
      the transformed input list
    ``pk_name``
      field name of ``data``'s (possibly new) primary key
    ``children``
      a defaultdict(list) of data extracted from child lists
    ``child_fk_names``
      dict of the foreign key field name in each child

    """
    possible_fk_names = [f'{parent_name}_id', f'_{parent_name}_id', 'parent_id', ]
    if pk_name:
        possible_fk_names.insert(0, '{}_{}'.format(parent_name, pk_name.strip('_')))
    children = defaultdict(list)
    field_names_used_by_children = defaultdict(set)
    child_fk_names = {}
    parent = ParentTable(data, parent_name, pk_name=pk_name, force_pk=force_pk)
    for row in parent:
        try:
            for (key, val) in list(row.items()):
                if hasattr(val, 'items'):
                    unnest_child_dict(parent=row, key=key, parent_name=parent_name)
                elif isinstance(val, list) or isinstance(val, tuple):
                    # force listed items to be dicts, not scalars
                    row[key] = [v if hasattr(v, 'items') else {key: v} for v in val]
        except AttributeError as err:
            raise TypeError(f'Each row should be a dictionary, got {type(row)}: {row}') from err
        for (key, val) in row.items():
            if isinstance(val, list) or isinstance(val, tuple):
                for child in val:
                    field_names_used_by_children[key].update(set(child.keys()))
    for (child_name, names_in_use) in field_names_used_by_children.items():
        pk = parent.pk or parent.assign_pk()
        for fk_name in possible_fk_names:
            if fk_name not in names_in_use:
                break
        else:
            raise Exception(f"Cannot find unused field name in {parent_name}.{child_name} to use as foreign key")
        child_fk_names[child_name] = fk_name
        for row in parent:
            if child_name in row:
                for child in row[child_name]:
                    child[fk_name] = row[pk.name]
                    children[child_name].append(child)
                row.pop(child_name)
    # TODO: What if rows have a mix of scalar / list / dict types?
    return (parent, parent.pk.name if parent.pk else None, children, child_fk_names)


if __name__ == '__main__':
    doctest.testmod(optionflags=doctest.NORMALIZE_WHITESPACE)
