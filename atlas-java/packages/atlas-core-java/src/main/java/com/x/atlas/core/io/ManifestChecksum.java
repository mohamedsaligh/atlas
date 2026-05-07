package com.x.atlas.core.io;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.x.atlas.core.model.CoverageManifest;
import com.x.atlas.core.model.Manifest;

/**
 * Computes and stamps the {@code checksum} field on manifests.
 *
 * <p>Strategy: serialise the value to canonical bytes with the {@code checksum}
 * field cleared, hash with SHA-256, then return a copy with the hash inserted.
 */
public final class ManifestChecksum {

    private ManifestChecksum() {}

    public static Manifest stamp(Manifest m) {
        Manifest blank = new Manifest(
                m.atlasVersion(), m.schemaVersion(),
                m.projectId(), m.repoId(), m.pairId(),
                m.git(), m.source(), m.target(),
                m.extractors(), m.edges(), m.stats(),
                ""
        );
        String hash = DeterministicJson.sha256(blank);
        return new Manifest(
                m.atlasVersion(), m.schemaVersion(),
                m.projectId(), m.repoId(), m.pairId(),
                m.git(), m.source(), m.target(),
                m.extractors(), m.edges(), m.stats(),
                hash
        );
    }

    public static CoverageManifest stamp(CoverageManifest c) {
        CoverageManifest blank = new CoverageManifest(
                c.schemaVersion(), c.projectId(), c.repoId(), c.pairId(),
                c.extractedAt(), c.gitSha(),
                c.filesScanned(), c.mappersDetected(), c.edgesEmitted(),
                c.byMapperKind(), c.byEdgeKind(),
                c.unparseableFiles(), c.unmatchedTargetFields(),
                c.ignoredByAnnotation(), c.extractorVersions(),
                c.drift(), ""
        );
        String hash = DeterministicJson.sha256(blank);
        return new CoverageManifest(
                c.schemaVersion(), c.projectId(), c.repoId(), c.pairId(),
                c.extractedAt(), c.gitSha(),
                c.filesScanned(), c.mappersDetected(), c.edgesEmitted(),
                c.byMapperKind(), c.byEdgeKind(),
                c.unparseableFiles(), c.unmatchedTargetFields(),
                c.ignoredByAnnotation(), c.extractorVersions(),
                c.drift(), hash
        );
    }

    /** Verifies a manifest's stored checksum matches its content. */
    public static boolean verify(Manifest m) {
        return stamp(m).checksum().equals(m.checksum());
    }

    public static boolean verify(CoverageManifest c) {
        return stamp(c).checksum().equals(c.checksum());
    }

    /** Strip checksum from a JsonNode in place; helper for Python-side parity. */
    public static void clearChecksum(JsonNode root) {
        if (root instanceof ObjectNode obj) {
            obj.put("checksum", "");
        }
    }
}
