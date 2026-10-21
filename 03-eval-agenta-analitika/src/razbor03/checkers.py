"""Три способа проверить ответ агента.

live   — живой эталон: check_sql по текущим данным, допуск tolerance_pct. Основной.
frozen — замороженный эталон: числа, записанные когда-то (`freeze`). Устаревает при дозагрузке.
judge  — судья-LLM без эталона: видит вопрос, ответ, пояснение и трассу. Сравнительный режим.

Проверяющий сам проверяется: его вердикты сравниваются с живым эталоном (`agreement`).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import duckdb

from .agent import price
from .reference import expected, is_correct
from .runs import Answer, Run
from .spec import Suite


@dataclass
class Verdict:
    correct: bool
    expected: float | None = None
    note: str = ""
    cost_usd: float = 0.0
    via: str = ""           # судья: tool — инструментом verdict, json — переспрошен со structured output


def check_live(run: Run, suite: Suite, con: duckdb.DuckDBPyConnection) -> dict[str, Verdict]:
    out = {}
    for a in run.answers:
        q = suite.get(a.qid)
        exp = expected(con, q)
        out[a.qid] = Verdict(is_correct(a.value, exp, q.tolerance_pct), exp)
    return out


def freeze(suite: Suite, con: duckdb.DuckDBPyConnection) -> dict[str, float]:
    """Записать эталонные числа на сегодняшние данные — так делают, когда эталон хранят числом."""
    return {q.id: expected(con, q) for q in suite.questions}


def check_frozen(run: Run, suite: Suite, frozen: dict[str, float]) -> dict[str, Verdict]:
    out = {}
    for a in run.answers:
        q = suite.get(a.qid)
        out[a.qid] = Verdict(is_correct(a.value, frozen[a.qid], q.tolerance_pct), frozen[a.qid])
    return out


# ---------- судья-LLM

JUDGE_SYSTEM = (
    "Ты проверяешь ответы AI-агента-аналитика розничной сети. Агент получил вопрос руководителя, "
    "сделал запросы к базе и сдал число. Эталонного ответа у тебя нет. По вопросу, ответу, пояснению "
    "и трассе запросов реши, верен ли ответ: правильно ли понят вопрос (период, разрез, определение "
    "метрики), правильно ли посчитано, согласуется ли число с данными в трассе. Если сомневаешься — "
    "назови сомнение и всё равно выбери. Сдай вердикт инструментом verdict."
)
VERDICT_TOOL = {
    "name": "verdict",
    "description": "Сдать вердикт по ответу агента. Вызывается ровно один раз.",
    "strict": True,
    "input_schema": {"type": "object", "additionalProperties": False, "properties": {
        "correct": {"type": "boolean", "description": "true — ответ верный, false — неверный."},
        "reason": {"type": "string", "description": "Почему, одним-двумя предложениями."}},
        "required": ["correct", "reason"]},
}


def judge_prompt(question: str, a: Answer) -> str:
    lines = [f"Вопрос: {question}",
             f"Ответ агента: {a.value} {a.unit}".rstrip(),
             f"Пояснение агента: {a.explanation or '—'}",
             f"Трасса ({len(a.trace)} шагов):"]
    for i, c in enumerate(a.trace, 1):
        lines.append(f"{i}. {c['name']} {json.dumps(c['input'], ensure_ascii=False)}")
        if c.get("output"):
            lines.append(f"→ {c['output']}")
    return "\n".join(lines)


VERDICT_SCHEMA = {k: v for k, v in VERDICT_TOOL["input_schema"].items()}
JSON_INSTRUCTION = "Ответь только JSON с полями correct (true или false) и reason."


def _tool_verdict(resp) -> tuple[bool, str] | None:
    for b in resp.content:
        if b.type == "tool_use" and b.name == "verdict" and isinstance(b.input.get("correct"), bool) \
                and str(b.input.get("reason", "")).strip():   # вердикт без причины не принимается
            return b.input["correct"], str(b.input["reason"])
    return None


def judge_one(client, model: str, question: str, a: Answer) -> Verdict:
    """Вердикт судьи. Сначала — инструмент verdict (принудительный выбор инструмента Sonnet 5.5 и Opus 5.5
    не принимают, поэтому tool_choice auto). Если модель не вызвала инструмент (бывает: пишет вызов текстом),
    судью переспрашивают один раз со structured output — JSON по той же схеме."""
    prompt = judge_prompt(question, a)
    resp = client.messages.create(model=model, max_tokens=1024, system=JUDGE_SYSTEM, tools=[VERDICT_TOOL],
                                  tool_choice={"type": "auto"},
                                  messages=[{"role": "user", "content": prompt}])
    cost = price(model, resp.usage.input_tokens, resp.usage.output_tokens)
    got = _tool_verdict(resp)
    if got:
        return Verdict(got[0], None, got[1], round(cost, 6), "tool")
    return judge_json(client, model, prompt, cost)


def judge_json(client, model: str, prompt: str, spent: float = 0.0) -> Verdict:
    resp = client.messages.create(model=model, max_tokens=4096,
                                  system=JUDGE_SYSTEM.replace("Сдай вердикт инструментом verdict.", JSON_INSTRUCTION),
                                  messages=[{"role": "user", "content": prompt}],
                                  output_config={"format": {"type": "json_schema", "schema": VERDICT_SCHEMA}})
    cost = spent + price(model, resp.usage.input_tokens, resp.usage.output_tokens)
    text = "".join(b.text for b in resp.content if b.type == "text")
    try:
        d = json.loads(text)
        return Verdict(bool(d["correct"]), None, str(d.get("reason", "")), round(cost, 6), "json")
    except (ValueError, KeyError, TypeError):
        return Verdict(False, None, f"судья не сдал вердикт: {text[:300]}", round(cost, 6), "none")


def check_judge(run: Run, suite: Suite, client, model: str, on_verdict=None) -> dict[str, Verdict]:
    out = {}
    for a in run.answers:
        try:
            v = judge_one(client, model, suite.get(a.qid).question, a)
        except Exception as e:  # сбой API на одном ответе виден в note, прогон судьи идёт дальше
            v = Verdict(False, None, f"error: {type(e).__name__}: {e}")
        out[a.qid] = v
        if on_verdict:
            on_verdict(a.qid, v)
    return out


# ---------- проверка проверяющего

def agreement(truth: dict[str, Verdict], other: dict[str, Verdict]) -> dict:
    """Сравнить проверяющего с живым эталоном: пропущенные ошибки и отвергнутые верные ответы."""
    qids = [q for q in truth if q in other]
    return {
        "answers": len(qids),
        "errors": sum(not truth[q].correct for q in qids),
        "missed": [q for q in qids if not truth[q].correct and other[q].correct],      # ложное «верно»
        "rejected": [q for q in qids if truth[q].correct and not other[q].correct],    # ложное «неверно»
    }


def verdicts_to_dict(vs: dict[str, Verdict]) -> dict:
    return {q: asdict(v) for q, v in vs.items()}


def verdicts_from_dict(d: dict) -> dict[str, Verdict]:
    return {q: Verdict(**v) for q, v in d.items()}
