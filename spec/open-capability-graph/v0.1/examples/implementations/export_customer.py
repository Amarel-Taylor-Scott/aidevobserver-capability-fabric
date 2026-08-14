"""Illustrative lossless field adapter for the OCG example."""


def export_customer(record: dict[str, str]) -> dict[str, str]:
    return {"name": record["name"], "email_address": record["email"]}
