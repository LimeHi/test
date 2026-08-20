import base64
import json
from urllib.parse import urlparse, parse_qs, unquote


def _stream_settings(qs: dict, sni_default: str = ""):
    network = qs.get("type", ["tcp"])[0]
    security = qs.get("security", ["none"])[0]
    stream = {"network": network, "security": security}

    sni = qs.get("sni", [sni_default])[0]
    fp = qs.get("fp", [""])[0]
    alpn = qs.get("alpn", [""])[0]

    if security == "tls":
        stream["tlsSettings"] = {
            "serverName": sni,
            "fingerprint": fp or "chrome",
            "allowInsecure": False,
        }
        if alpn:
            stream["tlsSettings"]["alpn"] = alpn.split(",")
    elif security == "reality":
        stream["realitySettings"] = {
            "serverName": sni,
            "fingerprint": fp or "chrome",
            "publicKey": qs.get("pbk", [""])[0],
            "shortId": qs.get("sid", [""])[0],
            "spiderX": qs.get("spx", ["/"])[0],
        }

    if network == "ws":
        stream["wsSettings"] = {
            "path": qs.get("path", ["/"])[0],
            "headers": {"Host": qs.get("host", [sni])[0]} if qs.get("host") else {},
        }
    elif network == "grpc":
        stream["grpcSettings"] = {"serviceName": qs.get("serviceName", [""])[0]}
    elif network in ("xhttp", "http"):
        stream["xhttpSettings"] = {
            "path": qs.get("path", ["/"])[0],
            "host": qs.get("host", [sni])[0],
            "mode": qs.get("mode", ["auto"])[0],
        }

    return stream


def vless_to_outbound(raw: str):
    parsed = urlparse(raw)
    qs = parse_qs(parsed.query)
    return {
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": parsed.hostname,
                "port": parsed.port,
                "users": [{
                    "id": parsed.username,
                    "encryption": qs.get("encryption", ["none"])[0],
                    "flow": qs.get("flow", [""])[0],
                }],
            }]
        },
        "streamSettings": _stream_settings(qs, sni_default=parsed.hostname),
    }


def trojan_to_outbound(raw: str):
    parsed = urlparse(raw)
    qs = parse_qs(parsed.query)
    return {
        "protocol": "trojan",
        "settings": {
            "servers": [{
                "address": parsed.hostname,
                "port": parsed.port,
                "password": unquote(parsed.username or ""),
            }]
        },
        "streamSettings": _stream_settings(qs, sni_default=parsed.hostname),
    }


def vmess_to_outbound(raw: str):
    body = raw[len("vmess://"):]
    padded = body + "=" * (-len(body) % 4)
    data = json.loads(base64.b64decode(padded).decode("utf-8", errors="ignore"))
    network = data.get("net", "tcp")
    tls_val = (data.get("tls") or "").lower()
    security = "tls" if tls_val == "tls" else "none"
    stream = {"network": network, "security": security}

    if security == "tls":
        stream["tlsSettings"] = {"serverName": data.get("sni") or data.get("host") or data.get("add")}
    if network == "ws":
        stream["wsSettings"] = {"path": data.get("path", "/"), "headers": {"Host": data.get("host", "")}}
    elif network == "grpc":
        stream["grpcSettings"] = {"serviceName": data.get("path", "")}

    return {
        "protocol": "vmess",
        "settings": {
            "vnext": [{
                "address": data.get("add"),
                "port": int(data.get("port")),
                "users": [{
                    "id": data.get("id"),
                    "alterId": int(data.get("aid", 0) or 0),
                    "security": "auto",
                }],
            }]
        },
        "streamSettings": stream,
    }


def ss_to_outbound(raw: str):
    parsed = urlparse(raw)
    host, port = parsed.hostname, parsed.port
    userinfo = parsed.username

    if host and port and userinfo:
        try:
            padded = userinfo + "=" * (-len(userinfo) % 4)
            decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
            method, password = decoded.split(":", 1)
        except Exception:
            method, password = userinfo.split(":", 1)
    else:
        # старый формат: ss://base64(method:password@host:port)
        body = raw[len("ss://"):].split("#")[0]
        padded = body + "=" * (-len(body) % 4)
        decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
        method_password, hostport = decoded.rsplit("@", 1)
        host, port_s = hostport.rsplit(":", 1)
        port = int(port_s)
        method, password = method_password.split(":", 1)

    return {
        "protocol": "shadowsocks",
        "settings": {
            "servers": [{
                "address": host,
                "port": int(port),
                "method": method,
                "password": password,
            }]
        },
    }


CONVERTERS = {
    "vless": vless_to_outbound,
    "trojan": trojan_to_outbound,
    "vmess": vmess_to_outbound,
    "ss": ss_to_outbound,
}


def to_outbound(raw: str, protocol: str):
    """None, если протокол/формат не поддержан — тогда deep-check для этого
    конфига просто пропускается, а вердикт остаётся по TCP/TLS."""
    fn = CONVERTERS.get(protocol)
    if not fn:
        return None
    try:
        return fn(raw)
    except Exception:
        return None
