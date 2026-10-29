"""Run the agent-tool conformance sweeps (src/cellarium/conformance.py) against a store and report.

    python scripts/tool_conformance.py [--store DIR] [--heavy] [--out FILE]

--store   the directory whose data/manifest is the store (default: the checkout). The sweeps chdir there.
--heavy   also call the tools that need the simulation image or a solver.

Prints one line per finding and writes the full report as JSON. Exit status 1 if any tool string-cuts its output,
returns an empty success from an unreadable source, changes its answer when rows are reordered, refuses without a
reason the registry can name, answers an unresolvable argument without marking it unknown, declares an enum value
its own tool refuses, leaves a string parameter with no description, reaches two disagreeing sites with one
glossary sentence, re-reads a fact that has a declared resolver, or -- with the run directory absent or a listener
column unwritten -- answers an empty success, misclassifies whose fault that is, or drops a fact it had already
resolved from the design's own declaration.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=str(ROOT))
    ap.add_argument("--heavy", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "evals" / "results" / "tool_conformance.json"))
    a = ap.parse_args()
    os.chdir(a.store)
    from cellarium import conformance, survey

    rows, _ = survey.analysis_rows()
    keys = sorted({survey.design_key(r) for r in rows})
    if not keys:
        print("the store has no reportable designs; nothing to sweep")
        return 1
    # PREFER A DESIGN WHOSE RAW IS ON THIS MACHINE. The old choice was the first knockout key in sort order,
    # which on this corpus is `gene_knockout/KO:alaS` -- one of the 17 designs whose seed directories were pruned
    # to HuggingFace. Every raw-reading tool then answers "no local raw" for the baseline call too, so the
    # absence sweeps have nothing to take away and report themselves as not exercised.
    # The CHEAPEST design that still has data: one local seed is enough to make every raw-reading tool take its
    # present-data path, and the sweeps call each tool up to three times, so seeds past the first buy nothing
    # here and cost real minutes.
    local = dict((k, n) for n, k in conformance.raw_backed_designs())
    backed_ko = sorted((n, k) for k, n in local.items() if "/KO:" in k)
    ko = (backed_ko[0][1] if backed_ko
          else next((k for k in keys if "/KO:" in k), keys[0]))
    ref = next((k for k in keys if k != ko and k.split("/")[0] == ko.split("/")[0] and "KO:" not in k),
               "wildtype/basal")
    rid = next((r.get("id") for r in rows if survey.design_key(r) == ko), None)
    gene = ko.split("KO:")[-1].split("+")[0].split("#")[0] if "KO:" in ko else "pfkA"
    calls = conformance.sample_args(ko, ref, rid, gene)
    print(f"store {a.store}: design {ko} vs {ref}; {len(calls)} tools with sample calls; "
          f"{local.get(ko, 0)} local raw seed(s) for the probe design")

    report = {"store": a.store, "design": ko, "reference": ref,
              "budget": conformance.budget_sweep(calls, a.heavy),
              "determinism": conformance.determinism_sweep(calls, a.heavy),
              "descriptions": conformance.description_claims(),
              "contract": conformance.contract_sweep(a.heavy),
              "unregistered_messages": conformance.unregistered_messages(),
              "confusable": conformance.confusable_pairs(),
              "enumeration_agreement": conformance.enumeration_agreement(),
              "channel_recording": conformance.channels_declare_when_they_are_recorded(),
              "enum_honesty": conformance.enum_honesty(calls, a.heavy),
              "param_descriptions": conformance.every_string_parameter_says_what_it_means(),
              "glossary_sites": conformance.glossary_sites_agree(),
              "one_fact_one_resolver": conformance.one_fact_one_resolver(),
              "resolver_places": conformance.a_resolver_reads_every_place_a_fact_can_live(),
              "fine_absence": conformance.fine_absence_sweep(calls, a.heavy, design=ko)}
    with tempfile.TemporaryDirectory() as tmp:
        report["absence"] = conformance.absence_sweep(calls, Path(tmp), a.heavy)

    bad = 0
    for r in report["budget"]:
        if r["string_cut"] or not r["valid_json"]:
            bad += 1
            print(f"SHAPE   {r['tool']}: {r['raw']} chars against a cap of {r['cap']}, cut mid-string")
        elif r["trimmed"]:
            print(f"trim    {r['tool']}: {r['raw']} -> {r['seen']} chars, omissions named")
    for r in report["absence"]:
        if r["empty_success"]:
            bad += 1
            print(f"ABSENCE {r['tool']}: an unreadable store gave an empty success: {r['excerpt']}")
    if any(r["verdict"] == "no_baseline" for r in report["fine_absence"]):
        bad += 1
        print(f"NOBASE   fine_absence: {ko} has no raw simOut on this machine, so the run- and channel-grain "
              f"sweeps had nothing to take away. They are NOT a pass.")
    for r in report["fine_absence"]:
        if not r["reads_source"]:
            continue
        g = r["grain"]
        if r["empty_success"]:
            bad += 1
            print(f"ABSENCE/{g} {r['tool']}: an absent {g} gave an empty success: {r['excerpt']}")
        if r["facts_dropped"]:
            bad += 1
            print(f"FACTLOSS/{g} {r['tool']}: resolved {r['facts_dropped']} and then dropped it when the "
                  f"{g} turned out to be absent")
        if r.get("narrowed_silently"):
            bad += 1
            print(f"NARROW/{g} {r['tool']}: {r['narrowed_silently']} fell when the {g} was taken away and the "
                  f"answer names no omission -- a partial read presented as a complete one")
        if r["about_ok"] is False:
            bad += 1
            print(f"ABOUT/{g} {r['tool']}: refused with about={r['about']!r} where an absent {g} is "
                  f"{r['about_expected']!r} -- {r['why_that_class']}")
    for r in report["determinism"]:
        if not r["repeat_equal"] or not r["order_invariant"]:
            bad += 1
            print(f"DETERM  {r['tool']}: repeat_equal={r['repeat_equal']} order_invariant={r['order_invariant']} "
                  f"{r['diff_hint']}")
    for r in report["descriptions"]:
        if r.get("earned"):
            print(f"claim   {r['tool']} ({r['where']}): \"{r['claim']}\" — earned: {r['earned']}")
        else:
            bad += 1
            print(f"CLAIM   {r['tool']} ({r['where']}): \"{r['claim']}\" tells the agent to read nothing as "
                  f"absence, and is not in EARNED_ABSENCE_CLAIMS")
    for r in report["contract"]:
        if r["verdict"] == "fail":
            bad += 1
            print(f"CONTRACT {r['tool']}: {r['why']} - {str(r.get('detail') or r.get('message'))[:120]}")
        elif r["verdict"] == "answered" and not r["marks_unknown_input"]:
            bad += 1
            print(f"CONTRACT {r['tool']}: answered an unresolvable argument without marking it unknown")
    for r in report["unregistered_messages"]:
        if r["dynamic"]:
            print(f"dynamic  {r['module']}: \"{r['message']}\" - classified at runtime from the exception name")
        else:
            bad += 1
            print(f"REASON   {r['module']}: \"{r['message']}\" matches no pattern in errors.PATTERNS")
    for r in report["confusable"]:
        if not r["cross_referenced"]:
            bad += 1
            print(f"SELECT   {r['a']} / {r['b']}: names overlap {r['name_overlap']} and neither description "
                  f"says when to use the other")
    for r in report["enumeration_agreement"]:
        if not r["agrees"]:
            bad += 1
            print(f"AGREE    {r['view']}: missing {r['missing_from_view']}, undeclared extras {r['not_in_envelope']}")
    for r in report["channel_recording"]:
        if not r["ok"]:
            bad += 1
            print(f"CHANNEL  {r['channel']}: recorded only in some configurations and does not say so")
    for r in report["enum_honesty"]:
        if r["verdict"] == "fail":
            bad += 1
            print(f"ENUM     {r['tool']}.{r['param']}: declares values its own tool refuses "
                  f"({[x['value'] for x in r['rejected']][:4]})")
        elif r["verdict"] == "not_exercised":
            print(f"skip     {r['tool']}.{r['param']}: {r['n_values']} values, no sample call to exercise them")
    for r in report["param_descriptions"]:
        if not r["ok"]:
            bad += 1
            print(f"PARAM    {r['tool']}.{r['param']}: a string parameter with no description — the model is "
                  f"asked to pick a value out of nothing")
    for r in report["one_fact_one_resolver"]:
        for o in r["reimplementations"]:
            bad += 1
            print(f"FACT     {r['fact']}: {o['module']}:{o['line']} re-reads it instead of calling "
                  f"{r['resolver']} -- {o['code']}")
    for r in report["resolver_places"]:
        if not r["ok"]:
            bad += 1
            print(f"RESOLVER {r['fact']}: does not answer from {r['place']}")
    for r in report["glossary_sites"]:
        if not r["ok"]:
            bad += 1
            print(f"GLOSS    {r['param']}: one glossary sentence reached {r['n_sites']} sites with "
                  f"{r['distinct_enums']} different enums ({r['tools']}) — it cannot mean the same thing at all "
                  f"of them")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(f"{bad} failure(s); report: {a.out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
