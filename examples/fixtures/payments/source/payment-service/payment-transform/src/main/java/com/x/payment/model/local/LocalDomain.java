package com.x.payment.model.local;

public class LocalDomain {
    private String txnRef;
    private Account dbtrAcct;
    private Account cdtrAcct;
    private Amount amt;
    private String channel;          // constant in some mappers
    private String purposeOfPayment; // unmapped target field

    public String getTxnRef() { return txnRef; }
    public void setTxnRef(String v) { this.txnRef = v; }

    public Account getDbtrAcct() { return dbtrAcct; }
    public void setDbtrAcct(Account v) { this.dbtrAcct = v; }

    public Account getCdtrAcct() { return cdtrAcct; }
    public void setCdtrAcct(Account v) { this.cdtrAcct = v; }

    public Amount getAmt() { return amt; }
    public void setAmt(Amount v) { this.amt = v; }

    public String getChannel() { return channel; }
    public void setChannel(String v) { this.channel = v; }

    public String getPurposeOfPayment() { return purposeOfPayment; }
    public void setPurposeOfPayment(String v) { this.purposeOfPayment = v; }

    public static class Account {
        private String iban;
        public String getIban() { return iban; }
        public void setIban(String v) { this.iban = v; }
    }

    public static class Amount {
        private String value;
        private String ccy;
        private String valueDate;

        public String getValue() { return value; }
        public void setValue(String v) { this.value = v; }

        public String getCcy() { return ccy; }
        public void setCcy(String v) { this.ccy = v; }

        public String getValueDate() { return valueDate; }
        public void setValueDate(String v) { this.valueDate = v; }
    }
}
