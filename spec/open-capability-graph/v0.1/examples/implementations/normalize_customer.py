"""Illustrative deterministic implementation for the OCG example."""


def normalize_customer(record: dict[str, str]) -> dict[str, str]:
    email = record["email"].strip()
    local_part, separator, domain = email.rpartition("@")
    normalized_email = f"{local_part}{separator}{domain.lower()}"
    return {
        "name": " ".join(record["full_name"].split()),
        "email": normalized_email,
    }
