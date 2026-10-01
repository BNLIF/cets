"""Template filters for the consortium checklist pages (#148)."""

import re

from django import template
from markdown_it import MarkdownIt
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*(?=\S)(.+?)(?<=\S)\*(?![*\w])")
# Hajime 2026-09-29: ``[text](https://…)`` — a named link; http(s) only, so a
# schema can't smuggle a javascript: URL. Runs on the escaped text, where
# ``&`` in a URL is already ``&amp;`` (fine inside href).
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
# Hajime 2026-10-01: ``<red>text</red>`` — a fixed palette, matched on the
# ESCAPED text, so the tag never reaches the page as HTML of its own
_COLOR = re.compile(r"&lt;(red|orange|green|blue|gr[ae]y)&gt;(.+?)&lt;/\1&gt;", re.S)


@register.filter
def clmd(text):
    """Markdown-lite for schema text (instructions, notes, steps): ``**bold**``,
    ``*italic*``, ``[text](https://url)``, ``<red>…</red>`` (orange, green,
    blue, gray too) and line breaks. Everything else — HTML included — stays
    escaped; the stored text (step keys) is untouched."""
    s = escape(str(text or ""))
    s = _COLOR.sub(r'<span class="clmd-\1">\2</span>', s)
    s = _LINK.sub(r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    s = _BOLD.sub(r"<strong>\1</strong>", s)
    s = _ITALIC.sub(r"<em>\1</em>", s)
    return mark_safe(s.replace("\n", "<br>"))


def _link_open(self, tokens, idx, options, env):
    tokens[idx].attrSet("target", "_blank")
    tokens[idx].attrSet("rel", "noopener")
    return self.renderToken(tokens, idx, options, env)


# #193 (Hajime 2026-10-01): the multi-line slots — a checklist's instructions,
# a static field's note — take full Markdown (CommonMark + tables +
# strikethrough). Raw HTML stays escaped, ``javascript:`` links are refused
# (markdown-it's defaults), a single line break is a <br> as in ``clmd``.
_MD = MarkdownIt("commonmark", {"html": False, "breaks": True, "xhtmlOut": False,
                                "typographer": False}).enable(["table", "strikethrough"])
_MD.add_render_rule("link_open", _link_open)
# a colour tag inside the rendered blocks — never across a block boundary
_COLOR_BLOCK = re.compile(r"&lt;(red|orange|green|blue|gr[ae]y)&gt;((?:(?!</(?:p|li|h\d|td|th|blockquote)>).)+?)&lt;/\1&gt;", re.S)


@register.filter
def clmd_block(text):
    """Full Markdown for a multi-line slot; ``<red>…</red>`` as in ``clmd``."""
    s = _MD.render(str(text or ""))
    return mark_safe(_COLOR_BLOCK.sub(r'<span class="clmd-\1">\2</span>', s))
