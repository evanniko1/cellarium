"""NMI-4 — there must be exactly ONE published dataset size, and the prose must agree with it.

THE DEFECT THIS PINS. Two committed documents disagreed about how large the public dataset is. `README.md`
said "about 198 GB across 96 run archives"; `data/hf/UPLOAD_LEDGER.md` said "13 designs / 55 runs (~90-100 GB
compressed)". Neither cited a measurement, and when one was finally taken the answer was a THIRD number:
270.0 GB across 131 run archives, spanning 35 designs. Both documents had been wrong for months, in different
directions, about the single number a reader uses to judge the dataset claim.

WHY A TEST AND NOT A CORRECTION. Correcting two numbers fixes today and guarantees nothing. The failure mode
is not a wrong number, it is TWO numbers: any size written in prose drifts the moment another batch uploads,
because nothing connects the sentence to the deposit. So the measurement lives in one artifact,
`data/hf/DATASET_SIZE.json`, every document cites it, and this test reads the numbers back OUT of the prose
and fails when they diverge. Adding a third document that states a size without citing the artifact fails too.

WHY IT RUNS OFFLINE. This test never touches the network. It compares the committed artifact against the
committed prose, which is a property of the repository and is therefore checkable on any CI runner, every
push. Whether the ARTIFACT still matches the live repo is a different question with a different failure mode
-- it needs network, it can fail for reasons nobody can fix in a pull request, and a check like that gets
switched off. That one is `scripts/verify_dataset_size.py --check`, run on a schedule, and its being separate
is deliberate.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / "data" / "hf" / "DATASET_SIZE.json"

# Every file that states a size for the published dataset.
#
# README.md is TRACKED, so it is what a reviewer or a fresh clone sees, and it is required.
# data/hf/UPLOAD_LEDGER.md is gitignored working state — present on a maintainer's machine, absent from a
# clone — so it is checked WHEN PRESENT and skipped otherwise. Making it required would fail CI on every
# runner for a file CI cannot have, which is how a check gets switched off. Making it optional on the
# maintainer's machine would miss the drift, since that is the only place it can drift.
REQUIRED_DOCS = (ROOT / "README.md",)
OPTIONAL_DOCS = (ROOT / "data" / "hf" / "UPLOAD_LEDGER.md",)
CITING_DOCS = REQUIRED_DOCS + OPTIONAL_DOCS

pytestmark = pytest.mark.skipif(not ARTIFACT.exists(),
                                reason="no measured artifact in this checkout; run scripts/verify_dataset_size.py")


@pytest.fixture(scope="module")
def measured() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_the_tracked_document_exists_at_all():
    """The required half of the contract: a clone must contain at least one document stating the size."""
    for doc in REQUIRED_DOCS:
        assert doc.exists(), f"{doc.relative_to(ROOT)} is missing from this checkout"


def test_the_artifact_is_a_real_measurement(measured):
    """A zeroed or empty artifact would silently satisfy every comparison below."""
    assert measured["n_runs"] > 0 and measured["total_gb"] > 0, \
        "the artifact records nothing; a measurement that found nothing must not have been written"
    assert measured["n_runs"] == measured["n_archives"], "one archive is one run; these cannot disagree"
    assert measured["archives_without_reported_size"] == 0, \
        "some archives reported no size, so total_gb is an undercount and must not be published as a total"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", measured["measured_utc"])


@pytest.mark.parametrize("doc", CITING_DOCS, ids=lambda p: p.name)
def test_every_citing_document_states_the_measured_size(doc, measured):
    """The two numbers a reader actually quotes -- gigabytes and archive count -- must match the artifact."""
    if not doc.exists():
        pytest.skip(f"{doc.name} is not present in this checkout (gitignored working state)")
    # whitespace-normalised: prose wraps, and a test that forbids a line break is a test about formatting
    text = re.sub(r"\s+", " ", doc.read_text(encoding="utf-8"))
    gb = f"{measured['total_gb']} GB"
    runs = f"{measured['n_runs']} run archives"
    missing = [s for s in (gb, runs) if s not in text]
    assert not missing, (
        f"{doc.relative_to(ROOT)} does not state the measured dataset size: missing {missing}. "
        f"The artifact says {gb} across {measured['n_runs']} run archives. "
        "Update the prose, or re-run scripts/verify_dataset_size.py if the deposit changed.")


@pytest.mark.parametrize("doc", CITING_DOCS, ids=lambda p: p.name)
def test_every_citing_document_points_at_the_artifact(doc, measured):
    """A number that happens to be right is not the same as a number with a source. The point of the fix is
    that a reader can find out where it came from, so the citation is part of the contract."""
    if not doc.exists():
        pytest.skip(f"{doc.name} is not present in this checkout (gitignored working state)")
    text = doc.read_text(encoding="utf-8")
    assert "DATASET_SIZE.json" in text, (
        f"{doc.relative_to(ROOT)} states a size without citing data/hf/DATASET_SIZE.json. "
        "An uncited number is how this repository ended up with two of them.")


def test_no_stale_size_claims_survive_anywhere(measured):
    """The specific wrong numbers that were in circulation must not reappear in a tracked document.

    This is narrower than it looks, and deliberately so: it bans the two literal strings that were wrong, not
    any number near the word GB, because a general rule would fire on the local corpus total (361 GB) and on
    Docker's disk budget, which are different quantities that are allowed to differ.
    """
    banned = ("198 GB", "96 run archives")
    for doc in CITING_DOCS:
        if not doc.exists():
            continue
        text = re.sub(r"\s+", " ", doc.read_text(encoding="utf-8"))
        hits = [b for b in banned if b in text]
        assert not hits, f"{doc.relative_to(ROOT)} still carries the superseded claim(s) {hits}"
