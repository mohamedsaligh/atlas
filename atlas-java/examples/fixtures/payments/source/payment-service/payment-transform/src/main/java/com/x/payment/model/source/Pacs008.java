package com.x.payment.model.source;

public class Pacs008 {
    private String msgId;
    private String dbtrIban;
    private String cdtrIban;
    private String amount;
    private String currency;

    public String getMsgId() { return msgId; }
    public void setMsgId(String v) { this.msgId = v; }

    public String getDbtrIban() { return dbtrIban; }
    public void setDbtrIban(String v) { this.dbtrIban = v; }

    public String getCdtrIban() { return cdtrIban; }
    public void setCdtrIban(String v) { this.cdtrIban = v; }

    public String getAmount() { return amount; }
    public void setAmount(String v) { this.amount = v; }

    public String getCurrency() { return currency; }
    public void setCurrency(String v) { this.currency = v; }
}
