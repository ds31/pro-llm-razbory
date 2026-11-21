"""Отчёты: текст проверки discovery, сводка JSON и протокол приёмки в Markdown."""
from __future__ import annotations

from .accept import GATES, Verdict
from .discovery import CheckReport
from .scaffold import Case


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def gaps_word(n: int) -> str:
    return f"{n} {plural(n, 'пробел', 'пробела', 'пробелов')}"


def num(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, dict):
        return f"{len(v)} строк, сумма {num(sum(v.values()))}"
    s = f"{v:,.2f}".replace(",", " ").replace(".", ",")
    return s[:-3] if s.endswith(",00") else s


def check_text(rep: CheckReport, title: str) -> str:
    lines = [f"{title}: {'готов к приёмке' if rep.ready else f'не готов — {gaps_word(len(rep.gaps))}'}"]
    for where, gaps in rep.by_where().items():
        lines.append(f"  {where}")
        for g in gaps:
            lines.append(f"    · {g.field}: {g.text}")
    if rep.untouched_issues:
        lines.append("  проблемы источников, которые не задевают вопросы руководства (в приёмку не входят): "
                     + ", ".join(f"{s}: {i}" for s, i in rep.untouched_issues))
    return "\n".join(lines)


def check_json(rep: CheckReport) -> dict:
    return {"questions": len(rep.questions), "ready": rep.ready, "gaps": len(rep.gaps),
            "by_where": {w: [g.field for g in gs] for w, gs in rep.by_where().items()},
            "untouched_issues": [f"{s}: {i}" for s, i in rep.untouched_issues]}


def _r(v):
    if isinstance(v, dict):
        return {str(k): round(x, 4) for k, x in v.items()}
    return None if v is None else round(v, 4)


def verdict_json(v: Verdict) -> dict:
    return {
        "verdict": v.verdict,
        "gates": {g: {"status": x.status, "detail": x.detail} for g, x in v.gates.items()},
        "answered": v.answered, "correct": v.correct, "waiting": len(v.waiting), "failed": v.failed,
        "cost_usd_mean": None if v.cost_usd_mean is None else round(v.cost_usd_mean, 4),
        "seconds_mean": None if v.seconds_mean is None else round(v.seconds_mean, 1),
        "cases": [{"id": r.id, "covers": r.covers, "question": r.question, "status": r.status,
                   "expected": _r(r.expected), "layer": _r(r.layer), "layer_ok": r.layer_ok,
                   "answer": _r(r.answer), "rows": f"{r.rows_correct}/{r.rows_answered}/{r.rows_total}"
                   if r.kind == "table" else None} for r in v.cases],
    }


def markdown(project: str, day1: CheckReport | None, filled: CheckReport, cases: list[Case],
             verdicts: dict[str, Verdict], titles: dict[str, str]) -> str:
    out = [f"# Протокол приёмки: {project}", ""]
    out += ["## Discovery", ""]
    if day1 is not None:
        out.append(f"- после первой встречи: {'готов' if day1.ready else f'не готов, {gaps_word(len(day1.gaps))}'}")
    out.append(f"- после недели discovery: {'готов к приёмке' if filled.ready else f'не готов, {gaps_word(len(filled.gaps))}'}")
    if filled.untouched_issues:
        out.append("- проблемы источников вне вопросов руководства: "
                   + ", ".join(f"`{s}: {i}`" for s, i in filled.untouched_issues))
    out += ["", f"## Кейсы приёмки ({len(cases)})", "", "| Кейс | Вопрос | Проверяет | Эталон подписал |", "|---|---|---|---|"]
    for c in cases:
        q = c.question or f"TODO: {c.hint}"
        out.append(f"| {c.id} | {q} | {', '.join(c.covers)} | {c.signed_by or '—'} |")
    for name, v in verdicts.items():
        out += ["", f"## Вариант {name} — {titles.get(name, '')}: **{v.verdict}**", "",
                "| Ворота | Что проверяют | Статус | Подробно |", "|---|---|---|---|"]
        for g, x in v.gates.items():
            out.append(f"| {g} | {GATES[g]} | {x.status} | {x.detail} |")
        out += ["", "| Кейс | Эталон | Слой | Агент | Статус |", "|---|---|---|---|---|"]
        for r in v.cases:
            agent = (f"{r.rows_correct} из {r.rows_total} строк верно, ответов {r.rows_answered}"
                     if r.kind == "table" else num(r.answer))
            out.append(f"| {r.id} | {num(r.expected)} | {num(r.layer)} | {agent} | {r.status} |")
        if v.waiting:
            out += ["", f"Ждут прогона агента: {len(v.waiting)} {plural(len(v.waiting), 'вопрос', 'вопроса', 'вопросов')}. Прогнать: "
                    f"`uv run razbor01 eval --root eval/out/agent-root-{name} --variants {name}`, затем "
                    f"`uv run razbor06 accept --variants {name} --results eval/out/agent-root-{name}/eval/out/results.jsonl`."]
    return "\n".join(out) + "\n"
