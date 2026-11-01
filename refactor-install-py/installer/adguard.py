"""Idempotent AdGuard Home rewrites using HTTPS and HTTP Basic Auth."""

import base64
import ipaddress
import json
import re
import urllib.error
import urllib.request

from .common import InstallError
from .context import InstallContext
from .traefik import domain_value

def is_bootstrap_service(quadlet: str) -> bool:
    """Recognize AdGuard Home by the rendered container image, including bundles."""
    in_container = False
    for line in quadlet.splitlines():
        line = line.strip()
        if line == "---" or line.startswith("["):
            in_container = line == "[Container]"
        elif in_container and (match := re.match(r"Image\s*=\s*(.*)$", line)):
            image = match[1].strip()
            if len(image) >= 2 and image[0] in "\"'" and image[-1] == image[0]:
                image = image[1:-1]
            if re.fullmatch(r"(?:[^/\s]+/)*adguard/adguardhome(?::[^@\s]+)?(?:@[^:\s]+:[^\s]+)?", image):
                return True
    return False


def resolve_base_url(context: InstallContext) -> str:
    variables = context.variables
    base_override = variables.get("AGH_BASE_URL")
    if base_override:
        base = base_override.rstrip("/")
        if not base.endswith("/control"):
            base += "/control"
        return base
    base = f"https://dns.{variables['PUBLIC_DOMAIN']}/control"
    context.log(f"[WARN] Do không có cấu hình AGH_BASE_URL, URL sẽ được dùng để gọi API là {base}")
    return base


def get_authorization(variables: dict[str, str]) -> str:
    credentials = f"{variables['ADGUARD_USERNAME']}:{variables['ADGUARD_PASSWORD']}"
    return "Basic " + base64.b64encode(credentials.encode("utf-8")).decode("ascii")


def make_request(base: str, authorization: str, endpoint: str, payload: dict[str, str] | None = None) -> bytes:
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
        if error.code in (401, 403):
            raise InstallError(f"AdGuard {endpoint}: HTTP {error.code} (xác thực thất bại, kiểm tra username/password).") from error
        raise InstallError(f"AdGuard {endpoint}: HTTP {error.code}.") from error
    except (urllib.error.URLError, OSError) as error:
        # Do not report headers, response bodies or credentials.
        raise InstallError(f"Không kết nối được AdGuard tại {base}.") from error


def check_adguard_status(base: str, authorization: str) -> dict[str, object]:
    content = make_request(base, authorization, "/status")
    try:
        data = json.loads(content)
    except (ValueError, UnicodeError) as error:
        raise InstallError(f"Phản hồi từ {base}/status không phải JSON hợp lệ.") from error
    if not isinstance(data, dict):
        raise InstallError(f"Phản hồi từ {base}/status không đúng định dạng AdGuard Home.")
    required_keys = ("version", "protection_enabled", "running")
    if not all(k in data for k in required_keys):
        raise InstallError(f"Phản hồi từ {base}/status không đúng định dạng AdGuard Home (thiếu trường cấu trúc ServerStatus).")
    return data


def validate_settings(context: InstallContext, *, test_connection: bool = True) -> str:
    variables = context.variables
    for name in ("PUBLIC_DOMAIN", "ADGUARD_USERNAME", "ADGUARD_PASSWORD"):
        if not variables.get(name):
            raise InstallError(f"DNS AdGuard cần biến {name}.")
    domain_value(variables["PUBLIC_DOMAIN"])

    base = resolve_base_url(context)
    if test_connection:
        authorization = get_authorization(variables)
        data = check_adguard_status(base, authorization)
        version = data.get("version", "unknown")
        context.log(f">>> Đã kết nối AdGuard Home ({version}) tại {base}.")
    return base


def register_rewrites(context: InstallContext) -> None:
    base = validate_settings(context, test_connection=False)
    variables = context.variables
    domain = f"{context.service_name}.{variables['PUBLIC_DOMAIN']}"
    authorization = get_authorization(variables)

    def request(endpoint: str, payload: dict[str, str] | None = None) -> bytes:
        return make_request(base, authorization, endpoint, payload)

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
