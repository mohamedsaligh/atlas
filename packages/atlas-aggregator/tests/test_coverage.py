"""Coverage analysis tests: unmatched fields, x-atlas-ignore, synthetic unmapped edges."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from atlas_aggregator import business_key, coverage
from atlas_aggregator.models import (
    Edge,
    ExtractorEntry,
    FieldRef,
    GitRef,
    Manifest,
    ManifestGit,
    ManifestSchemaRef,
    Stats,
)


def _make_manifest(written_paths: list[str], target_schema_file: str) -> Manifest:
    edges = [
        Edge(
            edgeId=f"r.p.e_{i:08x}",
            mapperId="m",
            mapperKind="plain-java",
            kind="field_copy",
            source=FieldRef(type="S", path=f"s{i}", schemaFile="src.json"),
            target=FieldRef(type="T", path=p, schemaFile=target_schema_file),
            git=GitRef(repo="", sha="0" * 40, file="f.java", line=1),
            confidence="high",
        )
        for i, p in enumerate(written_paths)
    ]
    return Manifest(
        atlasVersion="0.1.0",
        schemaVersion=1,
        projectId="proj",
        repoId="r",
        pairId="p",
        git=ManifestGit(repo="", sha="0" * 40, branch="main"),
        source=ManifestSchemaRef(name="S", schemaFile="src.json", schemaKind="json-schema"),
        target=ManifestSchemaRef(name="T", schemaFile=target_schema_file, schemaKind="json-schema"),
        extractors=[ExtractorEntry(id="plain-java", version="0.1.0")],
        edges=edges,
        stats=Stats(filesScanned=1, mappersDetected=1, edgesEmitted=len(edges)),
        checksum="0" * 64,
    )


def test_unmatched_lists_declared_but_unwritten_paths():
    with tempfile.TemporaryDirectory() as d:
        schema = Path(d) / "t.json"
        schema.write_text(json.dumps({
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "string"},
                "c": {"type": "string"},
            },
        }))
        target_fields = business_key.enumerate_fields(schema, "json-schema")
        m = _make_manifest(["a"], target_schema_file="t.json")
        unmatched = coverage.compute_unmatched_per_manifest(m, target_fields)
        paths = [u.target_path for u in unmatched]
        assert paths == ["b", "c"]


def test_x_atlas_ignore_drops_field_from_denominator():
    with tempfile.TemporaryDirectory() as d:
        schema = Path(d) / "t.json"
        schema.write_text(json.dumps({
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "string", "x-atlas-ignore": True},
                "c": {"type": "string"},
            },
        }))
        target_fields = business_key.enumerate_fields(schema, "json-schema")
        assert target_fields["b"].ignored is True
        m = _make_manifest(["a"], target_schema_file="t.json")
        unmatched = coverage.compute_unmatched_per_manifest(m, target_fields)
        # b is ignored, so only c remains unmatched
        assert [u.target_path for u in unmatched] == ["c"]


def test_synthetic_unmapped_edges_have_kind_unmapped_and_no_source():
    with tempfile.TemporaryDirectory() as d:
        schema = Path(d) / "t.json"
        schema.write_text(json.dumps({
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        }))
        target_fields = business_key.enumerate_fields(schema, "json-schema")
        m = _make_manifest([], target_schema_file="t.json")
        unmatched = coverage.compute_unmatched_per_manifest(m, target_fields)
        synth = coverage.synthetic_unmapped_edges(m, unmatched)
        assert {e.target.path for e in synth} == {"a", "b"}
        assert all(e.kind == "unmapped" for e in synth)
        assert all(e.source is None for e in synth)
        assert all(e.mapperKind == "schema" for e in synth)


def test_nested_paths_enumerate_correctly():
    with tempfile.TemporaryDirectory() as d:
        schema = Path(d) / "t.json"
        schema.write_text(json.dumps({
            "type": "object",
            "properties": {
                "outer": {
                    "type": "object",
                    "properties": {
                        "inner": {"type": "string", "x-atlas-business-key": "Inner"},
                        "skip": {"type": "string", "x-atlas-ignore": True},
                    },
                },
            },
        }))
        fields = business_key.enumerate_fields(schema, "json-schema")
        assert "outer.inner" in fields
        assert fields["outer.inner"].business_key == "Inner"
        assert fields["outer.skip"].ignored is True
