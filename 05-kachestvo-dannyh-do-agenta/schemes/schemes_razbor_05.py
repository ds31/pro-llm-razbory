# -*- coding: utf-8 -*-
"""Схемы разбора 05 «Откуда агент знает, что месяц закрыт?» (рубрика «Платформа под агентом»).

Запуск: python3 web/tools/schemes_razbor_05.py → web/public/blog/img/schemes/razbor05-*.svg
В пакете перерисовать в папку schemes/: SCHEMES_OUT=schemes python3 schemes/schemes_razbor_05.py
Факты: прогон автора (pro-llm-razbory/05-kachestvo-dannyh-do-agenta/eval/reference-run.json) — витрина дефектов
по одному и «всё сразу», seed потока 46; 200 случайных сценариев (seed 1000–1199); без LLM.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from scheme import Scheme, INK, INK2, INK3, HAIR_CARD  # noqa: E402

OUT = os.environ.get('SCHEMES_OUT') or os.path.join(os.path.dirname(__file__), '..', 'public', 'blog', 'img', 'schemes')
os.makedirs(OUT, exist_ok=True)
RED = '#d9363e'
GREEN = '#0b7d4f'


def p_(name):
    return os.path.join(OUT, name)


# ------------------------------------------------ главная: ворота перед слоем, который читает агент
def gate():
    s = Scheme(960, 470, title='Агент читает только то, что прошло ворота', accent='green')
    src = s.box(16, 92, 150, 92, 'Файлы', 'каждое утро:', sub2='продажи · остатки', muted=True)
    rules = s.box(206, 92, 170, 92, 'Правила', 'rules/*.sql', sub2='block · warn', accent=True)
    s.arrow(src.r, rules.l)
    core = s.box(424, 72, 170, 60, 'Слой core', 'прошло правила')
    quar = s.box(424, 168, 170, 60, 'Карантин', 'drop · hold')
    s.arrow(rules.at('r', 0.3), core.l, None, accent=True)
    s.arrow(rules.at('r', 0.75), quar.l)
    s.arrow(quar.t, core.b, None, dashed=True)
    s.mono(520, 154, 'отпущено', 10.5, INK2)
    close = s.box(642, 92, 150, 92, 'Закрытие месяца', 'чек-лист K1–K4', sub2='→ closed_through', accent=True)
    s.arrow(core.r, close.at('l', 0.3), None, accent=True)
    s.arrow(quar.r, close.at('l', 0.75), None)
    agent = s.box(832, 92, 112, 92, 'Агент', 'метрики 01', sub2='закрытое')
    s.arrow(close.r, agent.l, None, accent=True)
    # запрос исправленного файла
    s.arrow(quar.b, src.b, None, dashed=True, via=[(509, 262), (91, 262)])
    s.mono(300, 256, 'запрос исправленного файла (fix: resend)', 10.5, INK2, 'middle')
    # подписи правил
    lines = [('drop', 'мусор: ошибка сканера, повтор чека — отбросить'),
             ('hold', 'настоящая, но неверная строка — ждать файла, карточки или человека'),
             ('warn', 'эвристика: строка проходит, нарушение — в журнал')]
    y = 306
    for tag, text in lines:
        s.pill(16, y, tag, accent=(tag == 'hold'))
        s.text(84, y, text, 13, INK2)
        y += 30
    s.text(642, 306, 'Месяц закрыт, когда:', 13, INK, 'start', 600)
    for k, t in enumerate(['все магазины × все дни — файл принят', 'снимок остатков на конец месяца',
                           'карантин за месяц пуст', 'предыдущий месяц закрыт']):
        s.text(642, 330 + k * 20, '· ' + t, 12.5, INK2)
    s.rule(16, 420, 944, 420)
    s.note(16, 446, ['Октябрь с восемью дефектами: по календарю закрыт 01.11 с выручкой +110 % к правде; '
                     'воротами — 05.11, выручка совпала.'], 12, INK3)
    return s.save(p_('razbor05-gate.svg'))


# ------------------------------------------------ дефекты: что искажают и что их ловит
DEFECTS = [
    # (дефект, без ворот: ошибка выручки октября, правила 01, правило ворот, закрыт воротами)
    ('Ошибка сканера, qty = 9999', '+16,5 %', 'ловят', 'R01 · drop', '02.11'),
    ('Повторная загрузка дня', '+3,2 %', 'нет', 'R02 · drop', '02.11'),
    ('Сумма в копейках', '+20,3 %', 'нет', 'R04 · hold', '02.11'),
    ('Дата из будущего', '−0,3 %', 'нет', 'R03 · hold', '02.11'),
    ('Магазин не прислал файл', '−0,3 %', 'нет', 'C01 · hold', '05.11'),
    ('SKU без карточки', '−0,4 %', 'нет', 'R05 · hold', '03.11'),
    ('Карточка-дубль', '+0,15 %', 'ловят', 'R07 · warn', '02.11'),
    ('Отрицательные остатки', 'остатки', 'нет', 'R06 · hold', '04.11'),
    ('Тихий: файл обрезан', '−0,9 %', 'нет', 'не видит', '02.11'),
]


def defects():
    s = Scheme(960, 500, title='Какой дефект что искажает и какое правило его ловит', accent='green')
    cols = [(16, 'Дефект в файлах октября', 'start'), (430, 'Без ворот', 'end'),
            (560, 'Правила 01', 'middle'), (690, 'Ворота', 'start'), (944, 'Закрыт', 'end')]
    y0 = 78
    for x, t, a in cols:
        s.text(x, y0, t, 12, INK3, a, 600)
    s.mono(430, y0 + 16, 'выручка октября', 10.5, INK3, 'end')
    s.mono(944, y0 + 16, 'по календарю 01.11', 10.5, INK3, 'end')
    y = y0 + 48
    for name, err, r01, rule, day in DEFECTS:
        silent = rule == 'не видит'
        s.rule(16, y - 22, 944, y - 22)
        s.text(16, y, name, 14, RED if silent else INK, 'start', 500)
        bad = err != '+0,15 %'
        s.mono(430, y, err, 13, RED if bad else INK2, 'end')
        s.mono(560, y, r01, 12, GREEN if r01 == 'ловят' else INK3, 'middle')
        s.mono(690, y, rule, 13, RED if silent else GREEN)
        s.mono(944, y, day, 13, INK2 if day == '02.11' else INK, 'end')
        y += 38
    s.rule(16, y - 22, 944, y - 22)
    s.note(16, y + 4, ['Каждый дефект внесён отдельно в магазин №4. «Без ворот» — ошибка выручки, которую агент получил бы 01.11;',
                       'остатки ломают вопрос про остатки, а не выручку. Ворота во всех громких случаях — 0 %, тихий проходит.'],
           12, INK3)
    return s.save(p_('razbor05-defects.svg'))


# ------------------------------------------------ архитектура пакета
def package():
    s = Scheme(960, 430, title='Пакет 05: один поток, три пути к агенту, правда рядом', accent='green')
    h = s.box(16, 70, 176, 64, 'История 01', 'synth.py, seed 43', sub2='закрыта по 30.09', muted=True)
    f = s.box(228, 70, 176, 64, 'feed.py', 'файлы 01.10–14.11', sub2='магазин × день')
    d = s.box(440, 70, 176, 64, 'defects.py', '9 дефектов', sub2='правда отдельно', accent=True)
    t = s.box(652, 70, 160, 64, 'Правда', 'что было', sub2='на самом деле', muted=True)
    s.arrow(h.r, f.l)
    s.arrow(f.r, d.l, None, accent=True)
    s.arrow(d.r, t.l, None, dashed=True)
    s.group(16, 160, 600, 150, 'три пути одного потока')
    m1 = s.box(32, 196, 176, 64, 'Без ворот', 'всё в слой', sub2='закрыт 1-го числа', muted=True)
    m2 = s.box(224, 196, 176, 64, 'Правила 01', 'layers.sql', sub2='закрыт по снимку')
    m3 = s.box(416, 196, 184, 64, 'Ворота', 'rules/*.sql · карантин', sub2='закрыт по чек-листу', accent=True)
    s.arrow(d.b, (d.b[0], 160), None, accent=True)
    s.mono(518, 152, 'поток с дефектами — в каждый путь', 10.5, INK2, 'end')
    s.mono(316, 290, 'витрины mart и слой метрик — пакета 01, без изменений', 10.5, INK3, 'middle')
    q = s.box(652, 196, 160, 64, '9 вопросов', '«последний месяц»', sub2='compile_query 01')
    s.arrow((616, 228), q.l, None)
    s.arrow(t.b, q.t, None, dashed=True)
    rep = s.box(836, 196, 108, 64, 'report', '.html', sub2='.json', accent=True)
    s.arrow(q.r, rep.l, None, accent=True)
    ag = s.box(652, 334, 292, 56, 'agent_check.py: агент B 01 через API', 'closed_through: календарь / ворота', size=13)
    s.line([(m3.c[0], 260), (m3.c[0], 362)], dashed=True, head=False)
    s.arrow((m3.c[0], 362), ag.l, 'витрина 03.11', loff=(0, -8))
    s.mono(16, 352, 'uv run razbor05 all', 12, INK)
    s.mono(16, 372, '200 случайных сценариев · без LLM', 11, INK3)
    s.mono(16, 392, 'тесты: uv run pytest -q', 11, INK3)
    return s.save(p_('razbor05-package.svg'))


if __name__ == '__main__':
    only = set(sys.argv[1:])
    for fn in [gate, defects, package]:
        if not only or fn.__name__ in only:
            print(fn())
