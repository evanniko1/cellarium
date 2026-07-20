"""M-8: analyst robustness pass. The aggregation is pure (no model) and gets the bulk of the coverage; the panel
driver + the agent entry are exercised through a scripted fake client (same style as test_council)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cellarium import robustness  # noqa: E402


# --- scripted fake client (all jurors share the 'verdict' tool -> popped FIFO in juror order) ---------------
class _Block:
    def __init__(self, data):
        self.type = "tool_use"; self.input = data


class _Resp:
    def __init__(self, data):
        self.content = [_Block(data)]
        self.usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()
        self._request_id = "req"


class _Msgs:
    def __init__(self, queue):
        self.queue = queue; self.calls = 0

    def create(self, **kw):
        self.calls += 1
        return _Resp(self.queue.pop(0))


class FakeClient:
    def __init__(self, verdicts):
        self.messages = _Msgs(list(verdicts))


# --- pure aggregation --------------------------------------------------------------------------------------
def _votes(analyst, verifier, skeptic, orders=(0, 1)):
    out = []
    for role, vs in (("analyst", analyst), ("verifier", verifier), ("skeptic", skeptic)):
        for o, v in zip(orders, vs):
            out.append({"role": role, "verdict": v, "order": o})
    return out


def test_aggregate_robust_when_unanimous_and_order_invariant():
    agg = robustness.aggregate(_votes(["supported", "supported"], ["supported", "supported"],
                                      ["supported", "supported"]))
    assert agg["verdict"] == "robust" and agg["stable"] is True and agg["agreement"] == 1.0
    assert agg["order_sensitive_roles"] == []


def test_aggregate_flags_order_sensitivity_even_if_mostly_supported():
    # the skeptic flips between the two orders -> fragile, must NOT read as robust
    agg = robustness.aggregate(_votes(["supported", "supported"], ["supported", "supported"],
                                      ["supported", "refuted"]))
    assert agg["verdict"] == "order_sensitive" and agg["stable"] is False
    assert "skeptic" in agg["order_sensitive_roles"]


def test_aggregate_refuted_when_skeptic_refutes_consistently():
    agg = robustness.aggregate(_votes(["supported", "supported"], ["supported", "supported"],
                                      ["refuted", "refuted"]))
    assert agg["verdict"] == "refuted" and agg["skeptic_refutes"] is True
    assert agg["dissent"]                                   # the refuting votes are surfaced


def test_aggregate_underpowered_when_modal():
    agg = robustness.aggregate(_votes(["underpowered", "underpowered"], ["underpowered", "underpowered"],
                                      ["underpowered", "underpowered"]))
    assert agg["verdict"] == "underpowered"


def test_aggregate_contested_without_clean_majority():
    agg = robustness.aggregate(_votes(["supported", "supported"], ["underpowered", "underpowered"],
                                      ["supported", "underpowered"]))
    # skeptic flipped supported<->underpowered -> order_sensitive takes precedence (fragile)
    assert agg["verdict"] == "order_sensitive"


def test_aggregate_handles_no_usable_votes():
    agg = robustness.aggregate([{"role": "analyst", "verdict": "garbage"}, {}])
    assert agg["verdict"] == "no_votes" and agg["stable"] is False


# --- order variants ---------------------------------------------------------------------------------------
def test_rotate_preserves_multiset_and_changes_order():
    seq = [1, 2, 3, 4]
    r = robustness._rotate(seq, 1)
    assert sorted(r) == sorted(seq) and r != seq and r == [2, 3, 4, 1]
    assert robustness._rotate(seq, 0) == seq                # order 0 is the canonical order


def test_order_variants_are_independent_deep_copies():
    bundle = {"channel": "growth_rate", "target": {"design": "a", "values": [1, 2, 3]},
              "reference": {"design": "b", "values": [4, 5, 6]}}
    vs = robustness._order_variants(bundle, 2)
    assert len(vs) == 2
    assert vs[0]["target"]["values"] == [1, 2, 3] and vs[1]["target"]["values"] == [2, 3, 1]
    bundle["target"]["values"][0] = 999                     # mutating the source must not touch the variants
    assert vs[0]["target"]["values"] == [1, 2, 3]


# --- panel driver + agent entry --------------------------------------------------------------------------
_BUNDLE = {"channel": "growth_rate", "welch_t": 3.1, "significant": True, "effect_pct": -20.0,
           "target": {"design": "gene_knockout/KO:pfkA", "values": [0.8, 0.82, 0.79]},
           "reference": {"design": "wildtype/basal", "values": [1.0, 1.01, 0.99]}}


def test_consistency_panel_runs_all_jurors_and_orders():
    client = FakeClient([{"verdict": "supported"}] * 6)     # 3 jurors x 2 orders
    out = robustness.consistency_panel("pfkA KO slows growth", _BUNDLE, client=client, n_orders=2)
    assert out["verdict"] == "robust"
    assert len(out["votes"]) == 6 and client.messages.calls == 6
    assert out["evidence"]["welch_t"] == 3.1


def test_robustness_check_builds_bundle_and_gates_on_evidence(monkeypatch):
    from cellarium import rigor, tools
    monkeypatch.setattr(rigor, "disconfirm", lambda t, r, c: dict(_BUNDLE))
    monkeypatch.setattr(tools, "power_check", lambda *a, **k: {"min_detectable_effect_pct_at_n": 5.0})  # 5% < 20% -> powered
    client = FakeClient([{"verdict": "supported"}, {"verdict": "supported"},
                         {"verdict": "supported"}, {"verdict": "supported"},
                         {"verdict": "refuted"}, {"verdict": "refuted"}])
    out = robustness.robustness_check("gene_knockout/KO:pfkA", "wildtype/basal", "growth_rate",
                                      claim="pfkA KO slows growth", client=client, n_orders=2)
    assert out["verdict"] == "refuted"                      # the skeptic refuted on both orders (effect is above MDE)
    assert out["power"]["underpowered"] is False and "adequately powered" in out["power_ruling"]


def test_robustness_check_underpowered_ruling_overrides_the_panel(monkeypatch):
    """DD-MTH-1: a FIXED, always-run power floor — when the observed effect is below the MDE, that's the verdict
    regardless of what the jurors reasoned (the panel here votes 'supported' unanimously)."""
    from cellarium import rigor, tools
    monkeypatch.setattr(rigor, "disconfirm", lambda t, r, c: dict(_BUNDLE))       # observed effect_pct = -20 (abs 20)
    monkeypatch.setattr(tools, "power_check", lambda *a, **k: {"min_detectable_effect_pct_at_n": 30.0})  # 20% < 30% MDE
    client = FakeClient([{"verdict": "supported"}] * 6)      # jurors would say robust...
    out = robustness.robustness_check("gene_knockout/KO:pfkA", "wildtype/basal", "growth_rate",
                                      claim="pfkA KO slows growth", client=client, n_orders=2)
    assert out["verdict"] == "underpowered" and out["stable"] is False            # ...but the MDE ruling overrides
    assert out["power"]["underpowered"] is True and "within the replicate-noise" in out["power_ruling"]


def test_robustness_check_errors_cleanly_without_evidence(monkeypatch):
    from cellarium import rigor
    monkeypatch.setattr(rigor, "disconfirm", lambda t, r, c: {"error": "corpus empty"})
    out = robustness.robustness_check("a", "b", "growth_rate", client=FakeClient([]))
    assert "error" in out and "panel" in out["note"]


def test_robustness_check_is_wired_as_an_agent_tool():
    from cellarium import tools
    assert "robustness_check" in tools._DISPATCH
    assert any(t["name"] == "robustness_check" for t in tools.TOOLS)
