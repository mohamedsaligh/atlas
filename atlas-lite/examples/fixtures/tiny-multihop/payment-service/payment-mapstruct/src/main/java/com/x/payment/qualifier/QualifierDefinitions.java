package com.x.payment.qualifier;

import com.x.payment.model.source.TxInfo;
import com.x.payment.util.MapperQualifierUtil;

public class QualifierDefinitions {

    public String getAgentCpa(TxInfo txInfo) {
        if (txInfo != null && txInfo.getFinancialInstId() != null) {
            return MapperQualifierUtil.bicFromInst(txInfo.getFinancialInstId());
        }
        return null;
    }
}
