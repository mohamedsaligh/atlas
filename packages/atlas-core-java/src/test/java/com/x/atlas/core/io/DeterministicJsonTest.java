package com.x.atlas.core.io;

import static org.assertj.core.api.Assertions.assertThat;

import com.x.atlas.core.model.*;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class DeterministicJsonTest {

    @Test
    void same_value_serialises_byte_identically_twice() {
        Edge e = sampleEdge();
        byte[] a = DeterministicJson.toBytes(e);
        byte[] b = DeterministicJson.toBytes(e);
        assertThat(a).isEqualTo(b);
    }

    @Test
    void output_ends_with_lf_newline() {
        byte[] bytes = DeterministicJson.toBytes(sampleEdge());
        assertThat(bytes[bytes.length - 1]).isEqualTo((byte) '\n');
    }

    @Test
    void manifest_checksum_round_trips() {
        Manifest m = new Manifest(
                "0.1.0", Manifest.CURRENT_SCHEMA_VERSION,
                "payments-platform", "payment-service", "mt103_to_local",
                new Manifest.ManifestGit("ssh://git/r", "0".repeat(40), "main"),
                new Manifest.SchemaRef("MT103", "schemas/mt103.xsd", "xsd"),
                new Manifest.SchemaRef("LocalDomain", "schemas/local.json", "json-schema"),
                List.of(new Manifest.ExtractorEntry("mapstruct", "0.1.0", null)),
                List.of(sampleEdge()),
                new Manifest.Stats(1, 1, 1, Map.of("field_copy", 1), Map.of("mapstruct", 1)),
                ""
        );
        Manifest stamped = ManifestChecksum.stamp(m);
        assertThat(stamped.checksum()).matches("^[0-9a-f]{64}$");
        assertThat(ManifestChecksum.verify(stamped)).isTrue();
    }

    private Edge sampleEdge() {
        return Edge.builder()
                .edgeId("payment-service.mt103_to_local.e_abcdef12")
                .mapperId("com.x.payment.mapper.common.SwiftMt103ToLocalDomainMapperImpl")
                .mapperKind("mapstruct")
                .kind(EdgeKind.FIELD_COPY)
                .source(new FieldRef("com.x.payment.model.source.Mt103", "field_50K", "schemas/mt103.xsd"))
                .target(new FieldRef("com.x.payment.model.local.LocalDomain", "dbtr.acct.iban", "schemas/local.json"))
                .expression("src.getField50K()")
                .scope(Scope.ofCommon())
                .git(new GitRef("ssh://git/r", "0".repeat(40), "Foo.java", 1))
                .confidence(Confidence.HIGH)
                .build();
    }
}
