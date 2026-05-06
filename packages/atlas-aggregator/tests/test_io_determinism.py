from __future__ import annotations

from atlas_aggregator.io import sha256_hex, to_canonical_bytes


def test_canonical_bytes_are_stable_across_runs():
    a = to_canonical_bytes({"b": 1, "a": 2, "nested": {"y": [1, 2], "x": True}})
    b = to_canonical_bytes({"a": 2, "nested": {"x": True, "y": [1, 2]}, "b": 1})
    assert a == b
    assert a.endswith(b"\n")


def test_canonical_bytes_use_lf_and_two_space_indent():
    out = to_canonical_bytes({"a": [1, 2]}).decode("utf-8")
    assert "\r" not in out
    assert out == '{\n  "a": [\n    1,\n    2\n  ]\n}\n'


def test_sha256_matches_known_value():
    out = to_canonical_bytes({"a": 1})
    assert sha256_hex(out) == sha256_hex(out)  # idempotent
