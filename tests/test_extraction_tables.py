"""ADJ-W12: a table's TITLE read as its only column header, and the box-drawn dialect behind it.

FOUND BY READING WHAT THE PATH PRODUCED, not by reading the parser. Four of the 33 development reports lay
out their design matrix as an ASCII box table, and the reader took the first table LINE as the header row
-- so a one-cell title became the header, a role was matched against the title's own words, and every
later line's first cell became a VALUE for that role. 52 records whose values are `Configuration`,
`Designation`, `Config 1`, `(Wild-Type)`: row labels and header fragments, costed as demands on the model,
and every one of them `unresolved` -- 47 of the 190 unresolved demands over the whole development set. The
two table-TITLE spellings in `COLUMN_ROLES["factor:elongation_model"]` had been added to make that match
work, which cemented it.

WHAT THE FIX MOVED, reported here because three of the numbers are gate inputs and all three moved in the
favourable direction: `agent_covers_structural_roles` 0.745 -> 0.869, `unresolved_requirement_rate`
0.633 -> 0.569, and `G1`'s strict reading from `complementary` to `partial` -- the three reports that
shared no role with the model reading shared none because their only structural role was a misread.
`G2_ROLE_OVERLAP` did not move and is still failed, which is the control.

THE DIALECT IS NOT CLOSED. A row whose cells span two lines has no verbatim span to cite, so it is refused
and counted rather than stitched together.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import extraction  # noqa: E402

# Two layouts, both from the corpus, and they differ in the one way that matters: the first rules every
# logical row off and spans two lines per row; the second rules only its header and has one line per row.
BOX_TWO_LINE_ROWS = """# A proposal

## Factorial Simulation Matrix

|                       WCECOLI SIMULATION MODULE MATRIX                       |
+---------------+---------------+--------------------+-------------------------+
| Configuration | ppGpp Module  | Endogenous Amino   | Steady-State Target     |
| Designation   | State         | Acid Biosynthesis  | Charging Range          |
+---------------+---------------+--------------------+-------------------------+
| Config 1      | ON (Dynamic   | Active             | 0.55, 0.65, 0.85        |
| (Wild-Type)   | RelA / SpoT)  |                    | (Nominal = 0.65)        |
+---------------+---------------+--------------------+-------------------------+
| Config 2      | OFF (Fixed    | Active             | 0.55, 0.65, 0.85        |
| (Relaxed)     | 20 uM)        |                    | (Nominal = 0.65)        |
+---------------+---------------+--------------------+-------------------------+
"""

BOX_ONE_LINE_ROWS = """# A proposal

## Factorial Simulation Matrix

|                   SIMULATION MODULE MATRIX                    |
+---------------+---------------+-------------+-----------------+
| Configuration | ppGpp Module  | Amino Acid  | Target Charging |
+---------------+---------------+-------------+-----------------+
| Config 1      | ON (Dynamic)  | Endogenous  | 0.65 (Nominal)  |
| Config 2      | OFF (Fixed)   | Endogenous  | 0.65 (Nominal)  |
| Config 3      | OFF (Fixed)   | Hybrid      | 0.65 (Nominal)  |
| Config 4      | OFF (Fixed)   | Hybrid      | 0.65 (Nominal)  |
+---------------+---------------+-------------+-----------------+
"""

PIPE_TABLE = """# A proposal

## Factorial Simulation Matrix

| Run ID | Perturbation | ppGpp Module | Amino-Acid Mode | Target Setpoint |
| --- | --- | --- | --- | --- |
| R1 | gene_knockout | on | enzyme-aware | 0.55 |
| R2 | gene_knockout | off | medium-clamped | 0.85 |
"""


def _table(doc: str) -> dict:
    return extraction._header_and_rows(doc[doc.index("|"):])


# --- the defect ---------------------------------------------------------------------------------------

def test_a_table_TITLE_is_not_its_header_and_its_ROW_LABELS_are_not_LEVELS():
    """`Designation` and `(Wild-Type)` were being emitted as elongation-model levels."""
    recs = extraction.extract_structural(BOX_TWO_LINE_ROWS)
    values = {r.value for r in recs}
    assert "Configuration" not in values and "Designation" not in values
    assert not any(v.startswith("Config ") for v in values), values
    assert "factor:elongation_model" not in {r.role for r in recs}


def test_the_table_TITLE_spellings_are_GONE_from_the_column_vocabulary():
    """They were registered as header spellings to make the misread match. A title is not a column, and
    leaving them in would re-create the bug wherever a title survived the new reader."""
    for title in ("simulation module matrix", "wcecoli simulation module matrix"):
        assert title not in extraction.COLUMN_ROLES["factor:elongation_model"]
        assert extraction._ROLE_OF_HEADER.get(title) is None
    # The real column spelling stays: the fix is to the parser, not a narrowing of the vocabulary.
    assert "simulation module" in extraction.COLUMN_ROLES["factor:elongation_model"]


# --- how many lines make one row ----------------------------------------------------------------------

def test_the_HEADER_BLOCKS_OWN_LINE_COUNT_sets_how_many_lines_make_a_row():
    """ADJACENCY WAS THE FIRST RULE AND IT IS WRONG, measured on these two layouts: joining adjacent lines
    read the second table's four simulations as ONE row whose first cell was
    `Config 1 Config 2 Config 3 Config 4`. A box table is laid out uniformly, so the header block's own
    line count is the table's lines-per-row."""
    two = _table(BOX_TWO_LINE_ROWS)
    assert two["n_title_rows"] == 1
    assert two["header"][1] == "ppGpp Module State"
    assert [r["n_lines"] for r in two["rows"]] == [2, 2]

    one = _table(BOX_ONE_LINE_ROWS)
    assert one["n_title_rows"] == 1
    assert one["header"][1] == "ppGpp Module"
    assert [r["n_lines"] for r in one["rows"]] == [1, 1, 1, 1], "four rows, not one joined row"
    assert one["rows"][0]["cells"][0] == "Config 1"


def test_a_ONE_LINE_box_table_IS_READ_and_its_levels_are_the_REAL_ones():
    """The payoff half: this layout's cells are single-line, so a verbatim quote can be cut and the ppGpp
    column yields the levels the author actually wrote. On the development set this turned ten junk
    records in one report into eight real ones."""
    recs = extraction.extract_structural(BOX_ONE_LINE_ROWS)
    ppgpp = [r for r in recs if r.role == "factor:ppgpp_module"]
    assert len(ppgpp) == 4
    assert {r.value for r in ppgpp} == {"ON (Dynamic)", "OFF (Fixed)"}
    for r in ppgpp:
        assert r.quote in BOX_ONE_LINE_ROWS, "the quote must still be a verbatim span"


def test_a_MULTI_LINE_row_is_REFUSED_and_COUNTED_rather_than_STITCHED():
    """A cell assembled from two lines has no verbatim span to cite, so no record may be cut from it --
    rule R1, and `G3_QUOTES_VERBATIM` is a check on that construction. The pre-registration's own words: a
    field the tool cannot transcribe is COUNTED as untranscribable, not accommodated."""
    out = extraction.extract_report(BOX_TWO_LINE_ROWS)["structural"]
    assert out["n_records"] == 0
    assert out["refused_rows"]["n_multiline_rows_refused"] == 2
    assert out["refused_rows"]["n_title_rows_dropped"] == 1
    assert "no verbatim span to cite" in out["refused_rows"]["why"]


# --- the note: three states, not two -----------------------------------------------------------------

def test_a_table_THAT_COULD_NOT_BE_READ_is_not_reported_as_NO_TABLE():
    """The third case the note did not have, and this project's own recurring defect: a report whose
    box-drawn matrix asks for two design rows came back saying `no declared table was found in any plan
    section`, because the note's only test was whether any record survived."""
    found = extraction.extract_report(BOX_TWO_LINE_ROWS)["structural"]
    assert found["n_design_rows"] == 2
    assert "a declared table WAS found" in found["note"]
    assert "fact about this reader" in found["note"]
    assert len(found["unmapped_columns"]) == 4

    none = extraction.extract_report("# A proposal\n\n## Factorial Simulation Matrix\n\nNo table.\n")
    assert "no declared table was found" in none["structural"]["note"]


def test_n_design_rows_counts_LOGICAL_rows_and_not_LINES():
    """`n_design_rows` is read as "how many simulations is this plan asking for". Counting lines read a
    two-row box matrix as four runs plus a title, and over the development set 401 became 375."""
    assert extraction.extract_report(BOX_TWO_LINE_ROWS)["structural"]["n_design_rows"] == 2
    assert extraction.extract_report(BOX_ONE_LINE_ROWS)["structural"]["n_design_rows"] == 4


# --- the regression that matters ---------------------------------------------------------------------

def test_A_PIPE_TABLE_IS_UNCHANGED():
    """CAUGHT BY MEASURING, and it was catastrophic: grouping rows by the blocks a box table's rules
    delimit puts a Markdown table's every line in ONE block, because nothing but a newline separates them.
    The development set went from 2,018 structural records to 8."""
    recs = extraction.extract_structural(PIPE_TABLE)
    assert {r.value for r in recs if r.role == "factor:ppgpp_module"} == {"on", "off"}
    t = _table(PIPE_TABLE)
    assert t["header"][0] == "Run ID"
    assert [r["n_lines"] for r in t["rows"]] == [1, 1]
    assert t["n_title_rows"] == 0 and t["n_multiline_rows"] == 0


def test_a_pipe_table_with_a_ONE_CELL_TITLE_line_also_loses_the_title():
    """The same defect class in the other dialect, so the rule is not special-cased to box tables."""
    doc = PIPE_TABLE.replace("| Run ID", "| THE SIMULATION MATRIX |\n| Run ID", 1)
    t = _table(doc)
    assert t["n_title_rows"] == 1
    assert t["header"][0] == "Run ID"
    assert {r.value for r in extraction.extract_structural(doc)
            if r.role == "factor:ppgpp_module"} == {"on", "off"}


def test_BOTH_paths_kept_records_travel_through_extract_report():
    """A caller that must re-parse the document to see the records this call already cut is a caller
    whose second parse can disagree with the first -- and the held-out scorer was doing exactly that for
    the structural side, having been forced into it because the agent side's `kept` was missing too."""
    out = extraction.extract_report(PIPE_TABLE)
    assert len(out["structural"]["kept"]) == out["structural"]["n_records"]
    assert {r.role for r in out["structural"]["kept"]} == {
        r.role for r in extraction.verify_quotes(extraction.extract_structural(PIPE_TABLE),
                                                 PIPE_TABLE)["kept"]}
