"""Template filters for the consortium checklist pages (#148)."""

import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*(?=\S)(.+?)(?<=\S)\*(?![*\w])")


@register.filter
def clmd(text):
    """Markdown-lite for schema text (instructions, notes, steps): ``**bold**``,
    ``*italic*`` and line breaks. Everything else — HTML included — stays
    escaped; the stored text (step keys) is untouched."""
    s = escape(str(text or ""))
    s = _BOLD.sub(r"<strong>\1</strong>", s)
    s = _ITALIC.sub(r"<em>\1</em>", s)
    return mark_safe(s.replace("\n", "<br>"))
