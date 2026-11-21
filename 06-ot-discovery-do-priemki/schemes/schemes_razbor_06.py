# -*- coding: utf-8 -*-
"""Схемы разбора 06 «Как довести AI-агента от первого разговора до приёмки» (рубрика «FDE в поле»).

Запуск: python3 web/tools/schemes_razbor_06.py → web/public/blog/img/schemes/razbor06-*.svg
В пакете перерисовать в папку schemes/: SCHEMES_OUT=schemes python3 schemes/schemes_razbor_06.py
Факты: прогон автора pro-llm-razbory/06-ot-discovery-do-priemki/eval/reference-run.json — без LLM; ответы агента
из записанного прогона пакета 01 (claude-sonnet-5.5, 19.10.2026).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from scheme import Scheme, INK, INK2, INK3  # noqa: E402

OUT = os.environ.get('SCHEMES_OUT') or os.path.join(os.path.dirname(__file__), '..', 'public', 'blog', 'img', 'schemes')
os.makedirs(OUT, exist_ok=True)
RED = '#d9363e'
GREEN = '#0b7d4f'


def p_(name):
    return os.path.join(OUT, name)


# ------------------------------------------------ главная: путь и где он застревает
def main():
    s = Scheme(960, 560, title='Путь FDE: от вопроса руководителя до подписи владельца числа', accent='green')
    cols = [(16, 'discovery', 'неделя'), (336, 'прототип', 'спека до кода'), (656, 'приёмка', 'по eval')]
    for x, label, note in cols:
        s.group(x, 56, 288, 288, label, accent=(label == 'приёмка'), note=note)
    q = s.box(32, 92, 256, 56, 'Вопрос руководства', 'дословно + какое решение')
    m = s.box(32, 164, 256, 56, 'Карта данных', 'источники · их проблемы')
    o = s.box(32, 236, 256, 56, 'Владелец и эталон', 'кто подписывает число')
    s.pill(32, 322, 'check: готов к приёмке', accent=True)
    sp = s.box(352, 92, 256, 56, 'Спека на страницу', 'что считаем «работает»')
    cs = s.box(352, 164, 256, 56, 'Кейсы приёмки', 'scaffold из discovery', accent=True)
    vr = s.box(352, 236, 256, 56, 'Варианты прототипа', 'A сырые таблицы · B слой')
    gt = s.box(672, 92, 256, 72, 'Ворота G1–G5', 'кейсы · эталоны · слой', sub2='агент · цена и время', accent=True)
    a = s.box(672, 188, 120, 56, 'A', 'не принят', fill='rgba(255,100,103,0.08)')
    b = s.box(808, 188, 120, 56, 'B', 'ждёт прогона')
    s.box(672, 264, 256, 48, 'Подпись владельцев', muted=True, size=13)
    s.arrow(o.r, cs.l, None, accent=True, via=[(312, 264), (312, 192)])
    s.arrow(q.r, sp.l)
    s.arrow(cs.r, gt.at('l', 0.6), None, accent=True, via=[(632, 192), (632, 135)])
    s.arrow(vr.r, (672, 216), None, via=[(648, 264), (648, 216)])
    s.arrow(gt.at('b', 0.2), a.t)
    s.arrow(gt.at('b', 0.8), b.t)
    # где застревает
    s.text(16, 384, 'Где застревает — на сквозном примере пакета', 15, INK, 'start', 700)
    stuck = [
        (16, ['После первой встречи', 'discovery не готов: 24 пробела —', 'нет решений, определений,', 'владельцев и эталонов']),
        (336, ['Eval ≠ вопросы руководства', 'в пакете 01 агент B — 30 из 30,', 'но выручку каждого из 12', 'магазинов ему не задавали']),
        (656, ['Один месяц ничего не доказывает', 'в сентябре строк-ошибок нет,', 'в августе у магазина №2 их 8 —', 'агент A ошибся в 55 раз']),
    ]
    for x, lines in stuck:
        s.rule(x, 398, x + 288, 398, dashed=False)
        s.text(x, 424, lines[0], 14, RED, 'start', 600)
        for i, t in enumerate(lines[1:]):
            s.text(x, 448 + i * 20, t, 13, INK2)
    s.rule(16, 524, 944, 524)
    s.mono(16, 546, 'uv run razbor06 all · без LLM: ответы агента — записанный прогон пакета 01', 11, INK3)
    return s.save(p_('razbor06-main.svg'))


# ------------------------------------------------ один вопрос → кейсы приёмки и что ответили A и B
ROWS = [
    # (кейс, вопрос, что проверяет, эталон, A, B, A ошибся)
    ('M1-1', 'Выручка по магазинам, сентябрь', 'base', '12 строк', 'не задавали', 'не задавали', None),
    ('M1-2', 'Магазин №2, август', 'issue: строки-ошибки', '358 641', '19 908 486', '358 641', True),
    ('M1-3', 'Регион «Восток», последний месяц', 'issue: открытый месяц', '1 065 715', '392 590', '1 065 715', True),
    ('M1-4', 'Валовые продажи, сентябрь', 'alt: валовые ≠ чистые', '4 217 937', 'верно', 'верно', False),
    ('M2-1', 'Остатки на конец III квартала', 'base', '71 273', 'верно', 'верно', False),
    ('M2-2', 'Средний остаток, I полугодие', 'alt: средний ≠ на конец', '72 228', 'верно', 'верно', False),
    ('M3-1', 'Доля возвратов, III квартал', 'base + строки-ошибки', '1,17 %', '0,48 %', '1,17 %', True),
]


def cases():
    s = Scheme(960, 500, title='Три вопроса руководства → 7 кейсов приёмки', accent='green')
    cols = [(16, 'Кейс', 'start'), (80, 'Вопрос', 'start'), (370, 'Что проверяет', 'start'),
            (690, 'Эталон', 'end'), (818, 'Агент A', 'end'), (944, 'Агент B', 'end')]
    y0 = 74
    for x, t, anc in cols:
        s.text(x, y0, t, 12, INK3, anc, 600)
    s.mono(944, y0 + 16, 'слой метрик', 10.5, INK3, 'end')
    s.mono(818, y0 + 16, 'сырые таблицы', 10.5, INK3, 'end')
    y = y0 + 50
    for cid, q, cov, exp, a, b, a_bad in ROWS:
        s.rule(16, y - 22, 944, y - 22)
        s.mono(16, y, cid, 12.5, INK)
        s.text(80, y, q, 14, INK, 'start', 500)
        s.mono(370, y, cov, 11.5, INK2)
        s.mono(690, y, exp, 12.5, INK, 'end')
        wait = a == 'не задавали'
        s.mono(818, y, a, 12.5, RED if a_bad else (INK3 if wait else GREEN), 'end')
        s.mono(944, y, b, 12.5, INK3 if wait else GREEN, 'end')
        y += 38
    s.rule(16, y - 22, 944, y - 22)
    s.text(16, y + 6, 'A: не принят — 3 ошибки из 6 ответов.', 14, RED, 'start', 600)
    s.text(16, y + 30, 'B: 6 из 6 и слой сошёлся на всех 12 магазинах, но ждёт прогона — 12 вопросов «по магазинам».', 14,
           INK, 'start', 600)
    s.note(16, y + 58, ['Эталоны в рублях и штуках; допуск ±0,5 %. Ответы агентов — записанный прогон пакета 01 (19.10.2026).'],
           12, INK3)
    return s.save(p_('razbor06-cases.svg'))


# ------------------------------------------------ архитектура пакета
def architecture():
    s = Scheme(960, 470, title='Пакет 06: discovery.yaml → кейсы → ворота, база и ответы — из пакета 01', accent='green')
    d = s.box(16, 72, 176, 64, 'discovery.yaml', 'вопросы · карта', sub2='владельцы · эталоны', accent=True)
    ch = s.box(232, 72, 150, 64, 'check', 'готов / пробелы')
    sc = s.box(422, 72, 150, 64, 'scaffold', 'база + пробы', sub2='TODO на непокрытое')
    ac = s.box(612, 72, 150, 64, 'acceptance.yaml', '7 кейсов')
    s.arrow(d.r, ch.l)
    s.arrow(ch.r, sc.l, None, accent=True)
    s.arrow(sc.r, ac.l, None, accent=True)
    pr = s.box(804, 72, 140, 64, 'prototype.yaml', 'пороги «работает»', muted=True)
    g = s.box(612, 196, 332, 92, 'accept: ворота G1–G5', 'эталон: golden_sql по raw', sub2='слой: compile_query · агент: ответы', accent=True)
    s.arrow(ac.b, (ac.b[0], 196), None, accent=True)
    s.arrow(pr.b, (pr.b[0], 196))
    s.group(16, 168, 556, 150, 'пакет 01 — path-зависимость')
    db = s.box(32, 204, 160, 64, 'retail.duckdb', 'raw → stg → mart', sub2='synth.py')
    mt = s.box(208, 204, 160, 64, 'metrics.yaml', 'слой метрик')
    rr = s.box(384, 204, 172, 64, 'reference-run.json', 'ответы A и B', sub2='60 ответов, 19.10')
    s.arrow((556, 236), g.at('l', 0.45), None)
    s.mono(40, 300, 'эталон и слой считаются живыми запросами по одной базе', 10.5, INK3)
    rep = s.box(612, 330, 160, 56, 'report.md', 'summary.json')
    ex = s.box(788, 330, 156, 56, 'agent-root-B', '12 вопросов')
    s.arrow(g.at('b', 0.24), rep.t)
    s.arrow(g.at('b', 0.76), ex.t)
    ev = s.box(420, 352, 168, 56, 'razbor01 eval', '--root agent-root-B', muted=True, size=13)
    s.arrow(ex.b, ev.b, None, dashed=True, via=[(866, 426), (504, 426)])
    s.mono(690, 420, 'вопросы без ответа агента', 10.5, INK2, 'middle')
    s.arrow(ev.t, g.at('l', 0.75), None, dashed=True, via=[(504, 334), (592, 334), (592, 265)])
    s.mono(548, 328, 'results.jsonl', 10.5, INK2, 'middle')
    s.mono(16, 352, 'uv run razbor06 all', 12, INK)
    s.mono(16, 372, 'без ключа API и без LLM', 11, INK3)
    s.mono(16, 392, 'тесты: uv run pytest -q', 11, INK3)
    return s.save(p_('razbor06-architecture.svg'))


if __name__ == '__main__':
    only = set(sys.argv[1:])
    for fn in [main, cases, architecture]:
        if not only or fn.__name__ in only:
            print(fn())
