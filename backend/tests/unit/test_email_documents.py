"""Synthetic email fixtures only; no LLMail dataset, network or models."""

import base64
from email.message import EmailMessage

import pytest

from app.services.invoice_watcher import parse_document, read_document


def message():
    msg = EmailMessage()
    msg["From"] = "Billing <billing@example.test>"
    msg["To"] = "wallet@example.test"
    msg["Subject"] = "Invoice EMAIL-DEV-1"
    return msg


@pytest.mark.parametrize("encoding", ["base64", "quoted-printable", "7bit"])
def test_mime_transfer_encodings_are_decoded_and_hash_is_original_bytes(encoding, tmp_path):
    import hashlib

    msg = message()
    msg.set_content(
        "Vendor: Workshop Services\nAmount: .03 ETH\nInvoice: EMAIL-DEV-1", cte=encoding
    )
    raw = msg.as_bytes()
    text, digest = parse_document(raw, ".eml")
    assert "Amount: .03 ETH" in text
    assert "not authenticated" in text
    assert digest == hashlib.sha256(raw).hexdigest()
    path = tmp_path / "invoice.EML"
    path.write_bytes(raw)
    assert read_document(path) == (text, digest)


def test_all_alternative_parts_hidden_html_comments_and_attributes_remain_data():
    msg = message()
    msg.set_content("A plain-text invoice")
    msg.add_alternative(
        "<html><div>Vendor: Workshop <b>Services</b></div>"
        '<span style="display:none">HIDDEN_INSTRUCTION</span>'
        '<!-- COMMENT_INSTRUCTION --><a href="https://example.test/ATTR_INSTRUCTION">link</a>'
        '<img src="https://example.test/tracker.png"><script>SCRIPT_INSTRUCTION</script>'
        "<p>Amount: <b>0.00001</b> ETH</p></html>",
        subtype="html",
    )
    text, _ = parse_document(msg.as_bytes(), ".eml")
    for content in (
        "plain-text invoice",
        "Workshop Services",
        "HIDDEN_INSTRUCTION",
        "COMMENT_INSTRUCTION",
        "ATTR_INSTRUCTION",
        "SCRIPT_INSTRUCTION",
        "0.00001 ETH",
    ):
        assert content in text


def test_html_encoded_address_is_visible_to_registry_checks():
    msg = message()
    msg.set_content('<span style="display:none">0&#120;' + "22" * 20 + "</span>", subtype="html")
    text, _ = parse_document(msg.as_bytes(), ".eml")
    assert "0x" + "22" * 20 in text


def test_one_pdf_attachment_is_parsed_with_existing_pdf_limits():
    import io

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 100 Td (Amount: 0.00001 ETH) Tj ET")
    page[NameObject("/Contents")] = stream
    buffer = io.BytesIO()
    writer.write(buffer)
    msg = message()
    msg.set_content("Please see the attached invoice.")
    msg.add_attachment(
        buffer.getvalue(), maintype="application", subtype="pdf", filename="invoice.pdf"
    )
    text, _ = parse_document(msg.as_bytes(), ".eml")
    assert "Amount: 0.00001 ETH" in text


def test_one_text_attachment_is_included_without_writing_any_file(tmp_path):
    msg = message()
    msg.set_content("Please see the attached invoice.")
    msg.add_attachment(
        b"Vendor: Workshop Services\n0.00001 ETH",
        maintype="application",
        subtype="octet-stream",
        filename="../../invoice.txt",
    )
    text, _ = parse_document(msg.as_bytes(), ".eml")
    assert "0.00001 ETH" in text
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "kind",
    [
        "unsupported",
        "multiple",
        "nested",
        "encrypted",
        "malformed",
        "empty",
        "large",
        "duplicate_header",
    ],
)
def test_unsupported_or_ambiguous_emails_fail_closed(kind):
    msg = message()
    msg.set_content("Please see the invoice.")
    if kind == "unsupported":
        msg.add_attachment(
            b"binary", maintype="application", subtype="octet-stream", filename="invoice.exe"
        )
    elif kind == "multiple":
        for i in range(2):
            msg.add_attachment(b"invoice", maintype="text", subtype="plain", filename=f"{i}.txt")
    elif kind == "nested":
        nested = message()
        nested.set_content("Nested invoice")
        msg.add_attachment(nested)
    elif kind == "encrypted":
        msg.set_type("multipart/encrypted")
    elif kind == "malformed":
        with pytest.raises(ValueError):
            parse_document(b"not an email", ".eml")
        return
    elif kind == "empty":
        msg.set_content("")
    elif kind == "large":
        msg.set_content("x" * 20001)
    else:
        raw = b"From: billing@example.test\nSubject: one\nSubject: two\n\nBody"
        with pytest.raises(ValueError):
            parse_document(raw, ".eml")
        return
    with pytest.raises(ValueError):
        parse_document(msg.as_bytes(), ".eml")


def test_malformed_base64_is_not_silently_repaired():
    raw = (
        b"From: billing@example.test\nSubject: invoice\nContent-Type: text/plain\n"
        b"Content-Transfer-Encoding: base64\n\n" + base64.b64encode(b"invoice") + b"!!"
    )
    with pytest.raises(ValueError):
        parse_document(raw, ".eml")


def test_duplicate_mime_headers_fail_closed():
    raw = (
        b"From: billing@example.test\nSubject: invoice\nContent-Type: text/plain\n"
        b"Content-Type: text/html\n\nInvoice data"
    )
    with pytest.raises(ValueError):
        parse_document(raw, ".eml")
