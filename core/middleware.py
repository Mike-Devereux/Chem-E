from django.utils.deprecation import MiddlewareMixin


HEADER_STYLE_BLOCK = """
<style>
    :root {
        --chem-e-header-height: 45px;
        --chem-e-header-bg: #2d373c;
        --chem-e-footer-height: 45px;
        --chem-e-footer-bg: #2d373c;
        --chem-e-banner-height: 146px;
        --chem-e-content-margin: 100px;
        --chem-e-banner-bg: #a5d7d2;
    }
    body {
        margin: 0;
        max-width: none !important;
        width: 100%;
        min-height: 100vh;
        display: flex;
        flex-direction: column;
    }
    h1, h2, h3, h4, h5, h6 {
        font-family: "PTSerif", serif;
    }
    p {
        font-family: Inter, sans-serif;
        font-size: 15px;
    }
    li {
        font-family: Inter, sans-serif;
        font-size: 15px;
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
    .chem-e-global-header-inner {
        height: 100%;
        width: 100%;
        box-sizing: border-box;
        display: flex;
        justify-content: flex-end;
        align-items: center;
        padding-left: var(--chem-e-content-margin);
        padding-right: var(--chem-e-content-margin);
    }
    .chem-e-global-header-links {
        display: flex;
        align-items: center;
        gap: 20px;
    }
    .chem-e-global-header-home,
    .chem-e-global-header-logout {
        color: #ffffff;
        font-family: Inter, sans-serif;
        font-size: 13px;
        text-decoration: none;
    }
    .chem-e-global-header-home:hover,
    .chem-e-global-header-home:focus,
    .chem-e-global-header-logout:hover,
    .chem-e-global-header-logout:focus {
        text-decoration: underline;
    }
    .chem-e-page-banner {
        margin-top: var(--chem-e-header-height);
        width: 100vw;
        height: var(--chem-e-banner-height);
        background: var(--chem-e-banner-bg);
        box-sizing: border-box;
    }
    .chem-e-page-banner-inner {
        height: 100%;
        width: 100%;
        display: flex;
        justify-content: space-between;
        align-items: center;
        box-sizing: border-box;
        padding-left: var(--chem-e-content-margin);
        padding-right: var(--chem-e-content-margin);
    }
    .chem-e-page-banner-left {
        display: flex;
        align-items: center;
    }
    .chem-e-page-banner-right {
        display: flex;
        align-items: center;
    }
    .chem-e-page-banner-left-logo {
        display: block;
        height: 73px;
        width: auto;
    }
    .chem-e-page-banner-logo {
        display: block;
        height: 73px;
        width: auto;
    }
    .chem-e-global-footer {
        width: 100%;
        height: var(--chem-e-footer-height);
        background: var(--chem-e-footer-bg);
        display: flex;
        align-items: center;
        justify-content: flex-end;
        box-sizing: border-box;
        padding-left: var(--chem-e-content-margin);
        padding-right: var(--chem-e-content-margin);
        margin-top: auto;
    }
    .chem-e-global-footer-text {
        color: #ffffff;
        font-family: Inter, sans-serif;
        font-size: 13px;
    }
    body > :not(.chem-e-global-header):not(.chem-e-page-banner):not(.chem-e-global-footer) {
        margin-left: var(--chem-e-content-margin);
        margin-right: var(--chem-e-content-margin);
    }
</style>
"""

PAGE_BANNER = (
    '<div class="chem-e-page-banner" aria-hidden="true">'
    '<div class="chem-e-page-banner-inner">'
    '<div class="chem-e-page-banner-left">'
    '<img class="chem-e-page-banner-left-logo" src="/media/ui/uni-basel-logo.svg" alt="">'
    "</div>"
    '<div class="chem-e-page-banner-right">'
    '<img class="chem-e-page-banner-logo" src="/media/ui/DepChe_Logo_DE_Schwarz_RGB.png" alt="">'
    "</div>"
    "</div>"
    "</div>"
)

FOOTER_BAR = (
    '<footer class="chem-e-global-footer">'
    '<span class="chem-e-global-footer-text">Chem-E: michael.devereux@unibas.ch</span>'
    "</footer>"
)


class GlobalHeaderBarMiddleware(MiddlewareMixin):
    """Inject a global fixed header bar into all HTML responses."""

    def _home_href_for(self, request):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return "/"
        user_role = getattr(user, "role", None)
        if user.is_superuser or user_role in {"supervisor", "administrator"}:
            return "/supervisor"
        return "/"

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

        header_bar = (
            '<div class="chem-e-global-header">'
            '<div class="chem-e-global-header-inner">'
            '<nav class="chem-e-global-header-links">'
            f'<a class="chem-e-global-header-home" href="{self._home_href_for(request)}">Home</a>'
            '<a class="chem-e-global-header-logout" href="/logout/">Logout</a>'
            "</nav>"
            "</div>"
            "</div>"
        )

        if "</head>" in html:
            html = html.replace("</head>", f"{HEADER_STYLE_BLOCK}</head>", 1)
        if "<body>" in html:
            html = html.replace("<body>", f"<body>{header_bar}{PAGE_BANNER}", 1)
        else:
            body_start = html.find("<body")
            if body_start != -1:
                body_end = html.find(">", body_start)
                if body_end != -1:
                    html = (
                        html[: body_end + 1]
                        + header_bar
                        + PAGE_BANNER
                        + html[body_end + 1 :]
                    )
        if "</body>" in html:
            html = html.replace("</body>", f"{FOOTER_BAR}</body>", 1)

        response.content = html.encode(response.charset or "utf-8")
        if "Content-Length" in response:
            response["Content-Length"] = str(len(response.content))
        return response
