package com.x.atlas.core.io;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.core.util.DefaultIndenter;
import com.fasterxml.jackson.core.util.DefaultPrettyPrinter;
import com.fasterxml.jackson.core.util.Separators;
import com.fasterxml.jackson.databind.MapperFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectWriter;
import com.fasterxml.jackson.databind.SerializationFeature;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/**
 * Single source of truth for JSON output formatting and parsing.
 *
 * <p>Determinism contract:
 * <ul>
 *   <li>Sorted keys</li>
 *   <li>2-space indent, LF newlines</li>
 *   <li>UTF-8, no BOM</li>
 *   <li>Trailing newline</li>
 *   <li>Absent / null fields suppressed (Jackson NON_ABSENT)</li>
 * </ul>
 */
public final class DeterministicJson {

    private DeterministicJson() {}

    private static final ObjectMapper MAPPER = build();

    private static ObjectMapper build() {
        ObjectMapper m = new ObjectMapper();
        m.setSerializationInclusion(JsonInclude.Include.NON_ABSENT);
        m.configure(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS, true);
        m.configure(MapperFeature.SORT_PROPERTIES_ALPHABETICALLY, true); // alphabetical for cross-language parity
        m.configure(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS, false);
        return m;
    }

    public static ObjectMapper mapper() { return MAPPER; }

    public static ObjectWriter writer() {
        DefaultIndenter indenter = new DefaultIndenter("  ", "\n");
        Separators sep = Separators.createDefaultInstance()
                .withObjectFieldValueSpacing(Separators.Spacing.AFTER)
                .withObjectEntrySpacing(Separators.Spacing.NONE);
        DefaultPrettyPrinter pp = new DefaultPrettyPrinter()
                .withObjectIndenter(indenter)
                .withArrayIndenter(indenter)
                .withSeparators(sep);
        return MAPPER.writer(pp);
    }

    /** Serialise to deterministic UTF-8 bytes with trailing newline. */
    public static byte[] toBytes(Object value) {
        try {
            String s = writer().writeValueAsString(value);
            // Jackson renders empty arrays/objects as "[ ]" / "{ }" — Python writes
            // them as "[]" / "{}". Normalise to Python form for cross-language parity.
            s = s.replace("[ ]", "[]").replace("{ }", "{}");
            if (!s.endsWith("\n")) s += "\n";
            return s.getBytes(StandardCharsets.UTF_8);
        } catch (Exception e) {
            throw new RuntimeException("serialize failed", e);
        }
    }

    public static void writeFile(Path file, Object value) throws IOException {
        Files.createDirectories(file.getParent());
        // Atomic temp + rename to avoid half-written files.
        Path tmp = file.resolveSibling(file.getFileName() + ".tmp");
        Files.write(tmp, toBytes(value));
        Files.move(tmp, file, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
    }

    /** SHA-256 of the canonical-bytes serialization. */
    public static String sha256(Object value) {
        return sha256(toBytes(value));
    }

    public static String sha256(byte[] bytes) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(md.digest(bytes));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }
}
