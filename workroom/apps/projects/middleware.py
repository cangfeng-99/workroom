"""Server-mode access middleware.

All pages require a real session except login/register/invite/health and the
Bearer-token tool API. The tool API performs its own token check.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.urls import reverse

PUBLIC_PREFIXES = (
    "/login/",
    "/register/",
    "/join/",
    "/healthz",
    "/api/tools/",
    '/mcp/',
    "/static/",
    "/favicon.ico",
)


class TrustedProxyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        peer = request.META.get("REMOTE_ADDR", "")
        try:
            address = ipaddress.ip_address(peer)
            trusted = any(
                address in ipaddress.ip_network(value.strip())
                for value in getattr(settings, "WORKROOM_TRUSTED_PROXY_IPS", [])
            )
        except ValueError:
            trusted = False
        if not trusted:
            for key in ("HTTP_X_FORWARDED_PROTO", "HTTP_X_FORWARDED_HOST", "HTTP_X_FORWARDED_FOR"):
                request.META.pop(key, None)
        return self.get_response(request)


class ServerAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "WORKROOM_MODE", "local") != "server":
            return self.get_response(request)
        path = request.path_info or "/"
        if any(path == prefix or path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            return self.get_response(request)
        if request.user.is_authenticated:
            return self.get_response(request)
        if path.startswith("/api/"):
            from django.http import JsonResponse

            return JsonResponse({"ok": False, "error": "authentication required"}, status=401)
        login = reverse("projects:login")
        target = request.get_full_path()
        return HttpResponseRedirect(f"{login}?{urlencode({'next': target})}")
