"""Bounded, exact-origin HTTPS transport. Redirects are never followed."""
from __future__ import annotations

import urllib.error
import urllib.request

from ..errors import DeveloperError
from ..link_protocol import canonical, decode_json, origin


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Transport:
    def __init__(self, *, timeout: float = 15):
        self.timeout = timeout
        self.opener = urllib.request.build_opener(NoRedirect())

    def post(self, site_origin: str, path: str, body: dict, secret: str | None = None) -> dict:
        origin(site_origin)
        if not path.startswith('/api/developer-link/') or '?' in path or '#' in path:
            raise DeveloperError('LINK_DESTINATION_INVALID', 'invalid developer-link endpoint')
        encoded = canonical(body)
        if len(encoded) > 262144:
            raise DeveloperError('LINK_REQUEST_TOO_LARGE', 'developer-link request exceeds its bound')
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if secret is not None:
            headers['Authorization'] = 'Bearer ' + secret
        request = urllib.request.Request(site_origin + path, data=encoded, headers=headers, method='POST')
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if response.geturl() != site_origin + path:
                    raise DeveloperError('LINK_REDIRECT_REFUSED', 'developer-link redirects are refused')
                result = decode_json(response.read(262145), max_bytes=262144)
        except urllib.error.HTTPError as exc:
            code = 'LINK_AUTHORITY_REJECTED' if exc.code in (401, 403, 410) else 'LINK_REMOTE_REJECTED'
            if 300 <= exc.code < 400:
                code = 'LINK_REDIRECT_REFUSED'
            # Never echo server text, request headers, or credential-bearing URLs.
            raise DeveloperError(code, 'the paired site rejected this developer-link operation') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise DeveloperError('LINK_OFFLINE', 'the paired site could not be reached') from None
        if not isinstance(result, dict):
            raise DeveloperError('LINK_RESPONSE_INVALID', 'site response must be an object')
        return result
