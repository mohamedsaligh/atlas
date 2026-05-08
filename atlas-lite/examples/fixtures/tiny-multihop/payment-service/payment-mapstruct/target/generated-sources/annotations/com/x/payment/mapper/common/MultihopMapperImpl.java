package com.x.payment.mapper.common;

import com.x.payment.model.local.LocalDomain;
import com.x.payment.model.source.Mt103;
import com.x.payment.qualifier.QualifierDefinitions;
import javax.annotation.processing.Generated;

@Generated(value = "org.mapstruct.ap.MappingProcessor")
public class MultihopMapperImpl implements MultihopMapper {

    private QualifierDefinitions qualifiers = new QualifierDefinitions();

    @Override
    public LocalDomain toLocal(Mt103 src) {
        if (src == null) {
            return null;
        }
        LocalDomain localDomain = new LocalDomain();
        // qualifier (instance) -> static helper -> param.getX().getY()
        // Resolves to: agentBic <- txInfo.financialInstId.bic
        localDomain.setAgentBic(qualifiers.getAgentCpa(src.getTxInfo()));
        return localDomain;
    }
}
