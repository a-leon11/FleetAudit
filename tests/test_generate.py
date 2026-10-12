import hashlib

from fleetaudit.generate import generate, write


def _digest(tmp_path, seed, name):
    write(generate(seed), tmp_path / name)
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted((tmp_path / name).iterdir())}


def test_same_seed_same_book(tmp_path):
    assert _digest(tmp_path, 3, "a") == _digest(tmp_path, 3, "b")


def test_different_seed_different_book(tmp_path):
    assert _digest(tmp_path, 3, "a")["contracts.csv"] != _digest(tmp_path, 4, "b")["contracts.csv"]


def test_every_pattern_is_planted(truth):
    for pattern, ids in truth["contracts"].items():
        assert ids, pattern
    for pattern, ids in truth["lookalikes"].items():
        assert ids, pattern
    assert len(truth["dealers"]["epd_cluster"]) == 2
    assert len(truth["customers"]["exposure_breach"]) == 3


def test_patterns_do_not_overlap(truth):
    seen = {}
    for pattern, ids in list(truth["contracts"].items()) + list(truth["lookalikes"].items()):
        for cid in ids:
            if cid.startswith("FC-"):
                assert cid not in seen, f"{cid} in {seen.get(cid)} and {pattern}"
                seen[cid] = pattern


def test_data_quality_gate_passes(audit):
    assert [(n, f) for n, f in audit.dq if f] == []
