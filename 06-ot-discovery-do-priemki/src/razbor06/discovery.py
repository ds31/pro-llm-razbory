"""Discovery-файл: вопросы руководства, карта данных, владельцы и эталоны. Проверка «готов к приёмке»."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Что должно быть у каждого вопроса руководства, чтобы по нему можно было принять агента.
REQUIRED = {
    "question": "вопрос дословно, как его задаёт руководитель",
    "asked_by": "кто задаёт вопрос",
    "decision": "какое решение принимают по этому числу",
    "metric": "метрика из каталога слоя метрик",
    "definition": "определение словами владельца: что входит в число, что нет",
    "period": "период: from и to",
    "sources": "таблицы-источники из карты данных",
    "owner": "владелец числа — кто подписывает эталон",
    "golden": "эталон: как получено число, SQL, кто и когда подписал",
}
GOLDEN_REQUIRED = {
    "sql": "запрос, который даёт подписанное число",
    "signed_by": "кто подписал эталон",
    "signed_on": "когда подписан эталон",
}
CHECK_REQUIRED = {
    "question": "вопрос-проба",
    "metric_query": "запрос к слою метрик: metric, date_from, date_to, filters",
    "golden_sql": "эталонный запрос",
    "covers": "что проверяет кейс: issue:<id> или alt:<метрика>",
}
SOURCE_REQUIRED = {
    "what": "что лежит в источнике",
    "owner": "владелец источника",
    "refresh": "как часто обновляется",
}


@dataclass(frozen=True)
class Gap:
    where: str   # M1, data_map:raw.sales, questions
    field: str
    text: str


@dataclass
class CheckReport:
    gaps: list[Gap] = field(default_factory=list)
    untouched_issues: list[tuple[str, str]] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.gaps

    def by_where(self) -> dict[str, list[Gap]]:
        out: dict[str, list[Gap]] = {}
        for g in self.gaps:
            out.setdefault(g.where, []).append(g)
        return out


def load_discovery(path: Path | str) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"discovery: ожидается словарь с ключами stakeholders, data_map, questions — {path}")
    return data


def metric_parts(metric: str) -> list[str]:
    """«returns_amount / gross_sales» → две метрики каталога; обычная метрика — одна."""
    return [p.strip() for p in str(metric).split("/") if p.strip()]


def _empty(v) -> bool:
    return v is None or v == "" or v == [] or v == {}


def applicable_issues(q: dict, sources: dict[str, dict]) -> list[tuple[str, dict]]:
    """Проблемы источников вопроса, которые его задевают (only_if — только при таком свойстве вопроса)."""
    out = []
    for src in q.get("sources") or []:
        for issue in (sources.get(src) or {}).get("issues") or []:
            cond = issue.get("only_if")
            if cond and not q.get(cond):
                continue
            out.append((src, issue))
    return out


def required_covers(q: dict, sources: dict[str, dict]) -> dict[str, str]:
    """Что обязан проверить набор кейсов вопроса: проблемы его источников и отвергнутые определения."""
    need: dict[str, str] = {}
    for src, issue in applicable_issues(q, sources):
        need[f"issue:{issue['id']}"] = f"{src}: {issue.get('what', '')}".strip()
    for alt in q.get("alternatives") or []:
        need[f"alt:{alt}"] = f"агент не должен подменить «{q.get('metric')}» на «{alt}»"
    return need


def provided_covers(q: dict) -> set[str]:
    got = set((q.get("golden") or {}).get("covers") or [])
    for c in q.get("checks") or []:
        got |= set(c.get("covers") or [])
    return got


def check(d: dict, catalog: set[str] | None = None) -> CheckReport:
    """Проверить discovery. catalog — id метрик слоя; None — не сверять метрики с каталогом."""
    rep = CheckReport()
    roles = {s.get("role") for s in d.get("stakeholders") or []}
    sources = {s.get("source"): s for s in d.get("data_map") or []}
    questions = d.get("questions") or []
    if not questions:
        rep.gaps.append(Gap("questions", "questions", "нет ни одного вопроса руководства"))
    ids = [q.get("id") for q in questions]
    for dup in sorted({i for i in ids if ids.count(i) > 1}, key=str):
        rep.gaps.append(Gap("questions", "id", f"id {dup} повторяется"))

    for src, s in sources.items():
        where = f"data_map:{src}"
        for key, hint in SOURCE_REQUIRED.items():
            if _empty(s.get(key)):
                rep.gaps.append(Gap(where, key, f"нет поля {key}: {hint}"))
        if s.get("owner") and s["owner"] not in roles:
            rep.gaps.append(Gap(where, "owner", f"владелец «{s['owner']}» не в списке участников"))

    touched: set[tuple[str, str]] = set()
    for q in questions:
        qid = str(q.get("id"))
        rep.questions.append(qid)
        gap = lambda f, t: rep.gaps.append(Gap(qid, f, t))  # noqa: E731
        for key, hint in REQUIRED.items():
            if _empty(q.get(key)):
                gap(key, f"нет поля {key}: {hint}")
        if q.get("asked_by") and q["asked_by"] not in roles:
            gap("asked_by", f"«{q['asked_by']}» не в списке участников")
        if q.get("owner") and q["owner"] not in roles:
            gap("owner", f"владелец «{q['owner']}» не в списке участников")
        if q.get("metric") and catalog is not None:
            unknown = [m for m in metric_parts(q["metric"]) if m not in catalog]
            if unknown:
                gap("metric", f"метрики {', '.join(unknown)} нет в каталоге слоя метрик")
        for alt in q.get("alternatives") or []:
            if catalog is not None and alt not in catalog:
                gap("alternatives", f"альтернативы {alt} нет в каталоге слоя метрик")
        period = q.get("period")
        if period is not None and (not isinstance(period, dict) or _empty(period.get("from")) or _empty(period.get("to"))):
            gap("period", "период задаётся как {from: ГГГГ-ММ-ДД, to: ГГГГ-ММ-ДД}")
        for src in q.get("sources") or []:
            if src not in sources:
                gap("sources", f"источника {src} нет в карте данных")
        if q.get("dimensions") and _empty(q.get("row_question")):
            gap("row_question", "разрез по измерению: нужна формулировка вопроса по одной строке, "
                                "например «Какая выручка магазина №{key} за сентябрь?»")
        golden = q.get("golden")
        if isinstance(golden, dict):
            for key, hint in GOLDEN_REQUIRED.items():
                if _empty(golden.get(key)):
                    gap(f"golden.{key}", f"нет golden.{key}: {hint}")
            if golden.get("signed_by") and q.get("owner") and golden["signed_by"] != q["owner"]:
                gap("golden.signed_by", f"эталон подписал «{golden['signed_by']}», а владелец числа — «{q['owner']}»")
        for i, c in enumerate(q.get("checks") or [], 1):
            for key, hint in CHECK_REQUIRED.items():
                if _empty(c.get(key)):
                    gap(f"checks[{i}].{key}", f"кейс {i}: нет {key} — {hint}")
        need = required_covers(q, sources)
        touched |= {(src, issue["id"]) for src, issue in applicable_issues(q, sources)}
        for cover in sorted(set(need) - provided_covers(q)):
            gap("coverage", f"нет кейса на {cover} — {need[cover]}")

    all_issues = [(src, i["id"]) for src, s in sources.items() for i in s.get("issues") or []]
    rep.untouched_issues = [x for x in all_issues if x not in touched]
    return rep
