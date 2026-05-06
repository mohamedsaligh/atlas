package com.x.payment.mapper.common;

import com.x.payment.model.local.LocalDomain;
import com.x.payment.model.source.Mt103;
import org.mapstruct.Mapper;
import org.mapstruct.Mapping;

@Mapper(componentModel = "default")
public interface SwiftMt103ToLocalDomainMapper {

    @Mapping(target = "txnRef",        source = "field20")
    @Mapping(target = "dbtrAcct.iban", source = "field50K")
    @Mapping(target = "cdtrAcct.iban", source = "field59")
    @Mapping(target = "amt.value",     source = "field32A.amount")
    @Mapping(target = "amt.ccy",       source = "field32A.currency")
    @Mapping(target = "amt.valueDate", source = "field32A.valueDate")
    @Mapping(target = "channel",       constant = "SWIFT")
    LocalDomain toLocal(Mt103 src);
}
