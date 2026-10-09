"""Idempotent AdGuard Home rewrites using HTTPS and HTTP Basic Auth."""

import base64
import ipaddress
import json
import urllib.error
import urllib.request

from .common import InstallError
from .context import InstallContext
from .traefik import domain_value


def validate_settings(context: InstallContext) -> None:
    for name in ("PUBLIC_DOMAIN", "ADGUARD_USERNAME", "ADGUARD_PASSWORD"):
        if not context.variables.get(name):
            raise InstallError(f"DNS AdGuard cần biến {name}.")
    domain_value(context.variables["PUBLIC_DOMAIN"])


def register_rewrites(context: InstallContext) -> None:
    validate_settings(context)
    variables = context.variables
    base = f"https://dns.{variables['PUBLIC_DOMAIN']}/control"
    domain = f"{context.service_name}.{variables['PUBLIC_DOMAIN']}"
    credentials = f"{variables['ADGUARD_USERNAME']}:{variables['ADGUARD_PASSWORD']}"
    authorization = "Basic " + base64.b64encode(credentials.encode("utf-8")).decode("ascii")

    def request(endpoint: str, payload: dict[str, str] | None = None) -> bytes:
        headers = {"Authorization": authorization}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        message = urllib.request.Request(base + endpoint, data=body, headers=headers,
                                         method="POST" if payload is not None else "GET")
        try:
            with urllib.request.urlopen(message, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            error.close()
            raise InstallError(f"AdGuard {endpoint}: HTTP {error.code}.") from error
        except (urllib.error.URLError, OSError) as error:
            # Do not report headers, response bodies or credentials.
            raise InstallError(f"Không kết nối được AdGuard tại {base}.") from error

    try:
        rewrites = json.loads(request("/rewrite/list"))
    except (ValueError, UnicodeError) as error:
        raise InstallError("AdGuard trả về JSON không hợp lệ.") from error
    if not isinstance(rewrites, list) or any(not isinstance(item, dict)
                                            or not isinstance(item.get("domain"), str)
                                            or not isinstance(item.get("answer"), str) for item in rewrites):
        raise InstallError("AdGuard rewrite/list phải trả về danh sách domain/answer.")
    known = set()
    for item in rewrites:
        try:
            answer = str(ipaddress.ip_address(item["answer"]))
        except ValueError:
            answer = item["answer"]
        known.add((item["domain"].lower(), answer))
    answers = [context.host_ipv4]
    ula = ipaddress.IPv6Address(context.host_ula_ipv6)
    if ula in ipaddress.ip_network("fc00::/7"):
        answers.append(str(ula))
    else:
        context.log("[WARNING] Không có ULA IPv6; bỏ qua DNS rewrite IPv6.")
    for answer in answers:
        if (domain.lower(), answer) in known:
            context.log(f">>> DNS rewrite đã tồn tại: {domain} -> {answer}")
            continue
        request("/rewrite/add", {"domain": domain, "answer": answer})
        known.add((domain.lower(), answer))
        context.log(f">>> Đã thêm DNS rewrite: {domain} -> {answer}")
