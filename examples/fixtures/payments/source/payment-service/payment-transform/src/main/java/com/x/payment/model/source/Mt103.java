package com.x.payment.model.source;

public class Mt103 {
    private String field20;        // transaction reference
    private String field50K;       // ordering customer / IBAN
    private Field32A field32A;     // value date / currency / amount
    private String field59;        // beneficiary / IBAN

    public String getField20() { return field20; }
    public void setField20(String v) { this.field20 = v; }

    public String getField50K() { return field50K; }
    public void setField50K(String v) { this.field50K = v; }

    public Field32A getField32A() { return field32A; }
    public void setField32A(Field32A v) { this.field32A = v; }

    public String getField59() { return field59; }
    public void setField59(String v) { this.field59 = v; }

    public static class Field32A {
        private String valueDate;
        private String currency;
        private String amount;

        public String getValueDate() { return valueDate; }
        public void setValueDate(String v) { this.valueDate = v; }

        public String getCurrency() { return currency; }
        public void setCurrency(String v) { this.currency = v; }

        public String getAmount() { return amount; }
        public void setAmount(String v) { this.amount = v; }
    }
}
