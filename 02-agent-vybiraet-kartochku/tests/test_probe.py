import json
import socket
import urllib.error

import pytest

from conftest import FIXTURES
from razbor02 import mcp

RAW_PRODUCT = {
    "id": "gid://shopify/p/AAA", "title": "Trail Shoe X",
    "description": {"plain": '<p>Fit: <a href="https://shop-escape-outdoors.myshopify.com/pages/fit?_gsid=S2">guide</a></p>'},
    "media": [{"type": "image", "url": "https://cdn.shopify.com/s/files/1/0332/9363/1623/files/a.jpg",
               "alt_text": "Trail Shoe X shop-escape-outdoors"},
              {"type": "image", "url": "https://cdn.shopify.com/s/files/1/1563/9833/files/b.png", "alt_text": ""}],
    "variants": [{
        "id": "gid://shopify/ProductVariant/1", "price": {"amount": 18000, "currency": "USD"},
        "url": "https://shopescapeoutdoors.com/products/x?variant=1&_gsid=SECRET1&utm_source=shopify&utm_medium=catalog",
        "checkout_url": "https://shopescapeoutdoors.com/cart/1:1?_gsid=SECRET1&utm_source=shopify&payment=shop_pay",
        "seller": {"id": "gid://shopify/Shop/31452004483", "name": "Shop Escape Outdoors ",
                   "url": "https://shopescapeoutdoors.com", "domain": "shop-escape-outdoors.myshopify.com"},
        "rating": {"value": 4.8, "count": 29}, "availability": {"available": True},
    }],
}


def _resp(payload, structured=True):
    r = {"jsonrpc": "2.0", "id": 2, "result": {"resultType": "complete",
                                             "content": [{"type": "text", "text": json.dumps(payload)}]}}
    if structured:
        r["result"]["structuredContent"] = payload
    return r


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --- запрос ------------------------------------------------------------------

def test_tools_list_request_is_stateless_2026_07_28():
    headers, body = mcp.build_request("tools/list", {})
    assert headers["MCP-Protocol-Version"] == "2026-07-28" and headers["Mcp-Method"] == "tools/list"
    assert "Mcp-Name" not in headers and "Mcp-Session-Id" not in headers
    assert headers["Accept"] == "application/json, text/event-stream"
    meta = body["params"]["_meta"]
    assert meta["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
    assert meta["io.modelcontextprotocol/clientInfo"]["name"] == "pro-llm-razbor"


def test_tools_call_request_names_the_tool():
    headers, body = mcp.build_request("tools/call", {"name": "search_catalog", "arguments": {"catalog": {"query": "q"}}})
    assert headers["Mcp-Method"] == "tools/call" and headers["Mcp-Name"] == "search_catalog"
    assert body["params"]["arguments"]["catalog"]["query"] == "q" and "_meta" in body["params"]


def test_search_arguments_put_hard_requirements_into_filters():
    args = mcp.search_arguments("shoes", filters={"rating": {"variant": {"min": 4, "min_count": 20}}}, limit=50)
    cat = args["catalog"]
    assert cat["context"] == {"address_country": "US", "currency": "USD", "language": "en"}
    assert cat["filters"]["rating"]["variant"]["min_count"] == 20 and cat["pagination"] == {"limit": 50}
    assert "filters" not in mcp.search_arguments("shoes")["catalog"]


# --- ответ -------------------------------------------------------------------

def test_decode_json_and_sse():
    msg = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    assert mcp.decode(json.dumps(msg), "application/json") == msg
    sse = f"event: message\ndata: {json.dumps(msg)}\n\n"
    assert mcp.decode(sse, "text/event-stream; charset=utf-8") == msg


def test_parse_search_reads_text_content():
    payload = {"ucp": {"version": "2026-08-25"}, "products": [RAW_PRODUCT]}
    assert mcp.parse_search(_resp(payload, structured=False))["products"][0]["title"] == "Trail Shoe X"


def test_parse_errors_raise():
    with pytest.raises(mcp.McpError):
        mcp.parse_search({"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "bad"}})
    bad = {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"type": "text", "text": "nope"}]}}
    with pytest.raises(mcp.McpError, match="nope"):
        mcp.parse_search(bad)


def test_rating_filter_looks_at_variant_rating():
    p = json.loads(json.dumps(RAW_PRODUCT))
    assert mcp.rating_ok(p, 4, 20)
    assert not mcp.rating_ok(p, 4, 30)
    p["variants"][0].pop("rating")
    p["rating"] = {"value": 4.9, "count": 500}  # рейтинг товара без рейтинга варианта фильтр не проходит
    assert not mcp.rating_ok(p, 4, 20)


def test_filter_effect_counts():
    def prod(pid, count):
        return {"id": pid, "variants": [{"rating": {"value": 4.5, "count": count}}] if count else [{}]}
    base = [prod("a", 30), prod("b", 5), prod("c", 0), prod("d", 0)]
    filtered = [prod("a", 30), prod("x", 40), prod("y", 25)]
    e = mcp.filter_effect(base, filtered, 4, 20)
    assert e == {"base": 4, "base_meeting": 1, "base_dropped": 3, "filtered": 3, "filtered_meeting": 3,
                 "overlap": 1, "replaced": 2, "min": 4, "min_count": 20}


# --- обезличивание ------------------------------------------------------------

def test_anonymize_removes_merchant_and_tracking():
    out = mcp.anonymize_response(_resp({"ucp": {"version": "v"}, "products": [RAW_PRODUCT]}))
    assert "structuredContent" not in out["result"]
    text = out["result"]["content"][0]["text"]
    for leak in ["escape", "Escape", "SECRET1", "31452004483", "0332/9363", "1563/9833", "_gsid", "myshopify"]:
        assert leak not in text, leak
    v = json.loads(text)["products"][0]["variants"][0]
    assert v["seller"] == {"id": "gid://shopify/Shop/merchant-01", "name": "Merchant 01",
                           "url": "https://merchant-01.example", "domain": "merchant-01.example"}
    assert v["url"].startswith("https://merchant-01.example/products/x?") and "utm_source=shopify" in v["url"]
    assert "payment=shop_pay" in v["checkout_url"]
    assert v["price"] == {"amount": 18000, "currency": "USD"} and v["rating"]["count"] == 29


def test_slim_tools_keeps_catalog_schemas_only():
    resp = {"jsonrpc": "2.0", "id": 1, "result": {"tools": [
        {"name": "search_catalog", "description": "d", "inputSchema": {"x": 1}, "annotations": {"readOnlyHint": True}},
        {"name": "create_cart", "description": "d", "inputSchema": {"x": 1}, "annotations": {"readOnlyHint": False}},
    ]}}
    tools = mcp.slim_tools(resp)["result"]["tools"]
    assert "inputSchema" in tools[0] and "inputSchema" not in tools[1] and tools[1]["annotations"]


# --- офлайн-снимок 17.10.2026 -------------------------------------------------

def test_fixture_tools():
    tools = mcp.parse_tools(load("tools.json"))
    names = [t["name"] for t in tools]
    assert len(names) == 17
    assert {"search_catalog", "lookup_catalog", "get_product", "create_cart", "create_checkout",
            "complete_checkout"} <= set(names)
    assert next(t for t in tools if t["name"] == "search_catalog")["read_only"] is True
    assert mcp.attribute_names(load("tools.json")) == ["Color", "Size", "Target gender"]
    filters = mcp.search_filters(load("tools.json"))
    assert {"attributes", "available", "price", "rating", "ships_to"} <= set(filters)
    assert not {"min_count", "country", "values", "max"} & set(filters)  # вложенные поля — не фильтры верхнего уровня


def test_fixture_search_card_fields():
    payload = mcp.parse_search(load("search.json"))
    assert payload["ucp"]["version"] == "2026-08-25" and len(payload["products"]) == 10
    fields = {f["field"]: f["present"] for f in mcp.card_fields(payload["products"])}
    assert fields["title"] == 10 and fields["variants[].price"] == 10
    assert 0 < fields["rating"] < 10  # у части карточек рейтинга нет вовсе
    assert 0 < fields["metadata.tech_specs"] < 10
    assert "options[Color]" in fields


def test_fixtures_are_anonymized():
    for name in ["search.json", "search-base.json", "search-filtered.json"]:
        text = (FIXTURES / name).read_text(encoding="utf-8")
        assert "_gsid" not in text and "myshopify.com" not in text and "/s/files/1/" not in text, name
        payload = mcp.parse_search(load(name))
        hosts = {v["seller"]["domain"] for p in payload["products"] for v in p["variants"] if v.get("seller")}
        assert hosts and all(h.endswith(".example") for h in hosts), name


def test_fixture_filter_effect():
    base = mcp.parse_search(load("search-base.json"))["products"]
    filt = mcp.parse_search(load("search-filtered.json"))["products"]
    e = mcp.filter_effect(base, filt, 4, 20)
    assert e["base"] == len(base) >= 20 and e["base_meeting"] < e["base"] // 2
    assert e["filtered_meeting"] == e["filtered"]  # всё, что вернул фильтр, ему соответствует


# --- запуск probe -------------------------------------------------------------

def _fake_post(headers, body, timeout=30, url=mcp.ENDPOINT):
    if headers["Mcp-Method"] == "tools/list":
        return load("tools.json")
    filters = body["params"]["arguments"]["catalog"].get("filters", {})
    if "rating" in filters:
        return load("search-filtered.json")
    if "attributes" in filters:
        return load("search.json")
    return load("search-base.json")


def test_run_probe_offline_writes_files(tmp_path):
    s = mcp.run_probe(tmp_path, FIXTURES, offline=True)
    assert s["source"] == "fixtures" and s["tools"] == 17 and s["ucp_version"] == "2026-08-25"
    for f in ["tools.json", "search.json", "search-base.json", "search-filtered.json", "summary.json"]:
        assert (tmp_path / f).exists(), f


def test_run_probe_live_path_with_fake_network(tmp_path):
    s = mcp.run_probe(tmp_path, FIXTURES, post=_fake_post)
    assert s["source"] == "live" and s["products"] == 10
    assert s["filter_effect"] == mcp.run_probe(tmp_path / "o", FIXTURES, offline=True)["filter_effect"]


def test_run_probe_falls_back_without_network(tmp_path):
    def down(*a, **kw):
        raise urllib.error.URLError("нет сети")
    s = mcp.run_probe(tmp_path, FIXTURES, post=down)
    assert s["source"] == "fixtures" and "нет сети" in s["note"]


def test_run_probe_retries_once_on_transient_error(tmp_path):
    calls = {"n": 0}

    def flaky(headers, body, timeout=30, url=mcp.ENDPOINT):
        calls["n"] += 1
        if calls["n"] == 2:
            raise TimeoutError("timed out")
        return _fake_post(headers, body)
    s = mcp.run_probe(tmp_path, FIXTURES, post=flaky)
    assert s["source"] == "live" and calls["n"] == 5


def _online():
    try:
        socket.create_connection(("mcp.shop.com", 443), timeout=3).close()
        return True
    except OSError:
        return False


@pytest.mark.live
@pytest.mark.skipif(not _online(), reason="нет сети до mcp.shop.com")
def test_live_shop_mcp(tmp_path):
    s = mcp.run_probe(tmp_path, FIXTURES)
    assert s["source"] == "live", s["note"]
    assert s["tools"] >= 10 and "search_catalog" in s["tool_names"]
    assert s["products"] > 0
