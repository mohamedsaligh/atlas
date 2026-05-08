package com.x.payment.qualifier;

import com.x.payment.model.source.Mt103;

/**
 * Real-world MapStruct qualifier class. Each @Named-style method takes the
 * source object and returns a transformed value.
 */
public class QualifierDefinitions {

    public String referenceEndToEndIdentification(Mt103 mt103) {
        return mt103.getField20();
    }

    public String debtorIban(Mt103 mt103) {
        return mt103.getField50K();
    }

    public String creditorName(Mt103 mt103) {
        return mt103.getField59();
    }
}
