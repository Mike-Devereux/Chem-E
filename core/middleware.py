from django.utils.deprecation import MiddlewareMixin


HEADER_STYLE_BLOCK = """
<style>
    :root {
        --chem-e-header-height: 45px;
        --chem-e-header-bg: #2d373c;
        --chem-e-banner-height: 146px;
        --chem-e-content-margin: 100px;
        --chem-e-banner-bg: #a5d7d2;
    }
    body {
        margin: 0;
    }
    .chem-e-global-header {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        height: var(--chem-e-header-height);
        width: 100%;
        background: var(--chem-e-header-bg);
        z-index: 9999;
    }
    .chem-e-page-banner {
        margin-top: var(--chem-e-header-height);
        width: 100%;
        height: var(--chem-e-banner-height);
        background: var(--chem-e-banner-bg);
        box-sizing: border-box;
    }
    .chem-e-page-banner-inner {
        height: 100%;
        width: 100%;
        display: flex;
        justify-content: flex-end;
        align-items: center;
        box-sizing: border-box;
        padding-right: var(--chem-e-content-margin);
    }
    .chem-e-page-banner-logo {
        display: block;
        max-height: 120px;
        width: auto;
    }
    body > :not(.chem-e-global-header):not(.chem-e-page-banner) {
        margin-left: var(--chem-e-content-margin);
        margin-right: var(--chem-e-content-margin);
    }
</style>
"""

HEADER_BAR = '<div class="chem-e-global-header" aria-hidden="true"></div>'
PAGE_BANNER = (
    '<div class="chem-e-page-banner" aria-hidden="true">'
    '<div class="chem-e-page-banner-inner">'
    '<img class="chem-e-page-banner-logo" src="/media/ui/DepChe_Logo_DE_Schwarz_RGB.png" alt="">'
    "</div>"
    "</div>"
)


class GlobalHeaderBarMiddleware(MiddlewareMixin):
    """Inject a global fixed header bar into all HTML responses."""

    def process_response(self, request, response):
        content_type = response.get("Content-Type", "")
        if "text/html" not in content_type or getattr(response, "streaming", False):
            return response

        try:
            html = response.content.decode(response.charset or "utf-8")
        except (AttributeError, UnicodeDecodeError):
            return response

        if "chem-e-global-header" in html:
            return response

        if "</head>" in html:
            html = html.replace("</head>", f"{HEADER_STYLE_BLOCK}</head>", 1)
        if "<body>" in html:
            html = html.replace("<body>", f"<body>{HEADER_BAR}{PAGE_BANNER}", 1)
        else:
            body_start = html.find("<body")
            if body_start != -1:
                body_end = html.find(">", body_start)
                if body_end != -1:
                    html = (
                        html[: body_end + 1]
                        + HEADER_BAR
                        + PAGE_BANNER
                        + html[body_end + 1 :]
                    )

        response.content = html.encode(response.charset or "utf-8")
        if "Content-Length" in response:
            response["Content-Length"] = str(len(response.content))
        return response
