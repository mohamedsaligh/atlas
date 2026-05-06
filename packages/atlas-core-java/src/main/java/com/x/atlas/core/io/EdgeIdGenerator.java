package com.x.atlas.core.io;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/**
 * Deterministic edge id: {@code <service>.<pair>.e_<sha1(payload)[:8]>}.
 *
 * <p>Same inputs → same id, regardless of host, run order, or extractor.
 * The id is stable across reruns as long as file path, line, target, and
 * source paths are unchanged.
 */
public final class EdgeIdGenerator {

    private EdgeIdGenerator() {}

    public static String edgeId(
            String service,
            String pairId,
            String filePath,
            int line,
            String targetPath,
            String sourcePath
    ) {
        String payload = String.join("\n",
                nullSafe(filePath),
                Integer.toString(line),
                nullSafe(targetPath),
                nullSafe(sourcePath));
        String hash = sha1Hex(payload).substring(0, 8);
        return service + "." + pairId + ".e_" + hash;
    }

    private static String nullSafe(String s) { return s == null ? "" : s; }

    private static String sha1Hex(String s) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-1");
            byte[] digest = md.digest(s.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(digest.length * 2);
            for (byte b : digest) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-1 unavailable", e);
        }
    }
}
