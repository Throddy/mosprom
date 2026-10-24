"""Прямая ссылка на поток публичной камеры Ivideon через openapi, как у плеера open.ivideon.com.

Для hls и flv openapi отвечает перенаправлением на сам поток, для ws-fmp4 — JSON {"success": true, "result": {"url"}}.
Ссылка содержит токен и живёт ограниченное время: её нельзя писать в лог.
"""
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

API = "https://openapi-alpha.ivideon.com/cameras/{camera_id}/live_stream"
HEADERS = {
    "Origin": "https://open.ivideon.com",
    "Referer": "https://open.ivideon.com/",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                   "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"),
    "Accept": "*/*",
}
HOSTS = ("open.ivideon.com", "public.ivideon.com")
_TOKEN = re.compile(r'((?:access_)?token|sig|signature)=[^&"\s]+')


def _hide(text: str) -> str:
    return _TOKEN.sub(lambda m: m.group(1) + "=<скрыто>", text)


def _context() -> ssl.SSLContext:
    # Python с python.org на macOS не видит системные корневые сертификаты; certifi приходит с httpx
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def camera_id(page: str) -> str | None:
    """camera_id из адреса open.ivideon.com/embed/v3/<id>/ или public.ivideon.com/camera/<id>/."""
    parts = urllib.parse.urlsplit(page)
    if parts.hostname not in HOSTS:
        return None
    m = re.search(r"/(?:embed/v3|camera)/([^/]+)", parts.path)
    return urllib.parse.unquote(m.group(1)) if m else None


def safe(url: str) -> str:
    """Адрес без токенов и параметров: только схема, хост и путь."""
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}{parts.path}"


def resolve(camera_id: str, fmt: str) -> str:
    url = API.format(camera_id=camera_id) + "?" + urllib.parse.urlencode(
        {"op": "GET", "access_token": "public", "q": 2, "video_codecs": "h264", "format": fmt})
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_context()))
    try:
        response = opener.open(urllib.request.Request(url, headers=HEADERS), timeout=15)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
            return e.headers["Location"]
        raise RuntimeError(f"ivideon {e.code}: {_hide(e.read(300).decode('utf-8', 'replace'))}")
    body = response.read(4096).decode("utf-8", "replace")
    try:
        data = json.loads(body)
    except ValueError:
        raise RuntimeError(f"ivideon: ответ не JSON: {_hide(body[:200])}")
    stream = (data.get("result") or {}).get("url") if data.get("success") is True else None
    if not stream:
        raise RuntimeError(f"ivideon: нет url в ответе: {_hide(body[:200])}")
    return stream
