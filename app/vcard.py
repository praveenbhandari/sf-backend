"""RFC 2426 vCard 3.0 serialization for a stored contact."""

from __future__ import annotations

import re
import unicodedata

from app.models import Address, Contact

_PHOTO_DATA_URL = re.compile(
    r"^data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE,
)
_PHOTO_TYPE = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}
_NON_SLUG = re.compile(r"[^a-z0-9]+")

# vCard 3.0 physical lines SHOULD be folded at 75 octets (RFC 2425 §5.8.1).
_FOLD_OCTETS = 75


def filename_slug(full_name: str) -> str:
    """ASCII filename stem derived from the contact's full name."""
    ascii_name = unicodedata.normalize("NFKD", full_name).encode("ascii", "ignore").decode("ascii")
    slug = _NON_SLUG.sub("-", ascii_name.lower()).strip("-")
    return slug or "contact"


def build_vcard(contact: Contact) -> str:
    """Return a CRLF-delimited vCard 3.0 document for `contact`."""
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"FN:{_escape(contact.full_name)}",
        f"N:{_escape(contact.last_name)};{_escape(contact.first_name)};;;",
        f"EMAIL:{_escape(contact.email)}",
    ]
    if contact.phone:
        lines.append(f"TEL:{_escape(contact.phone)}")
    if contact.company:
        lines.append(f"ORG:{_escape(contact.company)}")
    if contact.job_title:
        lines.append(f"TITLE:{_escape(contact.job_title)}")
    if contact.notes:
        lines.append(f"NOTE:{_escape(contact.notes)}")
    for address in contact.addresses:
        lines.append(_adr(address))
    photo = _photo_line(contact.photo)
    if photo:
        lines.append(photo)
    lines.append("END:VCARD")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _adr(address: Address) -> str:
    kind = address.type.upper()
    street = _escape(address.address or "")
    city = _escape(address.city or "")
    state = _escape(address.state or "")
    postal = _escape(address.postal_code or "")
    country = _escape(address.country or "")
    return f"ADR;TYPE={kind}:;;{street};{city};{state};{postal};{country}"


def _photo_line(photo: str | None) -> str | None:
    if not photo:
        return None
    match = _PHOTO_DATA_URL.match(photo.strip())
    if not match:
        return None
    subtype = match.group(1).lower()
    payload = re.sub(r"\s+", "", match.group(2))
    if not payload:
        return None
    return f"PHOTO;ENCODING=b;TYPE={_PHOTO_TYPE[subtype]}:{payload}"


def _fold(line: str) -> str:
    """Fold a logical line into 75-octet physical lines with a leading space."""
    data = line.encode("utf-8")
    if len(data) <= _FOLD_OCTETS:
        return line
    chunks: list[str] = []
    offset = 0
    first = True
    length = len(data)
    while offset < length:
        limit = _FOLD_OCTETS if first else _FOLD_OCTETS - 1
        size = min(limit, length - offset)
        while size > 0:
            try:
                text = data[offset : offset + size].decode("utf-8")
                break
            except UnicodeDecodeError:
                size -= 1
        else:  # pragma: no cover - defensive; input is valid UTF-8
            size = 1
            text = data[offset : offset + size].decode("utf-8", errors="replace")
        chunks.append(text if first else f" {text}")
        offset += size
        first = False
    return "\r\n".join(chunks)
