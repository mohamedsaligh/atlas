package com.x.atlas.core.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;
import java.util.Map;

/**
 * One field-level lineage edge. Output of every extractor; the integration
 * seam of the whole system. The schema is authoritative — Java records mirror
 * {@code schemas/edge.schema.json}.
 *
 * @param edgeId          {@code <service>.<pair>.e_<sha1(file+line+target+source)[:8]>}
 * @param mapperId        Class FQN, or synthetic id for inline clusters.
 * @param mapperKind      Identifier of the extractor that produced this edge.
 * @param kind            RHS classification — see {@link EdgeKind}.
 * @param source          Source field reference; null when {@code kind} has no source.
 * @param target          Target field reference; required.
 * @param expression      Pretty-printed RHS AST snippet.
 * @param staticHelperFqn Set when {@code kind=static_call} or expression contains a static helper.
 * @param cardinality     Set when {@code kind=collection_map}.
 * @param branchCondition Set when {@code kind=conditional}; predicate AST snippet.
 * @param formatSpec      Encoder-specific shape: {@code {offset,length}} for fixedlen, {@code {tag}} for tagged.
 * @param scope           Tags inferred from package path.
 * @param git             Git anchor; required.
 * @param testIds         Test methods covering this edge.
 * @param confidence      Confidence band for downstream filtering.
 */
@JsonInclude(JsonInclude.Include.NON_ABSENT)
public record Edge(
        String edgeId,
        String mapperId,
        String mapperKind,
        EdgeKind kind,
        FieldRef source,
        FieldRef target,
        String expression,
        String staticHelperFqn,
        Cardinality cardinality,
        String branchCondition,
        Map<String, Object> formatSpec,
        Scope scope,
        GitRef git,
        List<String> testIds,
        Confidence confidence
) {

    public static Builder builder() { return new Builder(); }

    public static final class Builder {
        private String edgeId;
        private String mapperId;
        private String mapperKind;
        private EdgeKind kind;
        private FieldRef source;
        private FieldRef target;
        private String expression;
        private String staticHelperFqn;
        private Cardinality cardinality;
        private String branchCondition;
        private Map<String, Object> formatSpec;
        private Scope scope;
        private GitRef git;
        private List<String> testIds = List.of();
        private Confidence confidence = Confidence.HIGH;

        public Builder edgeId(String v)               { this.edgeId = v; return this; }
        public Builder mapperId(String v)             { this.mapperId = v; return this; }
        public Builder mapperKind(String v)           { this.mapperKind = v; return this; }
        public Builder kind(EdgeKind v)               { this.kind = v; return this; }
        public Builder source(FieldRef v)             { this.source = v; return this; }
        public Builder target(FieldRef v)             { this.target = v; return this; }
        public Builder expression(String v)           { this.expression = v; return this; }
        public Builder staticHelperFqn(String v)      { this.staticHelperFqn = v; return this; }
        public Builder cardinality(Cardinality v)     { this.cardinality = v; return this; }
        public Builder branchCondition(String v)      { this.branchCondition = v; return this; }
        public Builder formatSpec(Map<String, Object> v) { this.formatSpec = v; return this; }
        public Builder scope(Scope v)                 { this.scope = v; return this; }
        public Builder git(GitRef v)                  { this.git = v; return this; }
        public Builder testIds(List<String> v)        { this.testIds = v == null ? List.of() : v; return this; }
        public Builder confidence(Confidence v)       { this.confidence = v; return this; }

        public Edge build() {
            return new Edge(edgeId, mapperId, mapperKind, kind,
                    source, target, expression, staticHelperFqn,
                    cardinality, branchCondition, formatSpec,
                    scope, git, testIds, confidence);
        }
    }
}
