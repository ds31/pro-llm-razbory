# -*- coding: utf-8 -*-
"""Схемы разбора 01 «Почему AI-агент врёт в цифрах» (рубрика «Платформа под агентом»).

Запуск: python3 web/tools/schemes_razbor_01.py → web/public/blog/img/schemes/razbor01-*.svg
В пакете перерисовать в папку schemes/: SCHEMES_OUT=schemes python3 schemes/schemes_razbor_01.py
Факты: прогон автора 19.10.2026 (pro-llm-razbory/01-agent-vret-v-cifrah/eval/reference-run.json),
claude-sonnet-5.5, 30 вопросов × варианты A и B. Причины ошибок A проверены на базе пакета: с одним
фильтром |qty| < 1000 запросы агента в Q10 и Q29 дают ровно эталон.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from scheme import Scheme, INK2, INK3  # noqa: E402

OUT = os.environ.get('SCHEMES_OUT') or os.path.join(os.path.dirname(__file__), '..', 'public', 'blog', 'img', 'schemes')
os.makedirs(OUT, exist_ok=True)
RED = '#d9363e'


def p_(name):
    return os.path.join(OUT, name)


# ------------------------------------------------ главная: где живут правила
def layers():
    s = Scheme(960, 330, title='Правила компании живут в платформе, а не в голове агента', accent='green')
    w, h, y, gap, x0 = 112, 64, 104, 24, 16
    labels = [('Источники', '1С · кассы'), ('raw', 'как выгрузили'), ('stg', 'очистка'),
              ('mart', 'витрины'), ('Слой метрик', 'metrics.yaml'), ('Агент', 'Claude'),
              ('Ответ', 'с формулой')]
    nodes = [s.box(x0 + i * (w + gap), y, w, h, lab, sub, accent=(lab == 'Слой метрик'), muted=(i == 0))
             for i, (lab, sub) in enumerate(labels)]
    for a, b in zip(nodes, nodes[1:]):
        s.arrow(a.r, b.l, None, accent=(b is nodes[5]))
    rules = [(2, ['без ошибок сканера', '|qty| < 1000']), (3, ['только закрытые', 'месяцы']),
             (4, ['формула · разрезы', 'правило времени']), (5, ['не видит raw', 'SQL через шлюз'])]
    for i, lines in rules:
        cx = x0 + i * (w + gap) + w / 2
        for k, line in enumerate(lines):
            s.mono(cx, y + h + 28 + k * 15, line, 11, INK3, 'middle')
    a_y = 250
    s.text(16, a_y, 'A', 15, RED, 'start', 700)
    s.mono(36, a_y, 'агент ходит прямо в raw — 24 из 30 верно', 12, INK2)
    s.text(16, a_y + 26, 'B', 15, s.acc, 'start', 700)
    s.mono(36, a_y + 26, 'агент ходит через слой метрик — 30 из 30 верно, вдвое быстрее и дешевле', 12, INK2)
    s.note(16, 314, ['Прогон автора: claude-sonnet-5.5, 30 вопросов о синтетической сети, допуск ±0,5 %.'], 11.5, INK3)
    return s.save(p_('razbor01-layers.svg'))


# ------------------------------------------------ архитектура пакета
def package():
    s = Scheme(960, 400, title='Пакет 01: одна база, два агента, 30 вопросов с эталоном', accent='green')
    gen = s.box(24, 80, 150, 60, 'synth.py', 'seed 43, 24 мес.')
    raw = s.box(212, 80, 150, 60, 'DuckDB raw', 'с ловушками')
    s.arrow(gen.r, raw.l)
    lay = s.box(400, 80, 150, 60, 'layers.sql', 'stg → mart')
    s.arrow(raw.r, lay.l)
    met = s.box(588, 80, 150, 60, 'metrics.yaml', 'метрики и правила', accent=True)
    s.arrow(lay.r, met.l, None, accent=True)
    s.group(24, 168, 520, 200, 'агент на Claude API · claude-sonnet-5.5')
    a = s.box(48, 204, 220, 64, 'Вариант A', 'list_tables · describe_table', sub2='run_sql → raw.*', muted=True)
    b = s.box(300, 204, 220, 64, 'Вариант B', 'list_metrics · query_metric', sub2='run_sql → mart.*', accent=True)
    gate = s.box(48, 292, 472, 52, 'Шлюз SQL: один SELECT, своя схема; база только на чтение', None, size=12)
    s.arrow(a.b, (a.b[0], gate.y), None)
    s.arrow(b.b, (b.b[0], gate.y), None, accent=True)
    s.arrow(raw.b, a.t, None, dashed=True)
    s.arrow(met.b, b.t, None, accent=True, via=[(663, 186), (410, 186)])
    ev = s.box(588, 204, 168, 64, 'eval/questions.yaml', '30 вопросов, 5 групп', sub2='эталон = check_sql')
    run = s.box(588, 292, 168, 52, 'runner', 'допуск ±0,5 %')
    s.arrow(ev.b, run.t)
    rep = s.box(784, 292, 152, 52, 'report.html', 'A против B', accent=True)
    s.arrow(run.r, rep.l, None, accent=True)
    s.arrow(gate.r, run.l, 'ответы', loff=(0, -8))
    s.mono(784, 228, 'uv run razbor01 all', 11, INK2)
    return s.save(p_('razbor01-package.svg'))


# ------------------------------------------------ где агент A ошибся на самом деле
def lies():
    s = Scheme(960, 420, title='Где агент без платформы ошибся: не в SQL, а в правилах компании', accent='green')
    s.group(24, 56, 300, 330, 'Справился сам', accent=True)
    ok = [('Дубли в справочнике', 'оставил одну карточку на товар'),
          ('Определения', 'валовые = продажи без возвратов;'),
          ('', 'доля — из числителя и знаменателя'),
          ('Контрольные вопросы', '6 из 6 без ловушки')]
    y = 104
    for title, sub in ok:
        if title:
            s.text(44, y, '✓ ' + title, 14, s.acc, 'start', 600)
            y += 20
        else:
            y -= 14
        s.mono(64, y, sub, 11, INK2)
        y += 30
    s.note(44, 360, ['Модель сильная: SQL написан верно.'], 11.5, INK3)

    s.group(344, 56, 592, 330, 'Ошибся: правило знает только компания — 6 из 30')
    cards = [
        ('Ошибки сканера в выручке', 'строки qty = 9999 попали в сумму', '4 ответа', 2,
         [('×55', 'выручка магазина', 'за месяц'), ('×7,6', 'выручка сети', 'за квартал'),
          ('24,9 %', 'доля категории', 'верно 31,3 %'), ('0,48 %', 'доля возвратов', 'верно 1,17 %')]),
        ('Незакрытый месяц', '«последний» = 10 дней октября', '2 ответа', 1,
         [('−63 %', 'выручка региона', 'за месяц'), ('−66 %', 'продажи категории', 'в штуках')]),
    ]
    x = 364
    for title, why, cnt, cols, facts in cards:
        s.text(x, 104, title, 14, RED, 'start', 600)
        s.mono(x, 124, why, 11, INK2)
        s.mono(x, 142, cnt, 11, INK3)
        for k, (big, l1, l2) in enumerate(facts):
            fx, fy = x + (k % cols) * 144, 190 + (k // cols) * 76
            s.text(fx, fy, big, 28, RED, 'start', 300)
            s.mono(fx, fy + 20, l1, 11, INK2)
            s.mono(fx, fy + 35, l2, 11, INK3)
        x += 312
    s.note(364, 360, ['Сам заметил, что октябрь неполный, — и всё равно ответил октябрём.'], 11.5, INK3)
    s.note(24, 408, ['Прогон автора, вариант A (сырые таблицы). Вариант B через слой метрик — 30 из 30.'], 11.5, INK3)
    return s.save(p_('razbor01-lies.svg'))


if __name__ == '__main__':
    only = set(sys.argv[1:])
    for fn in [layers, package, lies]:
        if not only or fn.__name__ in only:
            print(fn())
