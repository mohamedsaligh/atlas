package com.x.payment.mapper.common;

import com.x.payment.model.local.LocalDomain;
import com.x.payment.model.source.Mt103;
import com.x.payment.qualifier.QualifierDefinitions;
import com.x.payment.util.PurposeUtil;
import javax.annotation.processing.Generated;

@Generated(value = "org.mapstruct.ap.MappingProcessor")
public class QualifiedMapperImpl implements QualifiedMapper {

    private QualifierDefinitions qualifiers = new QualifierDefinitions();

    @Override
    public LocalDomain toLocal(Mt103 src) {
        if (src == null) {
            return null;
        }
        LocalDomain localDomain = new LocalDomain();
        // Direct getter chain — fast path.
        localDomain.setIban(src.getField50K());
        // Qualifier-wrapped — needs resolver to follow into QualifierDefinitions.
        localDomain.setTxnRef(qualifiers.referenceEndToEndIdentification(src));
        localDomain.setBeneficiary(qualifiers.creditorName(src));
        // Static helper — needs resolver to follow into PurposeUtil.
        localDomain.setPurpose(PurposeUtil.extract(src));
        // Constant.
        localDomain.setChannel("SWIFT");
        return localDomain;
    }
}
