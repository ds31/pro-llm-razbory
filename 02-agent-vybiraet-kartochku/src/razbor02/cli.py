"""Запуск одной командой: uv run razbor02 all  (= probe + audit + report)."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from . import mcp
from .audit import load_rules, load_scenarios, run_audit
from .report import render_report
from .synth import read_csv

ARTICLE = "https://pro-llm.ru/blog/agent-pokupaet-v-chate-kogo-vyberet.html"
SNAPSHOT_KEYS = ["captured", "endpoint", "protocol", "tools", "tool_names", "read_only", "attribute_filters",
                 "search_filters", "query", "ucp_version", "products", "card_fields", "rating_filter", "filter_effect"]


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="razbor02", description="Shop MCP и аудит карточек под фильтры агента")
    p.add_argument("command", choices=["probe", "audit", "report", "all"])
    p.add_argument("--root", default=".", help="папка пакета (по умолчанию текущая)")
    p.add_argument("--offline", action="store_true", help="без сети: снимок Shop MCP из eval/fixtures")
    p.add_argument("--timeout", type=float, default=30, help="таймаут запроса к Shop MCP, с")
    p.add_argument("--catalog", default="", help="свой каталог CSV (колонки как в data/catalog.csv)")
    p.add_argument("--erp", default="", help="выгрузка учётной системы для своего каталога (необязательно)")
    p.add_argument("--write-reference", action="store_true", help="перезаписать eval/reference-run.json (автору)")
    return p


def reference_view(audit_summary: dict, snapshot: dict) -> dict:
    """Цифры статьи: аудит синтетического каталога + снимок Shop MCP (офлайн, детерминированно)."""
    return {
        "package": "02-agent-vybiraet-kartochku", "article": ARTICLE,
        "note": "audit — data/catalog.csv против data/catalog_erp.csv; shop_mcp_snapshot — eval/fixtures (17.10.2026)",
        "audit": audit_summary,
        "shop_mcp_snapshot": {k: snapshot[k] for k in SNAPSHOT_KEYS},
    }


def _probe(root: Path, args) -> dict:
    s = mcp.run_probe(root / "eval" / "out" / "live", root / "eval" / "fixtures", offline=args.offline,
                      timeout=args.timeout)
    src = "живой Shop MCP" if s["source"] == "live" else f"снимок {s['captured']} (eval/fixtures)"
    if s.get("note"):
        print(s["note"])
    e = s["filter_effect"]
    r = s["rating_filter"]["rating"]["variant"]
    print(f"probe: {src}")
    print(f"  инструментов: {s['tools']} — {', '.join(s['tool_names'])}")
    print(f"  жёсткие атрибуты: {', '.join(s['attribute_filters'])}; фильтры: {', '.join(s['search_filters'])}")
    print(f"  UCP {s['ucp_version']}; товаров в ответе: {s['products']} (найдено ~{s['total_count']})")
    print("  поля карточки: " + ", ".join(f"{f['field']} {f['present']}/{f['of']}" for f in s["card_fields"]))
    print(f"  фильтр rating.variant min={r['min']} min_count={r['min_count']}: из {e['base']} товаров без фильтра "
          f"проходят {e['base_meeting']}, отпадают {e['base_dropped']}; с фильтром {e['replaced']} из {e['filtered']} — другие товары")
    return s


def _audit(root: Path, args) -> dict:
    custom = bool(args.catalog)
    cards = read_csv(args.catalog if custom else root / "data" / "catalog.csv")
    erp_path = Path(args.erp) if args.erp else (None if custom else root / "data" / "catalog_erp.csv")
    erp = read_csv(erp_path) if erp_path and erp_path.exists() else None
    rules = load_rules(root / "audit" / "rules.yaml")
    res = run_audit(cards, erp, rules, load_scenarios(root / "eval" / "scenarios.yaml"))
    out = root / "eval" / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out / "cards.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sku", "title", "category", "score", "missing", "lost_in", "visible_in"])
        for c in res["cards"]:
            w.writerow([c["sku"], c["title"], c["category"], c["score"], "; ".join(c["missing"]),
                        " ".join(c["lost_in"]), " ".join(c["visible_in"])])
    a = res["summary"]
    print(f"audit: {a['cards']} карточек" + ("" if erp else " (без учётной системы: пул — все товары категории)"))
    print(f"  балл готовности: средний {a['readiness']['mean']}, медиана {a['readiness']['median']}, "
          f"80+ у {a['readiness']['ready_80plus']}, ниже 60 у {a['readiness']['below_60']}")
    for s in a["scenarios"]:
        cuts = ", ".join(f"{f['label']} −{f['cut']}" for f in s["funnel"] if f["cut"])
        print(f"  {s['id']}: агент покажет {s['visible']} из {s['pool']} ({s['visible_pct']} %). {cuts}")
    print("  топ-5 полей: " + ", ".join(f"{b['label']} ({b['hits']})" for b in a["top_blockers"]))
    print(f"  не видны хотя бы в одном сценарии: {a['lost_cards']}; чинятся 1 полем: {a['fixable']['1']}, "
          f"2 полями: {a['fixable']['2']}, 3+: {a['fixable']['3+']}")
    print(f"  по карточкам: {out / 'cards.csv'}")
    res["rules"] = rules
    return res


def _payloads(live: Path) -> dict:
    return {k: mcp.parse_search(json.loads((live / f"{k}.json").read_text(encoding="utf-8")))
            for k in ["search", "search-base", "search-filtered"]}


def _report(root: Path, probe: dict, audit: dict) -> Path:
    out = root / "eval" / "out"
    html = render_report(probe, _payloads(out / "live"), audit, audit.get("rules"))
    (out / "report.html").write_text(html, encoding="utf-8")
    print(f"отчёт: {out / 'report.html'}  (экраны #tools, #search, #audit)")
    return out / "report.html"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root).resolve()
    out = root / "eval" / "out"
    if args.command == "probe":
        _probe(root, args)
        return 0
    if args.command == "audit":
        _audit(root, args)
        return 0
    if args.command == "report":
        probe_file, audit_file = out / "live" / "summary.json", out / "audit.json"
        if not (probe_file.exists() and audit_file.exists()):
            print("нет результатов probe и audit — запустите: uv run razbor02 all")
            return 2
        audit = json.loads(audit_file.read_text(encoding="utf-8"))
        audit["rules"] = load_rules(root / "audit" / "rules.yaml")
        _report(root, json.loads(probe_file.read_text(encoding="utf-8")), audit)
        return 0
    probe = _probe(root, args)
    audit = _audit(root, args)
    (out / "audit.json").write_text(json.dumps({k: v for k, v in audit.items() if k != "rules"},
                                               ensure_ascii=False, indent=2), encoding="utf-8")
    _report(root, probe, audit)
    if args.catalog:
        return 0
    snapshot = mcp.summarize(mcp.load_fixtures(root / "eval" / "fixtures"), "fixtures", "",
                             mcp.fixtures_date(root / "eval" / "fixtures"))
    run = reference_view(audit["summary"], snapshot)
    text = json.dumps(run, ensure_ascii=False, indent=2) + "\n"
    (out / "run.json").write_text(text, encoding="utf-8")
    ref = root / "eval" / "reference-run.json"
    if args.write_reference:
        ref.write_text(text, encoding="utf-8")
        print(f"записан {ref}")
        return 0
    if not ref.exists():
        print("нет eval/reference-run.json — сверять не с чем")
        return 0
    if json.loads(ref.read_text(encoding="utf-8")) == run:
        print("прогон совпадает с eval/reference-run.json")
        return 0
    print("прогон НЕ совпадает с eval/reference-run.json — сравните eval/out/run.json")
    return 1
