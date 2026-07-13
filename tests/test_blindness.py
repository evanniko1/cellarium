"""The Council blindness invariant — the paper's D2/D4 quarantine, as a test.

The Socratic Council frames its hypothesis BLIND to the corpus RESULTS: it sees the instrument's dial LABELS
(capabilities) and the question, never its readings. That property is the scientific control the human-eval /
recitation experiments rest on, and it is now the thing a dedicated Hypothesis surface (with web/lit-review coming)
must not erode. This test captures the payloads the Council actually sends to its role-LLMs and asserts no
simulation reading — and no reference answer — ever enters them. See docs/HYPOTHESIS_MODE_PLAN.md.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CELLARIUM_MANIFEST", "data/manifest/vmnik-compact.parquet")

from cellarium import council, instrument  # noqa: E402

# capabilities + internal debate state — everything the Council is allowed to see. Corpus READINGS are NOT here.
_ALLOWED_KEYS = {
    "question", "dial_labels", "channels", "perturbations", "candidate", "objections", "feasible",
    "answered", "resolved_ambiguities", "previous_candidate", "open_objections", "instruction",
    "debate_so_far",   # the bounded cross-round digest — built from the debate's own claims/objections, never readings
}


def test_proposer_payload_is_blind_to_corpus_results(monkeypatch):
    """The proposer — which writes the hypothesis — must see only the question + dial labels, no reading, no leak."""
    captured = {}

    class _StopAfterFirstCall(Exception):
        pass

    def fake_emit(client, model, system, tool, payload, **kw):
        captured.update(payload)
        raise _StopAfterFirstCall()

    monkeypatch.setattr(council, "_emit", fake_emit)
    try:
        council.deliberate("Is the aaRS-KO survival spread a real charged-tRNA depletion difference, or a "
                           "generation-depth artifact?", max_rounds=1)
    except _StopAfterFirstCall:
        pass

    assert captured, "no Council payload was captured"
    # THE quarantine control key: a reference answer must NOT be in a normal deliberation
    assert "leaked_reference_answer" not in captured, "quarantine breach: a reference answer leaked to the proposer"
    # no surprise key that could smuggle in corpus data
    extra = set(captured) - _ALLOWED_KEYS
    assert not extra, f"unexpected key(s) in the proposer payload (possible corpus leak): {extra}"
    # dial_labels are capability metadata (channel NAMES + notes/units), never readings
    chans = (captured.get("dial_labels") or {}).get("channels", {})
    assert chans, "dial_labels should expose channel capabilities"
    for name, meta in chans.items():
        meta = meta or {}
        leaked = {k for k in meta if k in ("value", "values", "mean", "reading", "result", "growth_rate")}
        assert not leaked, f"a reading leaked into dial_labels[{name}]: {leaked}"


def test_sufficiency_gate_payload_is_blind(monkeypatch):
    """Phase 3(b): the scope-only sufficiency gate is another Council surface — it too must see ONLY the question +
    capabilities, never a reading or a leaked answer, so a clarifying question can never smuggle out a finding."""
    captured = {}

    def fake_emit(client, model, system, tool, payload, **kw):
        captured.update(payload)
        return {"sufficient": True}

    monkeypatch.setattr(council, "_emit", fake_emit)
    council.sufficiency_gate("what happens to the cell?", client=object(), models={"judge": "m"})
    assert captured, "no gate payload was captured"
    assert "leaked_reference_answer" not in captured, "quarantine breach: a reference answer leaked to the gate"
    extra = set(captured) - _ALLOWED_KEYS
    assert not extra, f"unexpected key(s) in the gate payload (possible corpus leak): {extra}"
    assert (captured.get("dial_labels") or {}).get("channels"), "the gate should see channel capabilities"


def test_debate_digest_is_blind_and_bounded():
    """The 'debate so far' digest each role now sees must carry ONLY the debate's own artifacts (claims + objection
    type/severity/status), never a reading — and stay bounded (claims truncated). It is built from role-LLM output,
    which was itself blind, so no corpus value can enter."""
    ledger = [{"id": "r1.1", "round": 1, "type": "undefined_term", "severity": "substantive", "resolved_round": 2}]
    log = [{"round": 1, "claim": "X" * 500, "objections": [{"id": "r1.1", "type": "undefined_term", "severity": "substantive"}]}]
    dig = council._debate_digest(log, ledger)
    assert dig and dig[0]["round"] == 1
    assert len(dig[0]["claim"]) <= 200                       # bounded: claim truncated
    assert dig[0]["objections"][0]["status"] == "resolved@R2"
    import json
    blob = json.dumps(dig)
    for marker in ("simout_path", "growth_rate", "welch_t", "/cellarium/", "division_rate", "mean"):   # readings
        assert marker not in blob, f"a reading leaked into the debate digest: {marker}"
    nums = [v for e in dig for v in (e.get("round"),) if isinstance(v, (int, float))]
    assert nums == [1]                                       # only the round index is numeric — no data values


def test_web_research_input_is_blind(monkeypatch):
    """Phase 3(a) librarian: the web_search pass may search EXTERNAL literature, but its INPUT must carry only the
    question + instrument capabilities — never a corpus reading or a leaked answer, so it can't search FROM the
    answer or smuggle corpus data into the request."""
    captured = {}

    class _Cli:
        class messages:
            @staticmethod
            def create(**kw):
                import json as _j
                captured.update(_j.loads(kw["messages"][0]["content"]))

                class _B:
                    type = "text"; text = "a cited brief"; citations = []

                class _R:
                    content = [_B()]
                return _R()

    out = council.web_research("Is the aaRS-KO survival spread a charging-depletion difference?", client=_Cli())
    assert out["brief"] == "a cited brief"
    assert "leaked_reference_answer" not in captured
    # capabilities (channel/perturbation NAMES) are allowed; a READING would be a run path, a stat, or a numeric value
    import json as _j
    blob = _j.dumps(captured)
    for m in ("simout_path", "welch_t", "/cellarium/", "gene_knockout_0", "condition_0"):
        assert m not in blob, f"a corpus reading/run-ref leaked into the librarian request: {m}"
    caps = captured.get("instrument_capabilities", {})
    assert all(isinstance(c, str) for c in caps.get("channels", []))   # channel NAMES only, never {name: value} readings
    nums = [v for v in _j.loads(blob).get("instrument_capabilities", {}).get("channels", []) if isinstance(v, (int, float))]
    assert not nums


def test_leak_control_mechanism_exists():
    """The quarantine is testable BECAUSE the ablation can deliberately leak an answer key — confirm that lever
    exists (so 'blind' is a measured claim, not an assumption) and that it is off by default."""
    seen = {}

    def fake_emit(client, model, system, tool, payload, **kw):
        seen.clear()
        seen.update(payload)
        return {"claim": "x"}

    import cellarium.council as c
    orig = c._emit
    c._emit = fake_emit
    try:
        labels = instrument.dial_labels()
        c._propose(None, {"proposer": "m"}, "q", labels, None, [], [])           # normal: no leak
        assert "leaked_reference_answer" not in seen
        c._propose(None, {"proposer": "m"}, "q", labels, None, [], [], leak="THE ANSWER")  # ablation: leak on
        assert seen.get("leaked_reference_answer") == "THE ANSWER"
    finally:
        c._emit = orig


def test_dial_labels_carry_no_readings():
    """instrument.dial_labels() is the whole capability view handed to the Council — assert it's STRUCTURE, not
    data: each channel maps to capability metadata (unit/note strings), never a per-run numeric value, and the view
    carries no run identifiers or paths (those would be readings)."""
    labels = instrument.dial_labels()
    chans = labels.get("channels", {})
    assert chans, "dial_labels should name the channels (capabilities)"
    for name, meta in chans.items():
        assert isinstance(meta, dict), f"channel {name} should be capability metadata"
        nums = [v for v in meta.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        assert not nums, f"a numeric reading leaked into dial_labels[{name}]: {nums}"
    import json
    blob = json.dumps(labels)
    for marker in ("simout_path", "/cellarium/", "gene_knockout_0_", "condition_0_"):   # run ids / paths = readings
        assert marker not in blob, f"a run reference leaked into dial_labels: {marker}"
