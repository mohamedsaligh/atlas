package com.x.payment.mapper.common;

import com.x.payment.model.local.LocalDomain;
import com.x.payment.model.source.Mt103;
import javax.annotation.processing.Generated;

@Generated(value = "org.mapstruct.ap.MappingProcessor")
public class SwiftMt103ToLocalDomainMapperImpl implements SwiftMt103ToLocalDomainMapper {

    @Override
    public LocalDomain toLocal(Mt103 src) {
        if (src == null) {
            return null;
        }
        LocalDomain localDomain = new LocalDomain();
        localDomain.setDbtrAcct(mt103ToAccount(src));
        localDomain.setCdtrAcct(mt103ToAccount1(src));
        localDomain.setTxnRef(src.getField20());
        localDomain.setChannel("SWIFT");
        return localDomain;
    }

    protected LocalDomain.Account mt103ToAccount(Mt103 mt103) {
        if (mt103 == null) {
            return null;
        }
        LocalDomain.Account account = new LocalDomain.Account();
        account.setIban(mt103.getField50K());
        return account;
    }

    protected LocalDomain.Account mt103ToAccount1(Mt103 mt103) {
        if (mt103 == null) {
            return null;
        }
        LocalDomain.Account account = new LocalDomain.Account();
        account.setIban(mt103.getField59());
        return account;
    }
}
