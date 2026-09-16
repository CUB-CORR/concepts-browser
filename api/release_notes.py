"""Release notes (GitHub-flavored Markdown) → an HTML fragment an email client renders.

What GitHub hands a workflow as `release.body` is the raw Markdown the release was written in,
not HTML. GitHub *can* render it (`body_html`), but that output leans on GitHub's stylesheet
and classes, which no mail client has — so it is rendered here instead, with the styling
inlined on each element (Outlook ignores most of a `<style>` block).

Raw HTML in the notes is escaped, not passed through: the body arrives from a workflow and is
mailed to every user, so nothing in it gets to be markup we did not produce. As a consequence,
the string replacements below only ever see tags this renderer emitted.

GitHub's auto-generated notes lean on its own shorthands — bare URLs, `@user`, `#123` — so
bare URLs are always linked, and mentions and issue references are linked when the repository
is known.
"""
import re

from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore
from markdown_it.token import Token

_FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
_MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

# Inline style per opening tag. Keyed on the tag, so every heading level, list and cell is
# covered by one entry.
_STYLES = {
    "h1": "font-size: 20px; margin: 20px 0 8px; padding-bottom: 4px; border-bottom: 1px solid #d8dee4;",
    "h2": "font-size: 18px; margin: 20px 0 8px; padding-bottom: 4px; border-bottom: 1px solid #d8dee4;",
    "h3": "font-size: 16px; margin: 16px 0 8px;",
    "h4": "font-size: 14px; margin: 16px 0 8px;",
    "h5": "font-size: 14px; margin: 16px 0 8px;",
    "h6": "font-size: 13px; margin: 16px 0 8px; color: #59636e;",
    "p": "margin: 0 0 12px;",
    "ul": "margin: 0 0 12px; padding-left: 24px;",
    "ol": "margin: 0 0 12px; padding-left: 24px;",
    "li": "margin: 2px 0;",
    "a": "color: #0969da; text-decoration: none;",
    "blockquote": "margin: 0 0 12px; padding: 0 12px; color: #59636e; border-left: 3px solid #d0d7de;",
    "table": "border-collapse: collapse; margin: 0 0 12px;",
    "th": "border: 1px solid #d0d7de; padding: 4px 10px; background: #f6f8fa; text-align: left;",
    "td": "border: 1px solid #d0d7de; padding: 4px 10px;",
    "hr": "border: 0; border-top: 1px solid #d8dee4; margin: 16px 0;",
    "img": "max-width: 100%;",
}
_CODE_INLINE_STYLE = (
    f"font-family: {_MONO}; font-size: 85%; padding: 1px 4px; "
    "background: #eff1f3; border-radius: 4px;"
)
_PRE_STYLE = (
    f"font-family: {_MONO}; font-size: 12px; line-height: 1.45; padding: 12px; margin: 0 0 12px; "
    "background: #f6f8fa; border-radius: 6px; overflow-x: auto; white-space: pre-wrap;"
)

# GitHub's username rule: alphanumerics and single hyphens, at most 39 characters. The
# lookbehinds keep e-mail addresses, paths and existing anchors (`foo@bar`, `a/#1`) alone.
_MENTION = r"(?<![\w@/.])@(?P<user>[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38})(?![\w-])"
_ISSUE = r"(?<![\w&/#])#(?P<issue>\d+)\b"
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def is_repository(value: str) -> bool:
    """`owner/repo`, the shape GitHub's `github.repository` context has."""
    return bool(_REPOSITORY.match(value))


def _style_tokens(state: StateCore) -> None:
    def style(tokens: list[Token]) -> None:
        for token in tokens:
            if token.type == "code_inline":
                token.attrSet("style", _CODE_INLINE_STYLE)
            elif (token.nesting == 1 or token.type in ("hr", "image")) and token.tag in _STYLES:
                token.attrSet("style", _STYLES[token.tag])
            if token.children:
                style(token.children)

    style(state.tokens)


def _github_links(repository: str):
    """Core rule linking `@user` and `#123` in plain text. Text inside an existing link (a
    Markdown link, or a URL linkify already turned into one) and code spans are left alone —
    the latter for free, since a code span is its own token type and never `text`."""
    pattern = re.compile(f"{_MENTION}|{_ISSUE}")
    base = "https://github.com"

    def rule(state: StateCore) -> None:
        for block in state.tokens:
            if block.type != "inline" or not block.children:
                continue
            children: list[Token] = []
            depth = 0
            for token in block.children:
                if token.type == "link_open":
                    depth += 1
                elif token.type == "link_close":
                    depth -= 1
                if token.type != "text" or depth > 0 or not pattern.search(token.content):
                    children.append(token)
                    continue

                pos = 0
                for match in pattern.finditer(token.content):
                    if match.start() > pos:
                        children.append(_text(token.content[pos : match.start()]))
                    if match.group("user"):
                        href = f"{base}/{match.group('user')}"
                    else:
                        href = f"{base}/{repository}/issues/{match.group('issue')}"
                    link_open = Token("link_open", "a", 1)
                    link_open.attrSet("href", href)
                    children += [link_open, _text(match.group(0)), Token("link_close", "a", -1)]
                    pos = match.end()
                if pos < len(token.content):
                    children.append(_text(token.content[pos:]))
            block.children = children

    return rule


def _text(content: str) -> Token:
    token = Token("text", "", 0)
    token.content = content
    return token


def _parser(repository: str | None) -> MarkdownIt:
    # "commonmark" with `html` off: raw HTML in the notes is escaped (see the module docstring).
    md = MarkdownIt("commonmark", {"html": False, "linkify": True}).enable(
        ["table", "strikethrough", "linkify"]
    )
    if repository:
        md.core.ruler.after("linkify", "github_links", _github_links(repository))
    # Last, so the links the rules above introduced are styled too.
    md.core.ruler.push("inline_styles", _style_tokens)
    return md


def render_markdown(markdown: str, *, repository: str | None = None) -> str:
    """The notes as an HTML fragment with inline styles. `repository` (`owner/repo`) turns on
    `@user` / `#123` links; without it they stay plain text."""
    html = _parser(repository).render(markdown)
    # A fence renders as `<pre><code>`, and its token's attributes land on the `<code>`; the
    # box belongs on the `<pre>`, which no token exposes. Safe as a plain replacement: with
    # `html` off, a literal `<pre>` in the notes arrives here as `&lt;pre&gt;`.
    return html.replace("<pre>", f'<pre style="{_PRE_STYLE}">')


def email_html(*, greeting: str, lead_html: str, notes_html: str, footer_html: str) -> str:
    """The whole message: a greeting, the lead paragraph, the notes set off in a box, a footer.
    A table carries the box because Outlook's Word engine does not honour `max-width` or
    padding on a `<div>`."""
    return f"""\
<html><body style="margin: 0; padding: 16px; font-family: {_FONT}; font-size: 14px; line-height: 1.5; color: #1f2328;">
<p style="margin: 0 0 12px;">{greeting}</p>
<p style="margin: 0 0 16px;">{lead_html}</p>
<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width: 720px; border-collapse: collapse;">
<tr><td style="padding: 16px 20px; border: 1px solid #d0d7de; border-radius: 6px;">
{notes_html}
</td></tr>
</table>
{footer_html}
</body></html>
"""
