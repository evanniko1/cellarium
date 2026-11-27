"""The label writers keep every identity axis, and a refusal is not a crash (D29, 2026-11-27).

Found by the suite after today's runs landed, each by a row that sat under the wrong design:
- a graded knockout written the generate.py way (`condition='KO:argS'`, no `target_genes`) and no timeline took the
  plain-condition branch of `_design_tag`, which has no dose: the S2 reproduction (expression 0.25) was labelled
  `graded_gene_knockout/KO:argS`, a key no graded design should have;
- a CRASH row's label (`_label`) used `condition or timeline` alone, so a crash of a fitted-start, graded, clamped or
  relaxed-threshold design was filed under another design (V3's refused anaerobic-start run landed on the timeline
  with no initial condition, which the envelope refuses);
- a run REFUSED before the model started was indexed as a crash, with no knowledge base and a NULL condition;
- two such rows alone in an arm made `corpus_schema.arms()` compare None with None.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cellarium import corpus_schema, manifest  # noqa: E402
from cellarium.model import Design  # noqa: E402


def test_a_graded_knockout_named_in_its_condition_keeps_its_dose():
    d = Design(perturbation="graded_gene_knockout", condition="KO:argS", params={"variant_index": 6444, "level": 4})
    assert manifest._design_tag(d) == "KO:argS#expr:0.25"
    with_genes = Design(perturbation="graded_gene_knockout", condition="KO:argS",
                        params={"variant_index": 6444, "level": 4, "target_genes": ["argS"]})
    assert manifest._design_tag(with_genes) == "KO:argS#expr:0.25"


def test_a_plain_knockout_label_does_not_move():
    assert manifest._design_tag(Design(perturbation="gene_knockout", condition="KO:argS")) == "KO:argS"
    assert manifest._design_tag(Design(perturbation="gene_knockout", condition="basal",
                                       params={"target_genes": ["argS"]})) == "KO:argS"


def test_a_crash_label_carries_the_same_identity_as_a_run_label():
    ic = Design(perturbation="timeline", timeline="0 minimal_minus_oxygen, 1200 minimal",
                params={"initial_condition": "no_oxygen"})
    assert manifest._label(ic, 900) == "timeline/0 minimal_minus_oxygen, 1200 minimal#ic:no_oxygen seed900"
    clamp = Design(perturbation="graded_gene_knockout", condition="KO:argS",
                   params={"level": 4, "target_genes": ["argS"], "ppgpp_clamp": "basal", "variant_index": 6444})
    assert manifest._label(clamp, 0) == "graded_gene_knockout/KO:argS#expr:0.25#ppgpp:basal seed0"
    # unchanged where there is nothing to carry
    assert manifest._label(Design(perturbation="wildtype", condition="basal"), 3) == "wildtype/basal seed3"
    assert manifest._label(Design(perturbation="wildtype", condition="basal", elongation_model="kinetic"), 3) == \
        "wildtype/basal#elong:kinetic seed3"


def test_arms_survive_an_arm_whose_rows_have_no_timestamp(monkeypatch):
    rows = [("?", "?", None, "a_crash", None, False, 0, "timeline", None),
            ("?", "?", None, "b_crash", None, False, 0, "timeline", None),
            ("kb1", "on", None, "r1", "2026-11-27T10:00:00", True, 3, "wildtype", None)]
    monkeypatch.setattr(corpus_schema, "_rows", lambda con=None: rows)
    monkeypatch.setattr(corpus_schema, "_dropped_ids", lambda: set())
    out = {a["kb_sha256"]: a for a in corpus_schema.arms()}
    assert out["?"]["rows"] == 2 and out["?"]["first_ts"] is None and out["?"]["last_ts"] is None
    assert out["kb1"]["first_ts"] == "2026-11-27T10:00:00"


def _bv():
    spec = importlib.util.spec_from_file_location("bv_batch_w", ROOT / "scripts" / "bv_batch.py")
    B = importlib.util.module_from_spec(spec)
    sys.modules["bv_batch_w"] = B
    spec.loader.exec_module(B)
    return B


def test_a_run_refused_before_the_model_started_is_not_indexed_as_a_crash(tmp_path):
    from cellarium import runner
    B = _bv()
    crashes = []

    def run_fn(spec):
        if spec.id == "refused":
            raise runner.RunRefused("Refusing out-of-envelope design: a threshold-moving shift")
        raise RuntimeError("the model script's output contains a traceback")
    specs = [B.RunSpec(id=i, design={"perturbation": "wildtype", "condition": i}, seed=0, generations=1, group=i)
             for i in ("refused", "crashed")]
    b = B.Batch({"batch": "t", "parallel": 1, "min_free_gb": 0, "gates": {}}, specs, run_fn=run_fn,
                read_fn=None, qc_fn=None, index_fn=None, deposit_fn=None, existing_fn=lambda s: "",
                free_gb_fn=lambda: 500.0, ledger=tmp_path / "l.jsonl", sleep=lambda s: None, poll_s=0.01,
                crash_index_fn=lambda spec, exc: crashes.append(spec.id))
    out = {s.id: s for s in b.run()}
    assert crashes == ["crashed"]                                  # the real crash is still indexed
    assert out["refused"].status == "failed" and "Refusing" in out["refused"].why
    ev = [json.loads(x) for x in (tmp_path / "l.jsonl").read_text(encoding="utf-8").splitlines()]
    refused = [e for e in ev if e.get("id") == "refused" and e["event"] == "run_failed"]
    assert refused and refused[0].get("refused") is True        # a watcher still sees a terminal run_failed


def test_the_envelope_refusal_is_a_run_refused_and_still_a_value_error():
    from cellarium import runner
    assert issubclass(runner.RunRefused, ValueError) and runner.RunRefused.refused is True
