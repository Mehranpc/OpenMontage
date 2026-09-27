"""#241: markdown copied into approved copy is refused at the front door, not burned into captions."""

from __future__ import annotations

import pytest

from lib.persian_video_workflow import PersianVideoWorkflowError, _validate_approved_script


@pytest.mark.parametrize("text", [
    "پیام رو **صبح روز بعد** بفرست.",
    "`پیام` بعد از قرار",
    "# عنوان\nمتن",
    "- اول\n- دوم",
    "> نقل‌قول",
    "__تأکید__ روی پیام",
])
def test_markdown_markup_is_refused_with_the_fix(text: str) -> None:
    with pytest.raises(PersianVideoWorkflowError, match="markdown markup.*Remove the formatting"):
        _validate_approved_script(text)


@pytest.mark.parametrize("text", [
    "پیام رو صبح روز بعد بفرست.",
    "ساعت ۹-۱۰ صبح، نه همون شب.",
    "بین دو قرار — یه پیام کوتاه.",
    "snake_case نه، ولی متن فارسی آره.",
])
def test_plain_copy_passes(text: str) -> None:
    assert _validate_approved_script(text)["text"] == text
