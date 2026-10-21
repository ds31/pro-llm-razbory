# -*- coding: utf-8 -*-
"""Схемы разбора 04 «Какую модель брать агенту-аналитику» (рубрика «Как читать AI»).

Запуск: python3 web/tools/schemes_razbor_04.py → web/public/blog/img/schemes/razbor04-*.svg
В пакете перерисовать в папку schemes/: SCHEMES_OUT=schemes python3 schemes/schemes_razbor_04.py
Факты: прогон автора 21.10.2026 (pro-llm-razbory/04-benchmark-na-svoih-dannyh/eval/reference-run.json):
eval пакета 01 — 30 вопросов × варианты A (сырые таблицы) и B (слой метрик), шесть моделей через OpenRouter;
Opus и Sonnet — один прогон, остальные — три (на карте — среднее). $ за ответ — списано OpenRouter (usage.cost).
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from scheme import Scheme, INK, INK2, INK3, HAIR_CARD, MONO  # noqa: E402

OUT = os.environ.get('SCHEMES_OUT') or os.path.join(os.path.dirname(__file__), '..', 'public', 'blog', 'img', 'schemes')
os.makedirs(OUT, exist_ok=True)
RED = '#d9363e'

# модель: (A верно, A $ за ответ, B верно, B $ за ответ) — eval/reference-run.json, summary
RUN = {
    'claude-opus-5.5': (26.0, 0.0831, 30.0, 0.0328),
    'claude-sonnet-5.5': (24.0, 0.0261, 30.0, 0.0161),
    'claude-haiku-5.5': (25.0, 0.00232, 30.0, 0.00096),
    'deepseek-v4.1-flash': (15.67, 0.00099, 30.0, 0.00072),
    'glm-5.3': (12.67, 0.00101, 29.0, 0.00104),
    'gpt-5.6-luna': (13.33, 0.00090, 30.0, 0.00052),
}


def p_(name):
    return os.path.join(OUT, name)


# ------------------------------------------------ главная: точность × $ за ответ
def main():
    s = Scheme(960, 600, title='Без слоя метрик решает модель, со слоем метрик — цена', accent='green')
    left, right, top, bottom = 72, 936, 120, 490
    lo, hi = -4, -1                       # 10^-4 … 10^-1 $
    ymin, ymax = 10, 30
    X = lambda c: left + (math.log10(c) - lo) / (hi - lo) * (right - left)
    Y = lambda k: bottom - (k - ymin) / (ymax - ymin) * (bottom - top)
    for d in range(lo, hi + 1):
        x = X(10 ** d)
        s.rule(x, top, x, bottom)
        s.mono(x, bottom + 22, f'${10 ** d:g}'.replace('.', ','), 11, INK2, 'middle')
    for k in range(ymin, ymax + 1, 5):
        s.rule(left, Y(k), right, Y(k))
        s.mono(left - 10, Y(k) + 4, str(k), 11, INK2, 'end')
    s.text(24, 64, 'верных ответов из 30', 12, INK2, 'start')
    # порог «прошёл» пакета 01
    s.back.append(f'<line x1="{left}" y1="{Y(27):g}" x2="{right}" y2="{Y(27):g}" stroke="{s.acc}" '
                  f'stroke-width="1.2" stroke-dasharray="6 4"/>')
    s.mono(left + 8, Y(27) - 8, 'порог «прошёл»: 27 из 30', 11, s.acc, 'start')
    s.mono((left + right) / 2, bottom + 46, '$ за ответ — списано OpenRouter, логарифмическая шкала', 11, INK2, 'middle')
    # стрелки A → B
    for name, (ka, ca, kb, cb) in RUN.items():
        s.line([(X(ca), Y(ka)), (X(cb), Y(kb) + 9)], dashed=True)
    for name, (ka, ca, kb, cb) in RUN.items():
        s.back.append(f'<circle cx="{X(ca):.1f}" cy="{Y(ka):.1f}" r="6" fill="#fff" stroke="{RED}" stroke-width="2"/>')
        s.back.append(f'<circle cx="{X(cb):.1f}" cy="{Y(kb):.1f}" r="6" fill="{s.acc}" stroke="{s.acc}" stroke-width="2"/>')
    # подписи B: над точками, плотная группа дешёвых — лесенкой с выносками
    b_labels = {'gpt-5.6-luna': (-34, -36, 'end', 'luna'), 'deepseek-v4.1-flash': (0, -22, 'middle', 'deepseek'),
                'claude-haiku-5.5': (30, -36, 'start', 'haiku'), 'glm-5.3': (14, 4, 'start', 'glm · 29'),
                'claude-sonnet-5.5': (0, -16, 'middle', 'sonnet'), 'claude-opus-5.5': (0, -16, 'middle', 'opus')}
    for name, (dx, dy, anchor, lab) in b_labels.items():
        ka, ca, kb, cb = RUN[name]
        x0, y0 = X(cb), Y(kb)
        if abs(dx) > 20 or dy < -20:
            s.back.append(f'<line x1="{x0:.1f}" y1="{y0 - 7:.1f}" x2="{x0 + dx:.1f}" y2="{y0 + dy + 4:.1f}" stroke="{INK3}" stroke-width="0.8"/>')
        s.mono(x0 + dx, y0 + dy, lab, 11.5, s.acc, anchor)
    # подписи A
    a_labels = {'claude-opus-5.5': (-14, 4, 'opus · 26'), 'claude-sonnet-5.5': (14, 4, 'sonnet · 24'),
                'claude-haiku-5.5': (14, 4, 'haiku · 25'), 'deepseek-v4.1-flash': (-14, 4, 'deepseek · 15,7'),
                'gpt-5.6-luna': (-14, 2, 'luna · 13,3'), 'glm-5.3': (14, 10, 'glm · 12,7')}
    for name, (dx, dy, lab) in a_labels.items():
        ka, ca, kb, cb = RUN[name]
        s.mono(X(ca) + dx, Y(ka) + dy, lab, 11.5, RED, 'start' if dx > 0 else 'end')
    # легенда
    ly = bottom + 76
    s.back.append(f'<circle cx="{left + 6}" cy="{ly - 4}" r="6" fill="#fff" stroke="{RED}" stroke-width="2"/>')
    s.text(left + 20, ly, 'A — агент на сырых таблицах', 12.5, INK, 'start')
    s.back.append(f'<circle cx="{left + 290}" cy="{ly - 4}" r="6" fill="{s.acc}" stroke="{s.acc}" stroke-width="2"/>')
    s.text(left + 304, ly, 'B — тот же агент через слой метрик', 12.5, INK, 'start')
    s.note(24, 590, ['Прогон автора 21.10.2026: 30 вопросов, допуск ±0,5 %; у дешёвых моделей — среднее трёх прогонов.'],
           11.5, INK3)
    return s.save(p_('razbor04-main.svg'))


# ------------------------------------------------ внутри: из чего складываются цена и время ответа
def inside():
    s = Scheme(960, 520, title='Из чего складываются цена и время ответа агента', accent='green')
    s.text(24, 70, 'Каждый шаг цикла заново отправляет модели всё, что было до него', 13.5, INK2, 'start')
    # шаги варианта B (3) и A (7): ширина полосы ~ вход шага
    rows = [('B · слой метрик', 3, ['list_metrics', 'query_metric', 'final_answer'], True),
            ('A · сырые таблицы', 7, ['list_tables', 'describe', 'describe', 'run_sql', 'run_sql', 'run_sql',
                                      'final_answer'], False)]
    y = 104
    for label, n, tools, acc in rows:
        s.text(24, y + 4, label, 14, s.acc if acc else RED, 'start', 600)
        for i in range(n):
            by = y + 18 + i * 22
            fixed = 150
            hist = 28 * i
            s.back.append(f'<rect x="200" y="{by}" width="{fixed}" height="16" rx="3" fill="#ffffff" stroke="{HAIR_CARD}"/>')
            if hist:
                s.back.append(f'<rect x="{200 + fixed}" y="{by}" width="{hist}" height="16" rx="3" '
                              f'fill="{s.acc_soft if acc else "rgba(255,100,103,0.10)"}" stroke="{s.acc if acc else RED}" stroke-width="0.8"/>')
            s.mono(190, by + 12, f'шаг {i + 1}', 10.5, INK3, 'end')
            s.mono(200 + fixed + hist + 10, by + 12, tools[i], 10.5, INK2)
        y += 18 + n * 22 + 26
    s.back.append(f'<rect x="200" y="{y - 6}" width="22" height="12" rx="2" fill="#fff" stroke="{HAIR_CARD}"/>')
    s.text(230, y + 4, 'промпт, инструменты, вопрос — на каждом шаге', 11.5, INK2, 'start')
    s.back.append(f'<rect x="200" y="{y + 14}" width="22" height="12" rx="2" fill="{s.acc_soft}" stroke="{s.acc}" stroke-width="0.8"/>')
    s.text(230, y + 24, 'история: прошлые вызовы и ответы инструментов', 11.5, INK2, 'start')
    # справа — цифры Opus 5.5 из прогона
    gx = 640
    s.group(gx, 92, 296, 384, 'claude-opus-5.5 · на ответ')
    facts = [('', 'A', 'B'), ('шагов цикла', '6,8', '3,1'), ('токенов входа', '15 432', '6 296'),
             ('токенов выхода', '1 067', '383'), ('доля входа в цене', '74 %', '77 %'),
             ('$ за ответ', '0,083', '0,033'), ('секунд на ответ', '21,8', '8,5')]
    for i, (k, a, b) in enumerate(facts):
        yy = 140 + i * 34
        s.text(gx + 16, yy, k, 12.5, INK2, 'start')
        s.mono(gx + 214, yy, a, 12, RED if i else INK3, 'end')
        s.mono(gx + 278, yy, b, 12, s.acc if i else INK3, 'end')
    s.rule(gx + 16, 362, gx + 280, 362, dashed=False)
    s.note(gx + 16, 386, ['цена = Σ по шагам: вход × цена входа', '        + выход × цена выхода',
                          'время = Σ по шагам: ответ модели', '        + работа инструмента'], 12, INK, 'start')
    s.note(24, 506, ['Полосы — схема роста входа, не масштаб. Цифры — прогон автора 21.10.2026, eval/reference-run.json пакета 04.'],
           11.5, INK3)
    return s.save(p_('razbor04-inside.svg'))


# ------------------------------------------------ публичный бенчмарк и свой eval
def bench():
    s = Scheme(960, 400, title='Что меряет публичный бенчмарк и что нужно знать вам', accent='green')
    cols = [(24, 'Публичный бенчмарк', False), (500, 'Свой eval на 30 вопросов', True)]
    rows = [('задача', 'чужая: код, браузер, учебный SQL', 'ваша: вопросы руководителя'),
            ('данные', 'открытые, часто уже в обучении', 'ваши, с правилами компании'),
            ('каркас', 'у каждой строки рейтинга свой', 'один для всех моделей'),
            ('итог', 'доля решённых задач', 'верных из 30, $ и секунды на ответ'),
            ('ответ на вопрос', '«какая модель сильнее вообще»', '«какую брать мне и за сколько»')]
    for x, head, acc in cols:
        s.group(x, 56, 436, 300, head, accent=acc)
    for i, (k, a, b) in enumerate(rows):
        y = 112 + i * 50
        for x, val, acc in ((24, a, False), (500, b, True)):
            s.mono(x + 18, y, k, 10.5, INK3)
            s.text(x + 18, y + 20, val, 14, s.acc if acc else INK, 'start', 500 if acc else 400)
    s.arrow((462, 206), (498, 206), None, accent=True)
    s.note(24, 384, ['Рейтинг годится для шорт-листа из 3–5 моделей; выбирает свой прогон.'], 12, INK2)
    return s.save(p_('razbor04-bench.svg'))


if __name__ == '__main__':
    only = set(sys.argv[1:])
    for fn in [main, inside, bench]:
        if not only or fn.__name__ in only:
            print(fn())
