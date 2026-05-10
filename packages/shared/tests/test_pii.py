"""Unit tests for PII detection and redaction."""

import pytest

from lex_agents_shared.pii import contains_pii, redact_pii


class TestRedactDni:
    def test_valid_dni_is_redacted(self) -> None:
        assert redact_pii("El titular es 12345678Z") == "El titular es [PII:DNI]"

    def test_lowercase_letter_redacted(self) -> None:
        assert "[PII:DNI]" in redact_pii("DNI: 87654321q")

    def test_partial_match_not_redacted(self) -> None:
        # 7 digits + letter should NOT match DNI (needs exactly 8 digits)
        result = redact_pii("código 1234567A")
        assert "[PII:DNI]" not in result


class TestRedactNie:
    def test_nie_x_series(self) -> None:
        assert "[PII:NIE]" in redact_pii("NIE X1234567L")

    def test_nie_y_series(self) -> None:
        assert "[PII:NIE]" in redact_pii("NIE Y9876543Z")

    def test_nie_z_series(self) -> None:
        assert "[PII:NIE]" in redact_pii("Z0000001R")


class TestRedactIban:
    def test_spanish_iban(self) -> None:
        result = redact_pii("IBAN: ES9121000418450200051332")
        assert "[PII:IBAN]" in result

    def test_iban_with_spaces(self) -> None:
        result = redact_pii("ES91 2100 0418 4502 0005 1332")
        assert "[PII:IBAN]" in result


class TestRedactEmail:
    def test_standard_email(self) -> None:
        assert "[PII:EMAIL]" in redact_pii("Contacto: usuario@ejemplo.com")

    def test_email_with_subdomain(self) -> None:
        assert "[PII:EMAIL]" in redact_pii("test.user@mail.banco.es")


class TestRedactPhone:
    def test_mobile_number(self) -> None:
        assert "[PII:PHONE]" in redact_pii("Teléfono: 612345678")

    def test_number_with_country_code(self) -> None:
        assert "[PII:PHONE]" in redact_pii("+34 912345678")


class TestContainsPii:
    def test_clean_text(self) -> None:
        assert not contains_pii("Esta es una consulta sobre el artículo 92 del CRR.")

    def test_text_with_email(self) -> None:
        assert contains_pii("Remitente: abogado@bufete.es")

    def test_text_with_dni(self) -> None:
        assert contains_pii("El cliente 12345678Z presentó reclamación.")


class TestMultiplePii:
    def test_all_types_in_one_string(self) -> None:
        text = "DNI 12345678Z email user@test.com tel 666111222"
        result = redact_pii(text)
        assert "[PII:DNI]" in result
        assert "[PII:EMAIL]" in result
        assert "[PII:PHONE]" in result
        assert "12345678Z" not in result
        assert "user@test.com" not in result

    def test_idempotent_on_already_redacted(self) -> None:
        text = "[PII:EMAIL] consulta sobre capital"
        # Already-redacted tokens should not be double-redacted
        assert redact_pii(text) == text
