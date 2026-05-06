from __future__ import annotations

from pathlib import Path

from atlas_aggregator.business_key import parse


REPO = Path(__file__).resolve().parents[3]


def test_parse_json_schema_extracts_x_atlas_business_key():
    schema = REPO / "examples/fixtures/payments/source/payment-service/payment-transform/src/main/resources/LocalDomain.json"
    out = parse(schema, "json-schema")
    assert out["txnRef"] == "TransactionReference"
    assert out["dbtrAcct.iban"] == "DebtorIBAN"
    assert out["amt.value"] == "Amount"


def test_parse_xsd_extracts_business_key_via_appinfo():
    schema = REPO / "examples/fixtures/payments/source/payment-service/payment-transform/src/main/resources/SWIFT_MT103.xsd"
    out = parse(schema, "xsd")
    assert out["field_50K"] == "DebtorIBAN"
    assert out["field_32A.amount"] == "Amount"
    assert out["field_32A.currency"] == "Currency"


def test_unknown_kind_returns_empty():
    schema = REPO / "examples/fixtures/payments/source/payment-service/payment-transform/src/main/resources/LocalDomain.json"
    assert parse(schema, "unknown-kind") == {}
