"""Safe serving of user-uploaded artifact blobs.

Serving user-controlled bytes with their own ``media_type`` and
``Content-Disposition: inline`` is a stored-XSS sink: an uploaded ``.html`` /
``.svg`` / ``.xml`` renders as a *document* on the API origin and can run
script against it. This helper neutralizes executable document types, forces a
download for them, and always sends anti-sniffing + sandbox headers.
"""

from __future__ import annotations

from fastapi import Response

# Types a browser executes scripts in when rendered as a top-level document.
# Served bytes of these types must never render on our origin.
_EXECUTABLE_MEDIA = {
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
    "text/xml",
    "application/xml",
}


def _bare_media(media_type: str | None) -> str:
    return (media_type or "application/octet-stream").split(";")[0].strip().lower()


def _safe_filename(name: str | None) -> str:
    # Strip CR/LF (header injection) + escape quote/backslash (RFC 6266 quoting).
    return (
        (name or "download")
        .replace("\r", "")
        .replace("\n", "")
        .replace("\\", "_")
        .replace('"', "_")
    )


def safe_blob_response(
    *,
    content: bytes,
    media_type: str | None,
    filename: str | None,
    inline: bool = False,
) -> Response:
    """Serve untrusted blob bytes without a stored-XSS-on-origin risk.

    - Executable document types (html/xhtml/svg/xml/``*+xml``) are neutralized
      to ``application/octet-stream`` and always forced to ``attachment``.
    - Everything else honors ``inline`` (so image/text/json previews still work).
    - Always sets ``X-Content-Type-Options: nosniff`` + a ``sandbox`` CSP so even
      a directly-navigated blob cannot execute script on this origin.
    """
    bare = _bare_media(media_type)
    dangerous = bare in _EXECUTABLE_MEDIA or bare.endswith("+xml")
    serve_media = "application/octet-stream" if dangerous else (media_type or "application/octet-stream")
    disposition = "inline" if (inline and not dangerous) else "attachment"
    return Response(
        content=content,
        media_type=serve_media,
        headers={
            "Content-Disposition": f'{disposition}; filename="{_safe_filename(filename)}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )
