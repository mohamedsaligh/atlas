package com.x.atlas.core.scope;

import static org.assertj.core.api.Assertions.assertThat;

import com.x.atlas.core.model.Scope;
import com.x.atlas.core.spi.ExtractorContext.ScopeRule;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class ScopeInferenceEngineTest {

    @Test
    void common_path_marked_as_common() {
        Scope s = engine().infer(Path.of("payment-transform/src/main/java/com/x/payment/mapper/common/Foo.java"));
        assertThat(s.common()).isTrue();
        assertThat(s.country()).isNull();
    }

    @Test
    void country_clearing_captured_and_normalised() {
        Scope s = engine().infer(Path.of("payment-transform/src/main/java/com/x/payment/mapper/sg/sg-fast/InwardMapper.java"));
        assertThat(s.country()).isEqualTo("SG");
        assertThat(s.clearing()).isEqualTo("SG_FAST");
    }

    @Test
    void country_only_when_no_clearing() {
        Scope s = engine().infer(Path.of("payment-transform/src/main/java/com/x/payment/mapper/in/SomeMapper.java"));
        assertThat(s.country()).isEqualTo("IN");
        assertThat(s.clearing()).isNull();
    }

    @Test
    void unmatched_path_returns_empty_scope() {
        Scope s = engine().infer(Path.of("some/unrelated/path/Foo.java"));
        assertThat(s.common()).isNull();
        assertThat(s.country()).isNull();
    }

    @Test
    void glob_to_regex_handles_doublestar_singlestar_and_named_capture() {
        String r = ScopeInferenceEngine.globToRegex("**/mapper/{country}/{clearing}/**");
        assertThat(r).contains("(?<country>");
        assertThat(r).contains("(?<clearing>");
        assertThat(r).startsWith("^.*");
        assertThat(r).endsWith(".*$");
    }

    private ScopeInferenceEngine engine() {
        return new ScopeInferenceEngine(List.of(
                new ScopeRule("**/mapper/common/**", Map.of("common", true), List.of()),
                new ScopeRule("**/mapper/{country}/{clearing}/**", null, List.of("country", "clearing")),
                new ScopeRule("**/mapper/{country}/**", null, List.of("country"))
        ));
    }
}
