package com.x.payment.model.local;

public class LocalDomain {
    private String txnRef;
    private Account dbtrAcct;
    private Account cdtrAcct;
    private String channel;

    public String getTxnRef() { return txnRef; }
    public void setTxnRef(String v) { this.txnRef = v; }

    public Account getDbtrAcct() { return dbtrAcct; }
    public void setDbtrAcct(Account v) { this.dbtrAcct = v; }

    public Account getCdtrAcct() { return cdtrAcct; }
    public void setCdtrAcct(Account v) { this.cdtrAcct = v; }

    public String getChannel() { return channel; }
    public void setChannel(String v) { this.channel = v; }

    public static class Account {
        private String iban;
        public String getIban() { return iban; }
        public void setIban(String v) { this.iban = v; }
    }
}
