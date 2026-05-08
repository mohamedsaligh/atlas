package com.x.payment.util;

import com.x.payment.model.source.FinancialInstId;

public class MapperQualifierUtil {
    public static String bicFromInst(FinancialInstId fi) {
        return fi.getBic();
    }
}
