package com.x.payment.mapper.common;

import com.x.payment.model.local.LocalDomain;
import com.x.payment.model.source.Mt103;
import com.x.payment.model.source.Pacs008;
import org.mapstruct.Mapper;
import org.mapstruct.Mapping;

/**
 * Multi-parameter MapStruct mapper. Each {@code @Mapping(source=...)} routes
 * through the parameter named on the LHS of the dotted path. Atlas extractor
 * binds each parameter as its own source.
 */
@Mapper(componentModel = "default")
public interface CombinedToLocalDomainMapper {

    @Mapping(target = "txnRef",        source = "mt103.field20")
    @Mapping(target = "dbtrAcct.iban", source = "mt103.field50K")
    @Mapping(target = "amt.value",     source = "pacs.amount")
    @Mapping(target = "amt.ccy",       source = "pacs.currency")
    @Mapping(target = "channel",       constant = "COMBINED")
    LocalDomain combine(Mt103 mt103, Pacs008 pacs);
}
