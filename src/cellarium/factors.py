"""What a design ACTUALLY varies — the declared factor schema.

Three problems turned out to be one problem, so they are solved together here.

**WELL-1 — the factors are trapped in a string.** A design is keyed `ppgpp_conc/basal|ppGpp:0.6x`. A human reads
"ppGpp at 0.6x"; the database sees one opaque token, so "show me all ppGpp doses", "find the run identical to
this except the oxygen" and "which cells of the factorial are missing" are all inexpressible. The factor name and
level are right there in the label — this module parses them into typed fields, which works retroactively on
every existing row and needs no re-index.

**WELL-6m — the design name is not the design's identity.** `gene_knockout` addresses a transcription unit, and
the gene→index map is many-to-one: 4,538 genes collapse onto 2,984 indices, and 1,554 gene names are aliases of
a design named after a different gene. `KO:pheS`, `KO:pheT`, `KO:pheM`, `KO:thrS`, `KO:infC` and `KO:ihfA` are
ONE run. Two of them requested as independent knockouts would give a duplicate, not a replicate. So the
canonical identity of a knockout is its **ko_index set**, never its name.

**WELL-6g/6n — the name can be actively wrong.** `KO:flgB` deletes nine genes; `KO:rpoB` does not silence rpoB at
all; `KO:rpmJ` silences `secY` instead. And `rrna_operon_knockout` designs do not delete specific operons — the
model's rRNA rebalance erases operon identity while preserving the dose, so they are a graded reduction of total
rRNA capacity. Every design therefore carries a `label_integrity` verdict and a `true_label`.

Pure and dependency-free except for two committed caches (`gene_scope.json`, `ko_footprint.json`), so it works
with no wcEcoli checkout and no Docker. See docs/KNOCKOUT_SEMANTICS.md for the evidence behind the verdicts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# capability is itself dependency-free (os + dataclasses), so importing the elongation vocabulary here keeps
# this module's "works with no checkout and no Docker" property intact while making the tag spelling shared
# rather than re-implemented — a second copy of `#elong:` is exactly how a parser and a writer drift apart.
from .capability import DEFAULT_MODE, mode_from_tag

_CACHE = Path("data/cache")
_NUM = re.compile(r"^\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)")
_SCOPE: dict | None = None
_FP: dict | None = None

# The denominator in `rRNA_operons_removed:Nof7`. This is a BIOLOGICAL fact, not a model row count, which is why
# it is a constant and not derived from the manifest: E. coli K-12 MG1655 has seven rrn operons, and the model
# says so itself — `reconstruction/ecoli/dataclasses/molecule_groups.py:174` defines
# `rRNA_operons = ['rrnA','rrnB','rrnC','rrnD','rrnE','rrnG','rrnH']`, and the variant indexes it with a literal
# `np.zeros(7)` (models/ecoli/sim/variants/rrna_operon_knockout.py:62).
#
# It therefore holds in BOTH operon modes, which is the thing worth recording: the variant selects OPERONS and
# only then maps them to rows via `cistron_tu_mapping_matrix.T`, so with operons OFF that mapping becomes the
# identity and the same n operons are hit — as ~22 cistron rows rather than 7 TU rows, but still n of 7 operons.
# A row-count denominator WOULD have been mode-dependent and wrong; this one is not.
# `tests/test_factors.py` pins it against the model's own list whenever the checkout is present.
N_RRN_OPERONS = 7


def _scope() -> dict:
    global _SCOPE
    if _SCOPE is None:
        try:
            _SCOPE = json.loads((_CACHE / "gene_scope.json").read_text(encoding="utf-8"))
        except Exception:
            _SCOPE = {}
    return _SCOPE


def _footprints() -> dict:
    global _FP
    if _FP is None:
        try:
            _FP = json.loads((_CACHE / "ko_footprint.json").read_text(encoding="utf-8"))
        except Exception:
            _FP = {}
    return _FP


def level_num(raw: str | None) -> float | None:
    """The numeric level behind a level string: '0.6x'->0.6, '4op'->4, '1e-7_default'->1e-7, '0.01'->0.01.

    Suffixes are real in this corpus (`kin_w:1e-7_default` marks the model's own default), so the parse takes the
    leading number and ignores the rest rather than requiring a bare numeral."""
    if raw is None:
        return None
    m = _NUM.match(str(raw))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def parse(design_key: str) -> dict:
    """Decompose a design key into typed factors. PURE — no caches, no I/O, so it is testable in isolation.

    Returns family / base / factor / level_raw / level_num / genes. `genes` is a SET (order-normalised): a
    multi-KO is a set-membership question, not a dose, so those two query shapes stay in different fields.
    """
    key = str(design_key or "")
    family, _, tag = key.partition("/")
    # The elongation model is lifted OUT of the tag first and kept as its own field. Folding it into `base`
    # (so `basal` and `basal#elong:kinetic` became different bases) or into `level_raw` (so the dose parser
    # saw `0.6x#elong:kinetic`) would corrupt the very fields `one_factor_neighbours` filters on — and that
    # function is surfaced to the agent as THE control-selection primitive, so a wrong answer here propagates
    # into every comparison built on it.
    tag, elongation = mode_from_tag(tag)
    out = {"family": family, "base": None, "factor": None,
           "level_raw": None, "level_num": None, "genes": [], "elongation_model": elongation}
    if not tag:
        return out
    if "|" in tag:                                   # 'basal|ppGpp:0.6x' — the compound dose form
        base, _, spec = tag.partition("|")
        out["base"] = base
        name, sep, lvl = spec.partition(":")
        out["factor"] = name if sep else None
        out["level_raw"] = lvl if sep else None
        out["level_num"] = level_num(lvl) if sep else None
        return out
    if tag.startswith("KO:"):                        # 'KO:pfkA' or 'KO:gltX+relA+spoT'
        out["base"] = "basal"
        out["factor"] = "gene_KO"
        out["genes"] = sorted(g for g in tag[3:].split("+") if g)
        out["level_raw"] = tag[3:]
        return out
    if family == "timeline":                         # '0 minimal, 1200 minimal_plus_amino_acids'
        out["base"], out["factor"], out["level_raw"] = "minimal", "timeline", tag
        return out
    out["base"] = tag                                # a bare single-factor condition
    out["factor"] = "media" if family == "condition" else (family or None)
    out["level_raw"] = tag
    return out


def identity(design_key: str) -> dict:
    """`parse` plus the things that need the caches: the canonical experiment id, alias detection, and what the
    design actually perturbs.

    `canonical_id` is the dedupe key. For a knockout it is built from the **ko_index set**, because that is the
    experiment the simulator actually runs — so two alias names collapse to one id and cannot be mistaken for
    independent replicates.
    """
    f = parse(design_key)
    scope, fps = _scope(), _footprints()
    out = dict(f, aliases=[], perturbs=[], label_integrity="ok", true_label=None,
               canonical_id=None, notes=[])

    if f["factor"] == "gene_KO" and f["genes"]:
        idx, perturbed, integ = [], set(), "ok"
        for g in f["genes"]:
            e = scope.get(g) or {}
            ki = e.get("ko_index")
            if ki is None:
                integ = "no_design_possible"
                out["notes"].append(f"{g} has no RNA row — the variant cannot express this knockout")
                continue
            idx.append(ki)
            fp = fps.get(g)
            if not fp:
                perturbed.add(g)
                continue
            # what is really silenced: measured where we have it, otherwise the TU members are AT RISK
            if fp.get("target_silenced"):
                perturbed.add(g)
            else:
                integ = "misnamed"
                out["notes"].append(f"{g} is NOT silenced by this design (it has {fp.get('target_n_tu')} TUs)")
            perturbed.update(fp.get("measured_silenced") or [])
            if fp.get("co_members") and integ != "misnamed":
                integ = "operon_wide"
            for m in fp.get("unverified") or []:
                out["notes"].append(f"{m} shares the zeroed TU and is AT RISK (unverified)")
        out["ko_indices"] = sorted(idx)
        out["canonical_id"] = f"{f['family']}#idx:" + "+".join(str(i) for i in sorted(idx)) if idx else None
        # Genes sharing a targeted index. For a SINGLE-gene design these are true aliases — the identical run
        # under another name. For a multi-KO they merely ride one of the addressed indices, which is a different
        # (and weaker) statement, so the two are not conflated.
        if idx:
            want = set(idx)
            same = sorted(g for g, e in scope.items() if e.get("ko_index") in want and g not in f["genes"])
            out["same_index_genes"] = same
            out["aliases"] = same if len(f["genes"]) == 1 else []
        out["perturbs"] = sorted(perturbed)
        out["label_integrity"] = integ
    elif f["factor"] == "rRNA_KO":
        # The model's rRNA rebalance erases WHICH operons were removed while preserving HOW MUCH was removed,
        # so these are a total-capacity dose, not an operon deletion. Naming them otherwise is the error.
        n = int(f["level_num"] or 0)
        out["canonical_id"] = f"{f['family']}#rrna_removed:{n}of{N_RRN_OPERONS}"
        out["label_integrity"] = "relabel_required"
        out["perturbs"] = ["total_rRNA_capacity"]
        out["notes"].append("not an operon deletion: the rebalance erases operon identity but preserves the dose")
    else:
        out["canonical_id"] = f"{f['family']}#{f['factor']}:{f['level_raw']}" if f["factor"] else f"{f['family']}"

    # The elongation model is part of the canonical EXPERIMENT, not a label variant of it. Without this,
    # `dedupe` gives a kinetic and a steady-state knockout of one gene the SAME canonical_id, and integrity
    # check D4 does not merely miss the problem — it inverts, flagging the two arms as aliases wrongly counted
    # as replicates and telling the operator to "merge them, do not treat as replicates". The check would
    # actively argue for the merge this axis exists to prevent.
    if out.get("canonical_id") and f["elongation_model"] != DEFAULT_MODE:
        out["canonical_id"] += f"#elong:{f['elongation_model']}"

    out["true_label"] = true_label(design_key, out)
    return out


def true_label(design_key: str, ident: dict | None = None) -> str:
    """A name that says what the design actually does. Short enough to render; detail lives in the fields."""
    i = ident or identity(design_key)
    f_factor, genes = i.get("factor"), i.get("genes") or []
    if f_factor == "gene_KO":
        integ = i.get("label_integrity")
        fp = (_footprints().get(genes[0]) if len(genes) == 1 else None) or {}
        if integ == "operon_wide" and fp.get("tu_name"):
            return f"operon_KO:{fp['tu_name']}"
        if integ == "misnamed":
            hit = i.get("perturbs") or []
            missed = [g for g in genes if g not in hit]
            if len(genes) > 1:                       # a multi-KO: name what it DOES perturb, flag what it misses
                return (f"gene_KO:{'+'.join(hit) if hit else 'nothing'}"
                        f"({'+'.join(missed)} NOT silenced)" if missed else f"gene_KO:{'+'.join(hit)}")
            tu = fp.get("tu_name") or fp.get("tu_id") or "?"
            return f"TU_KO:{tu}(" + (f"→{'+'.join(hit)}" if hit else "silences nothing measured") + ")"
        if integ == "no_design_possible":
            return f"INVALID:{'+'.join(genes)}"
        return f"gene_KO:{'+'.join(genes)}"
    if f_factor == "rRNA_KO":
        return f"rRNA_operons_removed:{int(i.get('level_num') or 0)}of{N_RRN_OPERONS}"
    if f_factor and i.get("level_raw") is not None:
        return f"{f_factor}:{i['level_raw']}"
    return str(design_key)


def one_factor_neighbours(design_key: str, all_keys: list) -> list:
    """Designs differing from this one in exactly ONE factor — the correct-control query (WELL-2).

    This is the query the whole schema exists for, and it is a filter over typed fields: same family, same base,
    same factor, different level. No graph, no embedding — see WELL-6d1 for the measured comparison against a
    similarity search, which returned 1 of 5 relevant.
    """
    me = parse(design_key)
    if not me["factor"]:
        return []
    out = []
    for k in all_keys:
        if k == design_key:
            continue
        o = parse(k)
        # Same ELONGATION MODEL is a precondition, not a fourth factor to vary. This function promises a
        # neighbour differs "in exactly one factor", which an agent reads as "these are exchangeable except
        # for that factor" — and two runs under different elongation models are not exchangeable at all: the
        # same column names carry different quantities in each (a broadcast identity, 86 independent values,
        # or 86 exact zeros). Offering one as the control for the other would attach that promise to a pair
        # that cannot honour it.
        if o["elongation_model"] != me["elongation_model"]:
            continue
        if o["family"] == me["family"] and o["base"] == me["base"] and o["factor"] == me["factor"]:
            out.append(k)
    return sorted(out, key=lambda k: (level_num(parse(k)["level_raw"]) is None,
                                      level_num(parse(k)["level_raw"]) or 0, k))


def dedupe(design_keys: list) -> dict:
    """Group designs by canonical experiment. Two keys in the same group are the SAME RUN under different names —
    the guard against counting an alias as an independent replicate."""
    groups: dict = {}
    for k in design_keys:
        cid = identity(k).get("canonical_id") or k
        groups.setdefault(cid, []).append(k)
    dupes = {c: sorted(v) for c, v in groups.items() if len(v) > 1}
    return {"n_designs": len(design_keys), "n_experiments": len(groups),
            "duplicates": dupes,
            "note": ("Designs sharing a canonical_id are one experiment under several names. For knockouts the id "
                     "is the ko_index set, because that is what the simulator actually varies.")}
