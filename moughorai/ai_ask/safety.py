from __future__ import annotations

from collections.abc import Mapping, Sequence
import re

from moughorai.repository_report.safety import contains_absolute_path_text


_CODE_FENCE = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)
_SOURCE_SHAPED = re.compile(
    r"(?is)(?:\b(?:public|private|protected|static|final)\s+)*"
    r"(?:class|interface|enum|record)\s+[A-Za-z_$][A-Za-z0-9_$]*\s*\{.*?\}"
    r"|\b(?:return|import|package)\s+[^;\r\n]{1,512};"
)
_SOURCE_LINE = re.compile(
    r"(?im)(?:^|\n)\s*(?:"
    r"(?:async\s+)?def\s+[A-Za-z_][A-Za-z0-9_]*\s*\([^\r\n]*"
    r"|print\s*\([^\r\n]*"
    r"|(?:function|const|let|var)\s+[A-Za-z_$][A-Za-z0-9_$]*[^\r\n]*"
    r"|(?:public|private|protected)\s+[^\r\n{;]+[\{;]"
    r")"
)
_LOOSE_SOURCE_INDICATOR = re.compile(
    r"(?im)(?:"
    r"(?:^|\n)\s*[A-Za-z_$][A-Za-z0-9_$]*"
    r"(?:\s*:\s*[A-Za-z_$][A-Za-z0-9_$<>\[\],.? ]*)?\s*="
    r"|(?:^|\n)\s*(?:await\s+)?[A-Za-z_$][A-Za-z0-9_$]*"
    r"(?:\.[A-Za-z_$][A-Za-z0-9_$]*)+\s*\([^\r\n)]*\)"
    r"|(?:^|\n)\s*lambda\s+[A-Za-z_$][A-Za-z0-9_$]*"
    r"(?:\s*,\s*[A-Za-z_$][A-Za-z0-9_$]*)*\s*:"
    r"|(?:print|println!|fmt\.Print(?:f|ln)?|System\.out\.[A-Za-z]+)\s*\("
    r"|=>|[{}]"
    r")"
)
_STRUCTURED_SOURCE_INDICATOR = re.compile(
    r"(?im)(?:"
    r"(?:^|\n)\s*(?:(?:public|private|protected|override|final|abstract|"
    r"inline|suspend|open|internal)\s+)*(?:async\s+)?def\s+"
    r"[A-Za-z_][A-Za-z0-9_]*"
    r"(?:\s*\(|\s*=)"
    r"|(?:^|\n)\s*(?:(?:public|private|protected|override|final|abstract|"
    r"inline|suspend|open|internal)\s+)*(?:fn|func|fun|function)\s+"
    r"[A-Za-z_$][A-Za-z0-9_$]*\s*\("
    r"|(?:^|\n)\s*(?:class|interface|enum|record|object|trait)\s+"
    r"[A-Za-z_$][A-Za-z0-9_$]*(?:\s+extends\b|\s*\{)"
    r"|(?:^|\n)\s*(?:package|namespace|using|import|from|return|export)\s+"
    r"[^\r\n]+"
    r"|(?:^|\n)\s*type\s+[A-Za-z_$][A-Za-z0-9_$]*\s*="
    r"|(?:^|\n)\s*(?:const|let|var|val)\s+"
    r"[A-Za-z_$][A-Za-z0-9_$]*\s*="
    r"|(?:^|\n)\s*(?:(?:public|private|protected|static|final|abstract|"
    r"synchronized|native)\s+)*(?:void|boolean|byte|short|int|long|float|"
    r"double|char|String|[A-Z][A-Za-z0-9_$]*(?:<[^\r\n>]+>)?)"
    r"(?:\[\])?\s+[A-Za-z_$][A-Za-z0-9_$]*\s*\([^\r\n)]*\)\s*"
    r"(?:\{|throws\b)"
    r"|(?:^|\n)\s*(?:boolean|byte|short|int|long|float|double|char|String|"
    r"[A-Z][A-Za-z0-9_$]*(?:<[^\r\n>]+>)?)(?:\[\])?\s+"
    r"[A-Za-z_$][A-Za-z0-9_$]*\s*="
    r"|(?:print|println!|fmt\.Print(?:f|ln)?|System\.out\.[A-Za-z]+)\s*\("
    r")"
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
    r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?<![:A-Za-z0-9_-])\b((?:[A-Z0-9]+[_-])*(?:api[ _-]?key|access[ _-]?token|"
    r"auth[ _-]?token|password|passwd|secret|credential)"
    r"(?:[_-][A-Z0-9]+)*)"
    r"\s*[:=]\s*(\[secret omitted\]|\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_REDACTED_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?<![:A-Za-z0-9_-])\b(?:[A-Z0-9]+[_-])*(?:api[ _-]?key|access[ _-]?token|"
    r"auth[ _-]?token|password|passwd|secret|credential)"
    r"(?:[_-][A-Z0-9]+)*\s*[:=]\s*\[secret omitted\]"
)
_SECRET_PHRASE = re.compile(
    r"(?i)(?<!\[)\b((?:api[ _-]?key|access[ _-]?token|auth[ _-]?token|"
    r"password|passwd|token|secret|credential))\s+"
    r"(?!(?:analysis|budget|budgeted|capability|ceiling|count|counts|coverage|"
    r"detection|estimate|estimation|finding|findings|handling|is|limit|limits|"
    r"management|policy|review|rotation|rule|rules|scanning|storage|support|"
    r"usage|validation|was|were)\b)"
    r"(\[secret omitted\]|\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_TOKEN = re.compile(
    r"(?i)\b(?:"
    r"gh[pousr]_[A-Za-z0-9]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r"|(?:(?:[A-Z0-9]+[_-])*(?:api[ _-]?key|access[ _-]?token|"
    r"auth[ _-]?token|token|secret|password|credential)"
    r"(?:[_-][A-Z0-9]+)*)"
    r"\s+(?:"
    r"[A-Za-z0-9._~+/=-]{20,}"
    r"|(?=[A-Za-z0-9._~+/=-]{12,}\b)"
    r"(?=[A-Za-z0-9._~+/=-]*[0-9._~+/=-])"
    r"[A-Za-z0-9._~+/=-]{12,}"
    r")"
    r")"
)
_WINDOWS_PATH = re.compile(
    r"(?i)(?:file:///?)?[A-Z]:[\\/](?:[^\s,;\]\[(){}]+[\\/]?)+"
)
_UNC_PATH = re.compile(r"\\\\[^\s\\/]+[\\/][^\s,;\]\[(){}]+")
_POSIX_PATH = re.compile(
    r"(?<![A-Za-z0-9])/(?:home|Users|root|private|tmp|var|etc|opt|srv|mnt)/"
    r"[^\s,;\]\[(){}]+",
    re.IGNORECASE,
)
_REMOTE_URL = re.compile(
    r"(?i)\b(?:https?|ssh|git)://[^\s,;\]\[(){}]+|"
    r"\bgit@[^\s:]+:[^\s,;\]\[(){}]+"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PRIVATE_HOST = re.compile(
    r"(?<![A-Za-z0-9:])(?:"
    r"(?i:localhost(?:\.localdomain)?)"
    r"|10(?:\.\d{1,3}){3}"
    r"|127(?:\.\d{1,3}){3}"
    r"|192\.168(?:\.\d{1,3}){2}"
    r"|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
    r"|169\.254(?:\.\d{1,3}){2}"
    r"|::1"
    r"|(?i:f[cd][0-9a-f]{2}(?::[0-9a-f]{0,4})+)"
    r"|(?i:fe[89ab][0-9a-f](?::[0-9a-f]{0,4})+)"
    r")(?![A-Za-z0-9.-])"
)
_PRIVATE_HOST_CONTEXT = re.compile(
    r"(?i)\b(?:host|server|endpoint)\s*[:=]?\s*"
    r"(?:[a-z0-9-]+\.)*(?:internal|local|lan|corp)"
    r"(?:\.[a-z0-9-]+)*"
    r"|\bconnect(?:ed|ing)?\s+to\s+"
    r"(?:[a-z0-9-]+\.)*(?:internal|local|lan|corp)"
    r"(?:\.[a-z0-9-]+)*"
)
_REDACTION_MARKERS = (
    "[secret omitted]",
    "[source omitted]",
    "[machine path omitted]",
    "[remote omitted]",
    "[identity omitted]",
    "[content omitted]",
)


def sanitize_chat_text(value: str, *, maximum: int = 4_096) -> str:
    """Return bounded untrusted prose with source, paths, and secrets removed."""

    if not isinstance(value, str):
        raise TypeError("chat text must be a string")
    if maximum < 1:
        raise ValueError("chat text limit must be positive")
    text = value.replace("\x00", " ")
    text = _PRIVATE_KEY.sub("[secret omitted]", text)
    text = _CODE_FENCE.sub("[source omitted]", text)
    text = _SOURCE_SHAPED.sub("[source omitted]", text)
    text = _SOURCE_LINE.sub("\n[source omitted]", text)
    text = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}=[secret omitted]", text
    )
    text = _SECRET_PHRASE.sub(
        lambda match: f"{match.group(1)} [secret omitted]", text
    )
    text = _BEARER.sub("Bearer [secret omitted]", text)
    text = _SECRET_TOKEN.sub("[secret omitted]", text)
    text = _WINDOWS_PATH.sub("[machine path omitted]", text)
    text = _UNC_PATH.sub("[machine path omitted]", text)
    text = _POSIX_PATH.sub("[machine path omitted]", text)
    text = _REMOTE_URL.sub("[remote omitted]", text)
    text = _EMAIL.sub("[identity omitted]", text)
    text = _PRIVATE_HOST_CONTEXT.sub("[identity omitted]", text)
    text = _PRIVATE_HOST.sub("[identity omitted]", text)
    if (
        _STRUCTURED_SOURCE_INDICATOR.search(text)
        or _LOOSE_SOURCE_INDICATOR.search(text)
    ):
        text = "[source omitted]"
    if contains_absolute_path_text(text):
        text = "[content omitted]"
    text = " ".join(text.split())
    if not text:
        text = "[content omitted]"
    if len(text) > maximum:
        if maximum <= 3:
            return "." * maximum
        text = text[: maximum - 3].rstrip() + "..."
    return text


def sanitize_chat_metadata(value: str, *, maximum: int = 256) -> str:
    """Return one bounded source-free provider/model identifier."""

    if not isinstance(value, str):
        raise TypeError("chat metadata must be a string")
    normalized = value.strip()
    if not normalized:
        return ""
    sanitized = sanitize_chat_text(normalized, maximum=maximum)
    if sanitized != normalized or any(
        marker in sanitized for marker in _REDACTION_MARKERS
    ):
        return "redacted"
    return sanitized


def contains_unsafe_chat_content(value: object) -> bool:
    """Reject unsafe raw text at the structured chat-envelope boundary."""

    if isinstance(value, Mapping):
        return any(
            contains_unsafe_chat_content(key) or contains_unsafe_chat_content(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return any(contains_unsafe_chat_content(item) for item in value)
    if not isinstance(value, str):
        return False
    # Redacted assignments are an approved boundary representation.  Remove
    # the complete assignment before stripping the remaining display markers
    # so the empty assignment cannot be mistaken for raw private data.
    text = _REDACTED_SECRET_ASSIGNMENT.sub("", value)
    for marker in _REDACTION_MARKERS:
        text = text.replace(marker, "")
    return bool(
        "\x00" in text
        or contains_absolute_path_text(text)
        or _CODE_FENCE.search(text)
        or _SOURCE_SHAPED.search(text)
        or _SOURCE_LINE.search(text)
        or _STRUCTURED_SOURCE_INDICATOR.search(text)
        or _LOOSE_SOURCE_INDICATOR.search(text)
        or _PRIVATE_KEY.search(text)
        or _SECRET_ASSIGNMENT.search(text)
        or _SECRET_PHRASE.search(text)
        or _BEARER.search(text)
        or _SECRET_TOKEN.search(text)
        or _REMOTE_URL.search(text)
        or _EMAIL.search(text)
        or _PRIVATE_HOST_CONTEXT.search(text)
        or _PRIVATE_HOST.search(text)
    )
