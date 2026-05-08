package com.x.payment.model.local;

public class LocalDomain {
    private String txnRef;
    private String iban;
    private String beneficiary;
    private String purpose;
    private String channel;

    public void setTxnRef(String v) { this.txnRef = v; }
    public void setIban(String v) { this.iban = v; }
    public void setBeneficiary(String v) { this.beneficiary = v; }
    public void setPurpose(String v) { this.purpose = v; }
    public void setChannel(String v) { this.channel = v; }
}
