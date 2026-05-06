package com.x.atlas.core.io;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class EdgeIdGeneratorTest {

    @Test
    void same_inputs_produce_same_id() {
        String a = EdgeIdGenerator.edgeId("payment-service", "mt103_to_local",
                "src/main/java/Foo.java", 142, "dbtr.acct.iban", "field_50K");
        String b = EdgeIdGenerator.edgeId("payment-service", "mt103_to_local",
                "src/main/java/Foo.java", 142, "dbtr.acct.iban", "field_50K");
        assertThat(a).isEqualTo(b);
    }

    @Test
    void different_line_produces_different_id() {
        String a = EdgeIdGenerator.edgeId("payment-service", "p", "f.java", 1, "t", "s");
        String b = EdgeIdGenerator.edgeId("payment-service", "p", "f.java", 2, "t", "s");
        assertThat(a).isNotEqualTo(b);
    }

    @Test
    void id_pattern_matches_schema() {
        String id = EdgeIdGenerator.edgeId("payment-service", "mt103_to_local",
                "f.java", 1, "t", "s");
        assertThat(id).matches("^[a-z0-9-]+\\.[a-z0-9_-]+\\.e_[0-9a-f]{8}$");
    }

    @Test
    void null_source_path_does_not_throw() {
        String id = EdgeIdGenerator.edgeId("svc", "p", "f.java", 1, "t", null);
        assertThat(id).isNotNull();
    }
}
