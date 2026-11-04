"""Bounded EML-to-untrusted-text conversion. No rendering, links, mail or disk writes."""

import html
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path


class EmailText(HTMLParser):
    """Retain hidden node data; visibility and CSS never remove screening input."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "p", "div", "tr", "li", "td", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"p", "div", "tr", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")


def email_text(raw, attachment_parser):
    if b"\n\n" not in raw and b"\r\n\r\n" not in raw:
        raise ValueError("MALFORMED_EMAIL")
    message = BytesParser(policy=policy.default).parsebytes(raw)
    if not message.get("From") and not message.get("Subject"):
        raise ValueError("MALFORMED_EMAIL")
    headers = []
    for name in ("From", "To", "Reply-To", "Subject", "Date"):
        values = message.get_all(name, [])
        if len(values) > 1 or any(getattr(value, "defects", ()) for value in values):
            raise ValueError("AMBIGUOUS_EMAIL_HEADERS")
        if values:
            headers.append(f"{name}: {values[0]}")
    chunks = ["Email headers (untrusted, not authenticated):\n" + "\n".join(headers)]
    queue = [(message, 0)]
    parts, attachments, bodies = 0, 0, 0
    while queue:
        part, depth = queue.pop()
        parts += 1
        if depth > 8 or parts > 32:
            raise ValueError("EMAIL_STRUCTURE_TOO_COMPLEX")
        if part.defects:
            raise ValueError("MALFORMED_EMAIL")
        if any(
            len(part.get_all(name, [])) > 1
            for name in ("Content-Type", "Content-Transfer-Encoding", "Content-Disposition")
        ):
            raise ValueError("MALFORMED_EMAIL")
        content_type = part.get_content_type()
        if (
            content_type in {"multipart/encrypted", "multipart/signed"}
            or part.get_content_maintype() == "message"
        ):
            raise ValueError("UNSUPPORTED_EMAIL_CONTENT")
        if part.is_multipart():
            if part.get_content_disposition() == "attachment":
                raise ValueError("UNSUPPORTED_EMAIL_ATTACHMENT")
            children = part.get_payload()
            if not isinstance(children, list) or len(children) > 32:
                raise ValueError("EMAIL_STRUCTURE_TOO_COMPLEX")
            queue.extend((child, depth + 1) for child in reversed(children))
            continue
        filename = part.get_filename()
        is_attachment = part.get_content_disposition() == "attachment" or bool(filename)
        # Inline images are never interpreted, fetched, OCR'd or passed to the model.
        if part.get_content_maintype() == "image" and part.get_content_disposition() == "inline":
            continue
        if is_attachment or content_type == "application/pdf":
            attachments += 1
            if attachments > 1:
                raise ValueError("MULTIPLE_EMAIL_ATTACHMENTS")
            suffix = (
                Path(filename).suffix.lower()
                if filename
                else (".pdf" if content_type == "application/pdf" else ".txt")
            )
            if suffix not in {".txt", ".pdf"}:
                raise ValueError("UNSUPPORTED_EMAIL_ATTACHMENT")
            payload = part.get_payload(decode=True)
            if part.defects or not isinstance(payload, bytes):
                raise ValueError("MALFORMED_EMAIL")
            text, _ = attachment_parser(payload, suffix)
            chunks.append("Email invoice attachment (untrusted):\n" + text)
            continue
        if content_type not in {"text/plain", "text/html"}:
            raise ValueError("UNSUPPORTED_EMAIL_CONTENT")
        text = part.get_content(errors="strict")
        if part.defects or not isinstance(text, str):
            raise ValueError("MALFORMED_EMAIL")
        if not text.strip():
            continue
        bodies += 1
        if content_type == "text/html":
            parser = EmailText()
            parser.feed(text)
            parser.close()
            # Include source as well as text: comments, attributes, scripts and hidden
            # spans remain untrusted screening data, never active browser content.
            chunks.append("HTML email source (untrusted):\n" + html.unescape(text))
            chunks.append("HTML email text (untrusted):\n" + "".join(parser.parts))
        else:
            chunks.append("Plain email body (untrusted):\n" + text)
        if sum(map(len, chunks)) > 20000:
            raise ValueError("EMAIL_TEXT_TOO_LARGE")
    if not bodies and not attachments:
        raise ValueError("EMAIL_BODY_REQUIRED")
    text = "\n\n".join(chunks)
    if len(text) > 20000:
        raise ValueError("EMAIL_TEXT_TOO_LARGE")
    return text
