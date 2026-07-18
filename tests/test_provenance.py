"""M-3: the in-sample/out-of-sample tagger must gate on the CONDITION, not short-circuit every 'wildtype' run to
in-sample. A wildtype run in an unfitted medium (wildtype/acetate) is a genuine out-of-sample prediction — tagging
it in-sample would over-credit agreement as validation."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import provenance  # noqa: E402


def test_wildtype_is_gated_on_condition():
    assert provenance.tag("wildtype", "basal") == "in_sample"
    assert provenance.tag("wildtype", None) == "in_sample"              # canonical wildtype/basal
    assert provenance.tag("wildtype", "acetate") == "out_of_sample"     # the M-3 bug: was wrongly in_sample
    assert provenance.tag("wildtype", "succinate") == "out_of_sample"


def test_condition_and_perturbations_unchanged():
    assert provenance.tag("condition", "with_aa") == "in_sample"
    assert provenance.tag("condition", "no_oxygen") == "in_sample"
    assert provenance.tag("condition", "acetate") == "out_of_sample"
    assert provenance.tag("gene_knockout", "basal") == "out_of_sample"
    assert provenance.tag("ppgpp_conc", "basal") == "out_of_sample"
    assert provenance.classify("wildtype", "acetate")["provenance"] == "out_of_sample"
