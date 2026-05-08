package com.x.payment.mapper.common;

import com.x.payment.model.local.LocalDomain;
import com.x.payment.model.source.Mt103;
import javax.annotation.processing.Generated;
import java.util.ArrayList;

@Generated(value = "org.mapstruct.ap.MappingProcessor")
public class LocalsMapperImpl implements LocalsMapper {

    @Override
    public LocalDomain toLocal(Mt103 src) {
        if (src == null) {
            return null;
        }
        LocalDomain localDomain = new LocalDomain();
        // Local-var chasing: locals defined here, then assigned to setters.
        String channelName = src.getHeader().getChannelName();
        String channelFormat = src.getHeader().getChannelFormat();
        localDomain.setChannelName(channelName);
        localDomain.setChannelFormat(channelFormat);
        return localDomain;
    }
}
