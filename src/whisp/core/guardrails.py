import re
from urllib.parse import urlsplit

from whisp.text import URL_PATTERN

MASK = "•"
# Fixed length, so a masked password does not reveal how long it is.
PASSWORD_MASK = MASK * 6
# User-facing replacements are Vietnamese, like every other Telegram string.
LINK_MASK = "[link đã ẩn, mở email để xem]"
SECRET_MASK = "[khóa bí mật đã ẩn]"
# How far from a keyword a value may sit, in characters. Covers both "Your code is 123456"
# and "123456 is your verification code" without reaching unrelated numbers further along.
_WINDOW = 40


def redact(text: str) -> str:
    """Mask anything in outgoing text that would give its reader access to an account.

    Rules target credentials only. Amounts, names, and dates stay: they are what makes a
    notification useful, and they are the user's own information shown to the user.
    Links go first because their tokens would otherwise be half-masked by later rules.
    """
    for rule in (_redact_links, _redact_secrets, _redact_passwords, _redact_otp):
        text = rule(text)
    return text


def _nearby(text: str, start: int, end: int, window: int = _WINDOW) -> str:
    """The text around a match, limited to its own line."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end == -1 else line_end
    return text[max(line_start, start - window) : min(line_end, end + window)]


# --- Sign-in, password-reset, and verification links ---

# Path segments and query keys that mark a link as one that signs in or changes an account.
_SENSITIVE_PATH = re.compile(
    r"(?i)(?:reset|recover|verif|confirm|activat|magic|passwordless|one[-_]?time"
    r"|sign[-_]?in|log[-_]?in|auth(?!or)|invite|otp)"
)
_SENSITIVE_QUERY = re.compile(
    r"(?i)(?:^|&)(?:[^=&]*[-_.])?"
    r"(?:token|code|otp|key|auth|ticket|hash|signature|sig|nonce|session)[^=&]*="
)
# Wording next to a link that says what it does, for links whose URL gives nothing away.
_LINK_KEYWORD = re.compile(
    r"""(?ix)
    reset | password | sign[\s-]?in | log[\s-]?in | verify | verification | confirm
  | magic\s+link | activate
  | mật\s+khẩu | đăng\s+nhập | xác\s+(?:minh|thực|nhận) | kích\s+hoạt
  | mat\s+khau | dang\s+nhap | xac\s+(?:minh|thuc|nhan) | kich\s+hoat
    """
)


def _redact_links(text: str) -> str:
    def mask(match: re.Match[str]) -> str:
        # Trailing punctuation belongs to the sentence, not the link.
        url = match.group().rstrip(".,;:!?")
        trailing = match.group()[len(url) :]
        parts = urlsplit(url)
        sensitive = (
            _SENSITIVE_PATH.search(parts.path)
            or _SENSITIVE_QUERY.search(parts.query)
            or _SENSITIVE_QUERY.search(parts.fragment)
            or _LINK_KEYWORD.search(_nearby(text, *match.span()))
        )
        return LINK_MASK + trailing if sensitive else match.group()

    return URL_PATTERN.sub(mask, text)


# --- API keys and access tokens ---

# Only formats with a distinctive prefix: a generic "long random string" rule would also
# catch tracking ids and file hashes.
_SECRET = re.compile(
    r"""(?xs)
    -----BEGIN[ A-Z]*PRIVATE\ KEY-----.*?-----END[ A-Z]*PRIVATE\ KEY-----
  | \b(?:
        gh[pousr]_[A-Za-z0-9]{36,}
      | github_pat_[A-Za-z0-9_]{22,}
      | glpat-[A-Za-z0-9_-]{20,}
      | sk-[A-Za-z0-9_-]{20,}
      | AKIA[0-9A-Z]{16}
      | AIza[0-9A-Za-z_-]{35}
      | xox[abposr]-[A-Za-z0-9-]{10,}
      | \d{8,10}:AA[A-Za-z0-9_-]{33}
    )
    """
)


def _redact_secrets(text: str) -> str:
    return _SECRET.sub(SECRET_MASK, text)


# --- Passwords ---

_PASSWORD = re.compile(
    r"""(?ix)
    \b(?:password | passwd | pwd | passphrase | mật\s+khẩu | mat\s+khau)\b
    # Up to a few words in between: "mật khẩu mở file là", "temporary password is".
    [^\n\d:]{0,25}?
    (?: : | \bis\b | \blà\b | \bla\b )
    \s*["'“]?
    (?P<value>[^\s"'”]{4,64})
    """
)


def _looks_like_password(value: str) -> bool:
    # Plain words after the keyword are usually prose ("your password is changed",
    # "mật khẩu là ngày sinh"), so only mask values that read like a credential.
    return (
        any(char.isdigit() for char in value)
        or any(not char.isalnum() for char in value)
        or (value[1:] != value[1:].lower())
    )


def _redact_passwords(text: str) -> str:
    def mask(match: re.Match[str]) -> str:
        value = match.group("value")
        # "!" and "?" are common in passwords, so only "." and "," count as sentence ends.
        stripped = value.rstrip(".,")
        if stripped in (LINK_MASK, SECRET_MASK) or not _looks_like_password(stripped):
            return match.group()
        start = match.start("value") - match.start()
        return match.group()[:start] + PASSWORD_MASK + value[len(stripped) :]

    return _PASSWORD.sub(mask, text)


# --- One-time codes ---

# Wording that marks a nearby number as a one-time code, in English and Vietnamese (with and
# without diacritics, since Vietnamese SMS-style mail often drops them). Bare "mã" is left
# out on purpose: "mã đơn hàng" (order number) is far more common than an OTP.
_OTP_KEYWORD = re.compile(
    r"""(?ix)
    \b(?:
        otp | one[\s-]?time | passcode | pin | 2fa | two[\s-]?factor | mfa
      | verification | verify | authentication | auth
      | (?:security|login|log[\s-]?in|sign[\s-]?in|confirmation|access|reset)\s+code
      | code
      | mã\s+(?:otp|xác\s+thực|xác\s+minh|xác\s+nhận|đăng\s+nhập|bảo\s+mật|kích\s+hoạt|pin)
      | ma\s+(?:otp|xac\s+thuc|xac\s+minh|xac\s+nhan|dang\s+nhap|bao\s+mat|kich\s+hoat|pin)
      | mật\s+khẩu\s+(?:một\s+lần|dùng\s+một\s+lần)
      | mat\s+khau\s+(?:mot\s+lan|dung\s+mot\s+lan)
    )\b
    """
)
# A code is 4-8 digits, optionally split into two groups ("123 456", "1234-5678"), with an
# optional letter prefix as Google uses ("G-123456"). The surrounding guards keep amounts,
# dates, times, and phone numbers ("1.250.000", "2026/10/11", "10:30", "+84 912") intact.
_OTP_CODE = re.compile(
    r"""(?x)
    (?<![\w.,/:+-])
    (?:[A-Z]{1,3}-)?
    (?:\d{4,8} | \d{3,4}[ -]\d{3,4})
    (?![\w/:]|[.,-]\d)
    """
)


def _redact_otp(text: str) -> str:
    # Only numbers near OTP wording are masked; a rule that hid every number would also
    # hide the amounts and dates that make a notification useful.
    def mask(match: re.Match[str]) -> str:
        if not _OTP_KEYWORD.search(_nearby(text, *match.span())):
            return match.group()
        return re.sub(r"\w", MASK, match.group())

    return _OTP_CODE.sub(mask, text)
