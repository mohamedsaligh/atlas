package com.x.payment.mapper.common;

import com.x.payment.model.local.LocalDomain;
import com.x.payment.model.source.Mt103;

public interface MultihopMapper {
    LocalDomain toLocal(Mt103 src);
}
