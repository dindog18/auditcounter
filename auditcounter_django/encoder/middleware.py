"""Unauthenticated MCP Encoder pages are available only on an enabled loopback site."""
from ipaddress import ip_address
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponseForbidden


def encoder_access_allowed(request):
    if not settings.ENCODER_LOCAL_ENABLED:
        return False
    try:
        peer = ip_address(request.META.get("REMOTE_ADDR", ""))
        host = urlsplit("//" + request.get_host()).hostname
        return peer.is_loopback and (host == "localhost" or (host is not None and ip_address(host).is_loopback))
    except ValueError:
        return False


class LocalEncoderMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info.startswith("/encoder/") and not encoder_access_allowed(request):
            return HttpResponseForbidden("MCP Encoder is available only when ENCODER_LOCAL_ENABLED=true on a trusted loopback development server.")
        return self.get_response(request)
