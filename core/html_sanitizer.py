from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse


ALLOWED_TAG_ATTRIBUTES = {
    "a": {"href", "target", "rel"},
    "strong": set(),
    "b": set(),
    "em": set(),
    "i": set(),
    "sub": set(),
    "sup": set(),
    "p": set(),
    "br": set(),
    "ul": set(),
    "ol": set(),
    "li": set(),
    "span": set(),
}

SAFE_LINK_SCHEMES = {"http", "https", "mailto"}
SELF_CLOSING_TAGS = {"br"}


def _is_safe_href(value):
    parsed = urlparse(value.strip())
    if not parsed.scheme:
        return True
    return parsed.scheme.lower() in SAFE_LINK_SCHEMES


class _AllowlistHTMLSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self._out = []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAG_ATTRIBUTES:
            return
        allowed_attrs = ALLOWED_TAG_ATTRIBUTES[tag]
        rendered_attrs = []
        for key, value in attrs:
            if key not in allowed_attrs:
                continue
            if value is None:
                continue
            if tag == "a" and key == "href" and not _is_safe_href(value):
                continue
            if tag == "a" and key == "target":
                target = value.strip().lower()
                if target not in {"_blank", "_self"}:
                    continue
                value = target
            if tag == "a" and key == "rel":
                # Always enforce safe rel values for links.
                value = "noopener noreferrer"
            rendered_attrs.append(f' {key}="{escape(value, quote=True)}"')
        if tag == "a" and "target" in [k for k, _ in attrs]:
            if not any(attr.startswith(' rel="') for attr in rendered_attrs):
                rendered_attrs.append(' rel="noopener noreferrer"')
        if tag in SELF_CLOSING_TAGS:
            self._out.append(f"<{tag}{''.join(rendered_attrs)}>")
        else:
            self._out.append(f"<{tag}{''.join(rendered_attrs)}>")

    def handle_endtag(self, tag):
        if tag in ALLOWED_TAG_ATTRIBUTES and tag not in SELF_CLOSING_TAGS:
            self._out.append(f"</{tag}>")

    def handle_data(self, data):
        self._out.append(escape(data))

    def handle_entityref(self, name):
        self._out.append(f"&{name};")

    def handle_charref(self, name):
        self._out.append(f"&#{name};")

    def get_html(self):
        return "".join(self._out)


def sanitize_rich_text(value):
    if not value:
        return ""
    parser = _AllowlistHTMLSanitizer()
    parser.feed(str(value))
    parser.close()
    return parser.get_html()
