"""Template filters for the consortium checklist pages (#148)."""

import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*(?=\S)(.+?)(?<=\S)\*(?![*\w])")
# Hajime 2026-09-29: ``[text](https://…)`` — a named link; http(s) only, so a
# schema can't smuggle a javascript: URL. Runs on the escaped text, where
# ``&`` in a URL is already ``&amp;`` (fine inside href).
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")


@register.filter
def clmd(text):
    """Markdown-lite for schema text (instructions, notes, steps): ``**bold**``,
    ``*italic*``, ``[text](https://url)`` and line breaks. Everything else —
    HTML included — stays escaped; the stored text (step keys) is untouched."""
    s = escape(str(text or ""))
    s = _LINK.sub(r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    s = _BOLD.sub(r"<strong>\1</strong>", s)
    s = _ITALIC.sub(r"<em>\1</em>", s)
    return mark_safe(s.replace("\n", "<br>"))
