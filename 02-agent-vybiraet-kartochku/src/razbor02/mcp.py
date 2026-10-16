"""probe: живой Shop MCP (https://mcp.shop.com/) — stateless MCP 2026-07-28, без сессии.

Четыре запроса: список инструментов, поиск как у агента (с фильтром по полу), и пара «тот же запрос без фильтра /
с фильтром по рейтингу» — чтобы увидеть, сколько товаров отсекает жёсткий фильтр. Ответы обезличиваются
(магазины → merchant-NN.example, без трекинговых _gsid) и пишутся в eval/out/live/. Без сети или с --offline
берётся снимок eval/fixtures/.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ENDPOINT = "https://mcp.shop.com/"
PROTOCOL = "2026-07-28"
CLIENT = {"name": "pro-llm-razbor", "version": "0.1"}
QUERY = "waterproof winter running shoes"
CONTEXT = {"address_country": "US", "currency": "USD", "language": "en"}
SEARCH_FILTERS = {"attributes": [{"name": "Target gender", "values": ["Male"]}]}
RATING_FILTER = {"rating": {"variant": {"min": 4, "min_count": 20}}}
EFFECT_LIMIT = 50
CATALOG_TOOLS = {"search_catalog", "lookup_catalog", "get_product"}
TOOL_GROUPS = [
    ("Каталог", ["search_catalog", "lookup_catalog", "get_product"]),
    ("Корзина", ["create_cart", "get_cart", "update_cart"]),
    ("Оформление и оплата", ["create_checkout", "get_checkout", "update_checkout", "complete_checkout"]),
    ("Лимит трат", ["create_spend_request", "get_spend_request", "update_spend_request", "cancel_spend_request",
                    "complete_spend_request"]),
    ("Аккаунт покупателя", ["get_account", "search_orders"]),
]


class McpError(RuntimeError):
    pass


# --- запрос ------------------------------------------------------------------

def build_request(method: str, params: dict, *, id: int = 1) -> tuple[dict, dict]:
    """Заголовки и тело JSON-RPC для stateless MCP: версия протокола и метод — в заголовках, сессии нет."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL,
        "Mcp-Method": method,
    }
    if method == "tools/call":
        headers["Mcp-Name"] = params["name"]
    meta = {"io.modelcontextprotocol/protocolVersion": PROTOCOL,
            "io.modelcontextprotocol/clientCapabilities": {},
            "io.modelcontextprotocol/clientInfo": CLIENT}
    body = {"jsonrpc": "2.0", "id": id, "method": method, "params": {**params, "_meta": meta}}
    return headers, body


def search_arguments(query: str, filters: dict | None = None, limit: int | None = None) -> dict:
    catalog: dict = {"query": query, "context": dict(CONTEXT)}
    if filters:
        catalog["filters"] = filters
    if limit:
        catalog["pagination"] = {"limit": limit}
    return {"catalog": catalog}


def decode(text: str, content_type: str) -> dict:
    """Ответ приходит JSON-ом или потоком SSE — берём последнее событие с JSON-RPC."""
    if "text/event-stream" in content_type:
        msgs = [json.loads(line[5:].strip()) for line in text.splitlines() if line.startswith("data:")]
        if not msgs:
            raise McpError("пустой поток SSE")
        return msgs[-1]
    return json.loads(text)


def post(headers: dict, body: dict, timeout: float = 30, url: str = ENDPOINT) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — адрес фиксирован
        return decode(r.read().decode("utf-8"), r.headers.get("Content-Type", ""))


# --- ответ -------------------------------------------------------------------

def _result(resp: dict) -> dict:
    if "error" in resp:
        raise McpError(f"{resp['error'].get('code')}: {resp['error'].get('message')}")
    res = resp.get("result") or {}
    if res.get("isError"):
        raise McpError(" ".join(c.get("text", "") for c in res.get("content", [])) or "isError")
    return res


def parse_tools(resp: dict) -> list[dict]:
    return [{"name": t["name"], "description": t.get("description", ""),
             "read_only": bool((t.get("annotations") or {}).get("readOnlyHint"))}
            for t in _result(resp).get("tools", [])]


def _tool(resp: dict, name: str) -> dict:
    return next(t for t in _result(resp)["tools"] if t["name"] == name)


def _walk(obj):
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def attribute_names(tools_resp: dict) -> list[str]:
    """Имена атрибутов, по которым search_catalog фильтрует жёстко — из описания схемы."""
    for node in _walk(_tool(tools_resp, "search_catalog").get("inputSchema", {})):
        if isinstance(node, dict) and isinstance(node.get("description"), str):
            m = re.search(r"Supported names:\s*([^.]+)\.", node["description"])
            if m:
                return [x.strip() for x in m.group(1).split(",")]
    return []


def search_filters(tools_resp: dict) -> list[str]:
    """Все поля filters в схеме search_catalog (жёсткие требования агента)."""
    schema = _tool(tools_resp, "search_catalog").get("inputSchema", {})
    defs = schema.get("$defs", {})
    names: list[str] = []

    def top_level(node) -> None:  # свойства самого объекта filters и его allOf/anyOf, без вложенных полей
        if not isinstance(node, dict):
            return
        if "$ref" in node:
            top_level(defs.get(node["$ref"].rsplit("/", 1)[-1]))
        names.extend(k for k in node.get("properties", {}) if k not in names)
        for key in ("allOf", "anyOf", "oneOf"):
            for sub in node.get(key, []):
                top_level(sub)

    for node in _walk(schema):
        if isinstance(node, dict) and isinstance(node.get("properties"), dict) and "filters" in node["properties"]:
            top_level(node["properties"]["filters"])
    return names


def parse_search(resp: dict) -> dict:
    res = _result(resp)
    for c in res.get("content", []):
        if c.get("type") == "text":
            return json.loads(c["text"])
    if "structuredContent" in res:
        return res["structuredContent"]
    raise McpError("в ответе нет каталога")


def card_fields(products: list[dict]) -> list[dict]:
    """Какие поля карточки агент видит в ответе и у скольких товаров они заполнены."""
    counts: dict[str, int] = {}

    def seen(key: str) -> None:
        counts[key] = counts.get(key, 0) + 1

    for p in products:
        keys: list[str] = [k for k, v in p.items() if v not in (None, "", [], {})]
        keys += [f"metadata.{k}" for k, v in (p.get("metadata") or {}).items() if v]
        keys += [f"options[{o['name']}]" for o in p.get("options") or []]
        if any((m.get("alt_text") or "").strip() for m in p.get("media") or []):
            keys.append("media[].alt_text")
        vkeys: list[str] = []
        for v in p.get("variants") or []:
            vkeys += [f"variants[].{k}" for k, val in v.items() if val not in (None, "", [], {}) and
                      f"variants[].{k}" not in vkeys]
        for k in dict.fromkeys(keys + vkeys):
            seen(k)
    return [{"field": k, "present": n, "of": len(products)} for k, n in counts.items()]


def rating_ok(product: dict, min_value: float, min_count: int) -> bool:
    """Фильтр rating.variant: хотя бы у одного варианта рейтинг не ниже min при count не меньше min_count."""
    for v in product.get("variants") or []:
        r = v.get("rating") or {}
        if r.get("value") is not None and r.get("count") is not None \
                and r["value"] >= min_value and r["count"] >= min_count:
            return True
    return False


def filter_effect(base: list[dict], filtered: list[dict], min_value: float, min_count: int) -> dict:
    meeting = sum(rating_ok(p, min_value, min_count) for p in base)
    overlap = len({p["id"] for p in base} & {p["id"] for p in filtered})
    return {"base": len(base), "base_meeting": meeting, "base_dropped": len(base) - meeting,
            "filtered": len(filtered), "filtered_meeting": sum(rating_ok(p, min_value, min_count) for p in filtered),
            "overlap": overlap, "replaced": len(filtered) - overlap, "min": min_value, "min_count": min_count}


# --- обезличивание ------------------------------------------------------------

URL_RE = re.compile(r"https?://[^\s\"'<>\\]+")


class _Merchants:
    def __init__(self) -> None:
        self.by_host: dict[str, str] = {}
        self.tokens: list[tuple[re.Pattern, str]] = []

    def _code(self, host: str) -> str:
        host = host.lower().removeprefix("www.")
        if host not in self.by_host:
            self.by_host[host] = f"merchant-{len(set(self.by_host.values())) + 1:02d}"
            self._token(host, self.by_host[host])
            labels = host.split(".")
            if len(labels) >= 2 and len(labels[-2]) >= 5:
                self._token(labels[-2], self.by_host[host])
        return self.by_host[host]

    def _token(self, text: str, code: str) -> None:
        text = text.strip()
        if len(text) >= 4:
            self.tokens.append((re.compile(re.escape(text), re.IGNORECASE), f"Merchant {code[-2:]}"))

    def seller(self, s: dict) -> dict:
        host = urllib.parse.urlsplit(s.get("url") or "").hostname or s.get("domain", "")
        code = self._code(host)
        if s.get("domain"):
            self.by_host.setdefault(s["domain"].lower(), code)
            slug = s["domain"].split(".")[0]
            self._token(slug, code)
            self._token(slug.replace("-", " "), code)
        self._token(s.get("name") or "", code)
        return {"id": f"gid://shopify/Shop/{code}", "name": f"Merchant {code[-2:]}",
                "url": f"https://{code}.example", "domain": f"{code}.example"}

    def url(self, value: str) -> str:
        u = urllib.parse.urlsplit(value)
        query = urllib.parse.urlencode([(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True)
                                        if k != "_gsid"], safe=":")
        path = re.sub(r"/s/files/(?:\d+/)+", "/s/files/redacted/", u.path)
        host = u.hostname or ""
        if host and host != "cdn.shopify.com":
            host = f"{self._code(host)}.example"
        return urllib.parse.urlunsplit((u.scheme, host, path, query, u.fragment))

    def text(self, value: str) -> str:
        for pattern, repl in sorted(self.tokens, key=lambda t: -len(t[0].pattern)):
            value = pattern.sub(repl, value)
        return value


def anonymize_payload(payload: dict) -> dict:
    m = _Merchants()
    for p in payload.get("products", []):
        for v in p.get("variants") or []:
            if isinstance(v.get("seller"), dict):
                v["seller"] = m.seller(v["seller"])

    def fix(obj, key=""):
        if isinstance(obj, dict):
            return {k: (v if k == "seller" else fix(v, k)) for k, v in obj.items()}
        if isinstance(obj, list):
            return [fix(v, key) for v in obj]
        if isinstance(obj, str):  # ссылки бывают и внутри HTML-описаний
            return m.text(URL_RE.sub(lambda u: m.url(u.group(0)), obj))
        return obj
    return fix(payload)


def anonymize_response(resp: dict) -> dict:
    """Ответ search_catalog без магазинов и трекинга; каталог только в content[0].text (без дубля structuredContent)."""
    payload = anonymize_payload(parse_search(resp))
    result = {k: v for k, v in resp["result"].items() if k not in ("structuredContent", "content")}
    result["content"] = [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]
    return {**resp, "result": result}


def slim_tools(resp: dict) -> dict:
    """Схемы входа оставляем только у инструментов каталога — остальное для снимка лишнее."""
    tools = [t if t["name"] in CATALOG_TOOLS else {k: v for k, v in t.items() if k != "inputSchema"}
             for t in resp["result"]["tools"]]
    return {**resp, "result": {**resp["result"], "tools": tools}}


# --- запуск -------------------------------------------------------------------

def requests_plan() -> dict[str, tuple[str, dict]]:
    call = lambda args: ("tools/call", {"name": "search_catalog", "arguments": args})  # noqa: E731
    return {
        "tools": ("tools/list", {}),
        "search": call(search_arguments(QUERY, filters=SEARCH_FILTERS)),
        "search-base": call(search_arguments(QUERY, limit=EFFECT_LIMIT)),
        "search-filtered": call(search_arguments(QUERY, filters=RATING_FILTER, limit=EFFECT_LIMIT)),
    }


def summarize(responses: dict, source: str, note: str, captured: str) -> dict:
    tools = parse_tools(responses["tools"])
    search = parse_search(responses["search"])
    base = parse_search(responses["search-base"])["products"]
    filtered = parse_search(responses["search-filtered"])["products"]
    r = RATING_FILTER["rating"]["variant"]
    headers, body = build_request(*requests_plan()["search"], id=2)
    return {
        "source": source, "note": note, "captured": captured, "endpoint": ENDPOINT, "protocol": PROTOCOL,
        "tools": len(tools), "tool_names": [t["name"] for t in tools],
        "read_only": [t["name"] for t in tools if t["read_only"]],
        "attribute_filters": attribute_names(responses["tools"]),
        "search_filters": search_filters(responses["tools"]),
        "request": {"headers": headers, "body": body},
        "query": QUERY, "ucp_version": (search.get("ucp") or {}).get("version"),
        "products": len(search.get("products", [])),
        "total_count": (search.get("pagination") or {}).get("total_count"),
        "hints": search.get("next", []),
        "card_fields": card_fields(search.get("products", [])),
        "rating_filter": RATING_FILTER, "filter_effect": filter_effect(base, filtered, r["min"], r["min_count"]),
    }


def load_fixtures(fixtures_dir: Path | str) -> dict:
    return {k: json.loads((Path(fixtures_dir) / f"{k}.json").read_text(encoding="utf-8")) for k in requests_plan()}


def fixtures_date(fixtures_dir: Path | str) -> str:
    return json.loads((Path(fixtures_dir) / "meta.json").read_text(encoding="utf-8"))["captured"]


def run_probe(out_dir: Path | str, fixtures_dir: Path | str, *, offline: bool = False, timeout: float = 30,
              post=post) -> dict:
    out_dir, fixtures_dir = Path(out_dir), Path(fixtures_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    responses: dict[str, dict] = {}
    source, note, captured = "fixtures", "", ""
    if not offline:
        try:
            for i, (key, (method, params)) in enumerate(requests_plan().items(), start=1):
                headers, body = build_request(method, params, id=i)
                try:
                    resp = post(headers, body, timeout=timeout)
                except OSError:  # разовый сбой сети или таймаут — один повтор
                    resp = post(headers, body, timeout=timeout)
                parse_tools(resp) if key == "tools" else parse_search(resp)
                responses[key] = resp if key == "tools" else anonymize_response(resp)
            source, captured = "live", date.today().isoformat()
        except (OSError, McpError, ValueError, KeyError) as e:
            responses = {}
            note = f"живой Shop MCP недоступен ({e}); взят снимок eval/fixtures"
    if not responses:
        responses, captured = load_fixtures(fixtures_dir), fixtures_date(fixtures_dir)
    for key, resp in responses.items():
        (out_dir / f"{key}.json").write_text(json.dumps(resp, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = summarize(responses, source, note, captured)
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
