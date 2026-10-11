import pytest

from whisp.core.guardrails import LINK_MASK, PASSWORD_MASK, SECRET_MASK, redact


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Mã OTP của bạn là 482913, hiệu lực 5 phút.",
            "Mã OTP của bạn là ••••••, hiệu lực 5 phút.",
        ),
        ("Ma xac thuc: 482913", "Ma xac thuc: ••••••"),
        (
            "G-482913 is your Google verification code.",
            "•-•••••• is your Google verification code.",
        ),
        ("Your login code is 482 913.", "Your login code is ••• •••."),
        ("Use code 1234-5678 to sign in.", "Use code ••••-•••• to sign in."),
    ],
)
def test_codes_near_otp_wording_are_masked(text: str, expected: str) -> None:
    assert redact(text) == expected


def test_keyword_on_another_line_does_not_mask_a_code() -> None:
    text = "Your order #48291 shipped.\nYour verification code is 991204."
    assert redact(text) == "Your order #48291 shipped.\nYour verification code is ••••••."


@pytest.mark.parametrize(
    "text",
    [
        "Đặt lại mật khẩu tại https://accounts.example.com/r/abc123 trong 1 giờ.",
        "Open https://example.com/password/reset/abc to continue",
        "Bấm https://shop.vn/c/abcd?token=zzz để nhận ưu đãi.",
        "Slack: sign in with https://app.slack.com/x/9f8e7d6c",
        "Accept at https://notion.so/invite/abc",
        "Download https://bucket.s3.amazonaws.com/f.pdf?X-Amz-Signature=abc",
    ],
)
def test_sign_in_and_reset_links_are_masked(text: str) -> None:
    redacted = redact(text)
    assert LINK_MASK in redacted
    assert "https://" not in redacted


def test_masked_link_keeps_sentence_punctuation() -> None:
    assert redact("Xác minh tại https://x.com/verify/abc.") == f"Xác minh tại {LINK_MASK}."


@pytest.mark.parametrize(
    "text",
    [
        "Xem hóa đơn tại https://acme.com/pay?id=42 trước thứ Sáu.",
        "Đọc bài viết https://blog.example.com/posts/2026/python-tips.",
        "Tác giả https://blog.vn/author/an",
    ],
)
def test_ordinary_links_are_kept(text: str) -> None:
    assert redact(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Mật khẩu mở file là 01011990.", f"Mật khẩu mở file là {PASSWORD_MASK}."),
        ("Mat khau: Abc@123", f"Mat khau: {PASSWORD_MASK}"),
        (
            "Your temporary password is Xy7#k2pQ, change it soon.",
            f"Your temporary password is {PASSWORD_MASK}, change it soon.",
        ),
        ('Wi-Fi password: "Cafe2026!"', f'Wi-Fi password: "{PASSWORD_MASK}"'),
    ],
)
def test_passwords_are_masked(text: str, expected: str) -> None:
    assert redact(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Mật khẩu mở file là ngày sinh của bạn (ddmmyyyy).",
        "Your password was changed on Oct 11.",
        "Your password is expiring soon.",
    ],
)
def test_password_prose_is_kept(text: str) -> None:
    assert redact(text) == text


@pytest.mark.parametrize(
    "secret",
    [
        "ghp_" + "a" * 36,
        "github_pat_" + "B1" * 15,
        "sk-or-v1-" + "c" * 40,
        "AKIA" + "D" * 16,
        "xoxb-1234567890-abcdef",
        "123456789:AA" + "e" * 33,
        "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----",
    ],
)
def test_api_keys_are_masked(secret: str) -> None:
    assert redact(f"Key: {secret} (keep it safe)") == f"Key: {SECRET_MASK} (keep it safe)"


@pytest.mark.parametrize(
    "text",
    [
        "Techcombank: Hóa đơn 1.250.000đ đến hạn 2026/10/11 lúc 10:30.",
        "Đơn hàng 12345678 đã được giao.",
        "Mã đơn hàng 12345678",
        "Gọi +84 912 345 678 nếu cần hỗ trợ.",
        "Promo code SAVE20 gives 20% off",
        "Commit a1b2c3d4e5f6 was deployed.",
    ],
)
def test_everyday_content_is_kept(text: str) -> None:
    assert redact(text) == text
