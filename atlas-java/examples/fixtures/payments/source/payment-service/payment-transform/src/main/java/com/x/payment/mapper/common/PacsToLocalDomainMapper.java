package com.x.payment.mapper.common;

import com.x.payment.model.local.LocalDomain;
import com.x.payment.model.source.Pacs008;

/**
 * Plain-Java mapper. Tests the {@code plain-java} extractor's setter pathway.
 */
public class PacsToLocalDomainMapper {

    public LocalDomain toLocal(Pacs008 src) {
        LocalDomain target = new LocalDomain();
        target.setTxnRef(src.getMsgId());

        LocalDomain.Account dbtr = new LocalDomain.Account();
        dbtr.setIban(src.getDbtrIban());
        target.setDbtrAcct(dbtr);

        LocalDomain.Account cdtr = new LocalDomain.Account();
        cdtr.setIban(src.getCdtrIban());
        target.setCdtrAcct(cdtr);

        LocalDomain.Amount amt = new LocalDomain.Amount();
        amt.setValue(src.getAmount());
        amt.setCcy(src.getCurrency());
        target.setAmt(amt);

        target.setChannel("ISO20022");
        return target;
    }
}
