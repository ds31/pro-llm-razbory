# -*- coding: utf-8 -*-
"""Схемы разбора 03 «Как доказать, что AI-агент считает правильно?» (рубрика «Агент в проде»).

Запуск: python3 web/tools/schemes_razbor_03.py → web/public/blog/img/schemes/razbor03-*.svg
В пакете перерисовать в папку schemes/: SCHEMES_OUT=schemes python3 schemes/schemes_razbor_03.py
Факты: прогон автора 21.10.2026 (pro-llm-razbory/03-eval-agenta-analitika/eval/reference-run.json):
60 ответов прогона автора пакета 01 (claude-sonnet-5.5), судьи claude-haiku-5.5 и claude-sonnet-5.5,
дозагрузка по 10.11.2026 (6 вопросов про «последний месяц»), повторы и ворота на варианте B.
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


# ------------------------------------------------ главная: три способа проверки
def main():
    s = Scheme(960, 470, title='Три способа проверить ответ агента — и что каждый пропускает', accent='green')
    cols = [
        ('Судья-LLM без эталона', False, 'видит вопрос, ответ, пояснение и трассу',
         [('4 из 6', 'ошибок назвал «верно»', RED), ('0–1', 'верных отверг (Sonnet — 0, Haiku — 1)', INK2)],
         ['поймал 2 ошибки — те, где агент сам', 'написал «октябрь неполный»;', 'выручку ×55 от строк-ошибок',
          'сканера — пропустили оба судьи']),
        ('Записанное число', False, 'эталон, сохранённый 10.10',
         [('5 из 6', 'верных — «неверно» после дозагрузки', RED), ('5 из 5', 'неверных — «верно» у платформы без', RED)],
         ['', '', 'SQL с датой внутри — так же:', '«последний месяц» застыл в сентябре']),
        ('Живой эталон', True, 'check_sql по данным при каждой проверке',
         [('0 из 6', 'ошибок пропущено', None), ('0', 'верных отвергнуто', None)],
         ['после дозагрузки: 6 из 6 верных', 'приняты, 5 ошибок устаревшей', 'платформы пойманы;',
          '«последний месяц» — из данных']),
    ]
    x0, w, gap = 24, 296, 16
    for i, (title, acc, sub, facts, notes) in enumerate(cols):
        x = x0 + i * (w + gap)
        s.group(x, 56, w, 330, title, accent=acc)
        s.mono(x + 16, 100, sub, 11, INK3)
        for k, (big, line, col) in enumerate(facts):
            y = 156 + k * 78
            s.text(x + 16, y, big, 34, col or s.acc, 'start', 300)
            s.mono(x + 16, y + 22, line, 11, INK2)
            if i == 1 and k == 1:
                s.mono(x + 16, y + 38, 'сдвига closed_through', 11, INK2)
        for k, line in enumerate(notes):
            if line:
                s.mono(x + 16, 316 + k * 16, line, 11, INK2)
    s.note(24, 414, ['Один прогон — тоже не доказательство: нужны повторы (pass^3) и ворота перед каждой правкой.'], 12.5, INK2)
    s.note(24, 448, ['Прогон автора: 60 ответов агента на Claude Sonnet 5.5 (6 настоящих ошибок), судьи — Claude Haiku 5.5 и Sonnet 5.5;',
                     'дозагрузка данных по 10.11.2026 — 6 вопросов про «последний месяц»; допуск ±0,5 %.'], 11, INK3)
    return s.save(p_('razbor03-main.svg'))


# ------------------------------------------------ архитектура: eval как ворота в цикле правок
def architecture():
    s = Scheme(960, 510, title='Eval как ворота перед каждой правкой агента', accent='green')
    s.group(24, 56, 196, 236, 'Любая правка')
    for k, t in enumerate(['промпт', 'модель', 'слой данных', 'дозагрузка данных']):
        s.pill(44, 100 + k * 44, t)
    q = s.box(256, 64, 200, 72, 'questions.yaml', 'вопрос · тег-ловушка', sub2='check_sql · trap_sql · допуск')
    raw = s.box(256, 168, 200, 60, 'Сырые данные', 'эталон — мимо витрин', muted=True)
    ag = s.box(256, 260, 200, 72, 'Агент под проверкой', 'answer(вопрос) → число,', sub2='пояснение, трасса')
    s.arrow((220, 296), ag.l, None)
    live = s.box(496, 140, 196, 72, 'Живой эталон', 'считается при проверке', sub2='допуск ±0,5 %', accent=True)
    s.arrow(q.r, (live.x, live.y + 22), None, accent=True)
    s.arrow(raw.r, (live.x, live.y + 52), None, accent=True)
    runs = s.box(496, 260, 196, 72, 'Прогоны ×3', 'ответы без вердиктов', sub2='run.json')
    s.arrow(ag.r, runs.l, None)
    judge = s.box(496, 364, 196, 56, 'Судья-LLM', 'только для сравнения', dashed=True, muted=True)
    s.arrow(runs.b, judge.t, None, dashed=True)
    cmp_ = s.box(732, 196, 204, 80, 'compare old new', 'регрессия: был верен', sub2='во всех повторах', accent=True)
    s.arrow(live.r, (cmp_.x, cmp_.y + 24), None, accent=True)
    s.arrow(runs.r, (cmp_.x, cmp_.y + 60), None)
    ok = s.box(732, 92, 204, 52, 'код 0 — в прод', None, size=13)
    bad = s.box(732, 328, 204, 52, 'код 1 — назад', 'explain-failure', size=13)
    s.arrow(cmp_.t, ok.b, None, accent=True)
    s.arrow(cmp_.b, bad.t, None)
    s.arrow(bad.b, (100, 292), None, dashed=True, via=[(834, 452), (100, 452)])
    s.mono(470, 446, 'чинить платформу или промпт, не эталон', 11, INK3, 'middle')
    s.note(24, 484, ['Прогон автора: убрали правило аномалий — 5 регрессий из 6, код 1; дозагрузка без сдвига closed_through — 5 из 6, код 1;',
                     'повтор без правок — 0 регрессий, код 0.'], 11, INK3)
    return s.save(p_('razbor03-architecture.svg'))


if __name__ == '__main__':
    only = set(sys.argv[1:])
    for fn in [main, architecture]:
        if not only or fn.__name__ in only:
            print(fn())
