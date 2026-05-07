package com.x.payment.mapper.common;

import com.x.payment.model.local.LocalDomain;
import com.x.payment.model.source.Mt103;

/**
 * Exercises P0 fixes:
 *   - Wrapper-call source path recursion: target.setX(Util.normalize(src.getY()))
 *     should produce source.path = "y" (not null).
 *   - Helper mutator detection: Helper.update(target.getZ()) should emit a
 *     synthetic kind=enrichment edge with target.path = "z".
 */
public class QualifiedAndHelperMapper {

    public LocalDomain toLocal(Mt103 src) {
        LocalDomain target = new LocalDomain();
        target.setTxnRef(QualifierUtil.normalize(src.getField20()));        // wrapper recursion
        target.setChannel(QualifierUtil.toUpper("swift"));                  // wrapper, but no source param
        AddressHelper.fixAccount(target.getDbtrAcct());                     // helper mutator (enrichment)
        return target;
    }

    /** Simulates a static qualifier helper. Real codebases use Qualifiers.X.class. */
    static final class QualifierUtil {
        static String normalize(String s) { return s == null ? null : s.trim(); }
        static String toUpper(String s) { return s == null ? null : s.toUpperCase(); }
    }

    /** Simulates a static post-processing helper mutator. */
    static final class AddressHelper {
        static void fixAccount(LocalDomain.Account acct) {
            if (acct != null && acct.getIban() != null) {
                acct.setIban(acct.getIban().replaceAll("\\s+", ""));
            }
        }
    }
}
