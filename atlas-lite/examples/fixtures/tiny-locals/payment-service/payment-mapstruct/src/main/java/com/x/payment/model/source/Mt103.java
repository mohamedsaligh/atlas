package com.x.payment.model.source;

public class Mt103 {
    private Header header;
    public Header getHeader() { return header; }

    public static class Header {
        private String channelName;
        private String channelFormat;
        public String getChannelName() { return channelName; }
        public String getChannelFormat() { return channelFormat; }
    }
}
