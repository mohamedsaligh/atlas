package com.x.payment.util;

import com.x.payment.model.source.Mt103;

/**
 * Static utility helper. Atlas-lite's static_helper resolver follows it
 * the same way it follows qualifier instance methods.
 */
public final class PurposeUtil {
    private PurposeUtil() {}

    public static String extract(Mt103 mt103) {
        return mt103.getField70();
    }
}
