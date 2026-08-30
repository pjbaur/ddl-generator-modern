# Deterministic Unnamed-Table Naming

**Date:** 2026-08-29
**Status:** Approved
**Input:** DEV-NOTES.md "Still open" — global table-name counter

## Problem

`Table.table_index` is a class-level counter incremented on every
`__init__` (`ddlgenerator/ddlgenerator.py`). Unnamed tables (bare Python
data, no `table_name`, no derivable source name) get
`generated_table{N}` where N depends on how many `Table` instances the
process created before. Consequences:

- Library use: same code emits different DDL depending on process history.
- Tests need a `reset_table_index` conftest fixture purely to undo the
  global state.
- The name is later detected by `startswith('generated_table')` string
  sniffing (`ddlgenerator.py:392`), which misfires on a user file named
  `generated_table.yaml`.

## Goal

Unnamed tables get the same name in every process, with no global
mutable state. Determinism chosen over cross-process uniqueness.

## Design

### Constant base name

- Remove `table_index` class attribute and its increment.
- `_find_table_name` falls back to the constant `generated_table`.
- `README.rst` already documents this exact name — becomes accurate.

### Explicit generated-name flag

- `_find_table_name` sets `self._name_generated = not self.table_name`
  on entry: True only when no name came from the caller, a Mongo
  collection, or a file basename.
- The source-name override at `ddlgenerator.py:392` becomes
  `if self._name_generated and hasattr(self.data, 'table_name'):`,
  replacing the `startswith` sniff. A file named
  `generated_table.yaml` is no longer treated as auto-named.

### Uniqueness contract

- The private `_used_table_names` pool (introduced by PR #19) stays the
  sole deduplication mechanism: a second unnamed table in one pooled run
  becomes `generated_table_1` with the existing warning.
- Two independent `Table([...])` calls without a pool both yield
  `generated_table`. Intended and deterministic. Callers emitting
  multi-table scripts pass distinct names or a pool.
- The pool parameter stays private (`_used_table_names`).

### Test changes

- Delete the `reset_table_index` conftest fixture.
- Add tests:
  - Determinism: a `Table` built after prior instances still names
    itself `generated_table`.
  - Pool suffix: two unnamed tables sharing a pool produce
    `generated_table` and `generated_table_1`.
  - Source override: a `Source` with its own `table_name` overrides
    only when no other name was provided (flag True).
  - `generated_table.yaml` file: derived basename wins, not treated as
    auto-named.

### Documentation

- DEV-NOTES.md "Still open" item closed in the same PR.
- README already correct; no change.

## Breaking change

Library code relying on the global counter to keep independent unnamed
tables distinct now sees the same name. Mitigation: pass `table_name`
or share an `_used_table_names` pool. Project is not on PyPI; sole
consumer is this repository.

## Testing strategy

Unit tests above, plus full suite (`pytest -m "not postgres"`) green.
No `.sql` golden fixture references the numbered name (verified by
grep), so no fixture churn expected.
