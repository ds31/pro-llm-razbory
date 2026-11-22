# -*- coding: utf-8 -*-
"""Схемы разбора 08 «Компания на 1С без команды данных» (рубрика «Платформа под агентом»).

Запуск: python3 web/tools/schemes_razbor_08.py → web/public/blog/img/schemes/razbor08-*.svg
В пакете перерисовать в папку schemes/: SCHEMES_OUT=schemes python3 schemes/schemes_razbor_08.py
Факты: прогон автора (pro-llm-razbory/08-1s-dwh-metabase/eval/reference-run.json) — синтетическая
розничная сеть трёх объёмов, 28 ночей с 19.10.2026, seed 8, без LLM.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from scheme import Scheme, INK, INK2, INK3  # noqa: E402

OUT = os.environ.get('SCHEMES_OUT') or os.path.join(os.path.dirname(__file__), '..', 'public', 'blog', 'img', 'schemes')
os.makedirs(OUT, exist_ok=True)
RED = '#d9363e'
GREEN = '#0b7d4f'

# Цифры прогона автора, eval/reference-run.json пакета 08 (объём L, среднее за 28 ночей).
FULL_ROWS_L = '7,2 млн строк · 1,8 ГБ'
INC_ROWS_L = '≈12 тыс. строк · 2,9 МБ'


def p_(name):
    return os.path.join(OUT, name)


# ------------------------------------------------ главная: платформа целиком за одну ночь
def main_scheme():
    s = Scheme(960, 520, title='Одна ночь платформы: из 1С до отчёта и агента', accent='green')
    c1 = s.box(16, 84, 150, 100, '1С', 'копия или', sub2='рабочая база', muted=True)
    ext = s.box(204, 84, 170, 100, 'Выгрузка', 'расширение, 02:00', sub2='изменённое − 2 ч', accent=True)
    s.arrow(c1.r, ext.l)
    land = s.box(412, 84, 150, 100, 'Файлы', 'объекты 1С', sub2='+ манифест')
    s.arrow(ext.r, land.l, None, accent=True)
    chk = s.box(600, 84, 150, 100, 'Проверки', 'K1 полнота', sub2='K2 ключи · K3 ссылки', accent=True)
    s.arrow(land.r, chk.l, None, accent=True)
    raw = s.box(788, 84, 156, 100, 'Хранилище', 'raw → stg', sub2='→ витрины mart')
    s.arrow(chk.r, raw.l, None, accent=True)
    # сверка раз в неделю
    s.arrow(raw.t, c1.t, None, dashed=True, via=[(866, 62), (91, 62)])
    s.mono(478, 56, 'воскресенье: контрольные суммы магазин × месяц, расхождения — перевыгрузить', 10.5, INK2, 'middle')
    # потребители
    pg = s.box(600, 232, 150, 76, 'Postgres', 'схема mart', sub2='только чтение')
    s.arrow((800, 184), pg.t, None, via=[(800, 208), (675, 208)])
    mb = s.box(412, 232, 150, 76, 'Metabase', 'дашборды', sub2='руководителю', accent=True)
    s.arrow(pg.l, mb.r, None, accent=True)
    gate = s.box(788, 232, 156, 76, 'Ворота', 'closed_through', sub2='разбор 05')
    s.arrow((866, 184), gate.t)
    ml = s.box(788, 338, 156, 76, 'Слой метрик', 'metrics.yaml', sub2='разбор 01')
    s.arrow(gate.b, ml.t)
    ag = s.box(600, 338, 150, 76, 'Агент', 'вопрос текстом →', sub2='цифра + метрика', accent=True)
    s.arrow(ml.l, ag.r, None, accent=True)
    # подписи о нагрузке
    s.text(16, 248, 'Сколько читает из 1С одна ночь', 13, INK, 'start', 600)
    s.text(16, 272, 'полная перезагрузка', 12.5, INK2)
    s.mono(16, 292, FULL_ROWS_L, 12, RED)
    s.text(16, 318, 'инкремент по дате изменения', 12.5, INK2)
    s.mono(16, 338, INC_ROWS_L, 12, GREEN)
    s.text(16, 364, 'синтетика: 60 магазинов, 3 года истории', 11.5, INK3)
    s.rule(16, 440, 944, 440)
    s.note(16, 466, ['Витрины пересобираются целиком каждую ночь — это дёшево. Дорого читать 1С: её трогает только выгрузка,',
                     'один раз за ночь и только изменённым. Отчёты и агент читают одни и те же витрины.'], 12, INK3)
    return s.save(p_('razbor08-main.svg'))


# ------------------------------------------------ архитектура пакета
def architecture():
    s = Scheme(960, 500, title='Пакет 08: одна «1С», четыре способа загрузки, эталон рядом', accent='green')
    src = s.box(16, 76, 190, 84, 'Синтетическая «1С»', 'справочники, документы', sub2='движения регистра', muted=True)
    day = s.box(16, 196, 190, 84, 'Бизнес-день', 'правки, отмена проведения', sub2='удаления, поздние записи')
    s.arrow(day.t, src.b, None, accent=True)
    exp = s.box(250, 76, 180, 84, 'Выгрузка 02:00', 'файлы обмена', sub2='+ манифест', accent=True)
    s.arrow(src.r, exp.l, None, accent=True)
    s.mono(340, 182, 'счётчики: запросы,', 10.5, INK2, 'middle')
    s.mono(340, 198, 'строки, байты', 10.5, INK2, 'middle')
    s.group(470, 56, 270, 252, 'четыре способа — четыре хранилища')
    names = [('full', 'всё каждую ночь'), ('doc_date', 'дата документа, 3 дня'),
             ('watermark', 'после прошлого запуска'), ('safe', 'перекрытие 2 ч + сверка')]
    for i, (n, sub) in enumerate(names):
        y = 84 + i * 54
        b = s.box(486, y, 238, 48, n, sub, accent=(n == 'safe'), size=13)
        s.arrow(exp.r, b.l, None, accent=(n == 'safe'), via=[(450, 118), (450, y + 24)])
    dwh = s.box(780, 76, 164, 84, 'Загрузчик', 'K1 · K2 · K3', sub2='raw → stg → mart', accent=True)
    s.arrow((740, 118), dwh.l, None, accent=True)
    tr = s.box(780, 196, 164, 84, 'Эталон', 'прямо по «1С»,', sub2='минуя загрузчик')
    s.arrow(dwh.b, tr.t, 'сверка', loff=(26, 4))
    rep = s.box(780, 372, 164, 64, 'Отчёт', 'reference-run.json', size=13, accent=True)
    s.arrow(tr.b, rep.t, None, accent=True)
    # витрины читают Metabase и слой метрик пакета 01
    s.line([(760, 160), (760, 340), (340, 340)], dashed=True, head=False)
    s.mono(748, 334, 'витрины mart', 10.5, INK2, 'end')
    pg = s.box(250, 372, 180, 64, 'Postgres + Metabase', 'deploy/, docker compose', size=13)
    ml = s.box(486, 372, 238, 64, 'Слой метрик пакета 01', 'metrics.yaml, агент', size=13)
    s.arrow((340, 340), pg.t, None, dashed=True)
    s.arrow((605, 340), ml.t, None, dashed=True)
    s.mono(16, 474, 'uv run razbor08 all · без LLM и без Docker · тесты: uv run pytest -q', 11.5, INK)
    return s.save(p_('razbor08-architecture.svg'))


# ------------------------------------------------ четыре способа на прогоне автора (объём L)
# (способ, читает за ночь, ночей с расхождением из 28, магазино-месяцев с ошибкой в последнюю ночь, что не видит)
STRATEGY_ROWS = [
    ('Полная перезагрузка', '7,2 млн', '0', '0', 'видит всё — ценой всей истории каждую ночь'),
    ('По дате документа, 3 дня', '20,3 тыс.', '28', '117', 'правки, отмены и удаления старше окна'),
    ('После прошлого запуска', '9,8 тыс.', '27', '90', 'поздние записи и прямые удаления'),
    ('Перекрытие 2 ч + сверка в вс', '11,7 тыс.', '19', '0', 'прямые удаления — только до воскресенья'),
]


def strategies():
    s = Scheme(960, 430, title='Четыре способа ночной загрузки: сколько читают из 1С и где расходятся', accent='green')
    cols = [(16, 'Способ', 'start'), (430, 'Строк за ночь', 'end'), (560, 'Ночей', 'end'),
            (690, 'Маг.-мес.', 'end'), (712, 'Что не видит', 'start')]
    y0 = 80
    for x, t, a in cols:
        s.text(x, y0, t, 12, INK3, a, 600)
    s.mono(560, y0 + 16, 'с расхожд.', 10.5, INK3, 'end')
    s.mono(690, y0 + 16, 'с ошибкой', 10.5, INK3, 'end')
    y = y0 + 52
    for name, r, nerr, sm, miss in STRATEGY_ROWS:
        good = name.startswith('Перекрытие')
        bad = sm not in ('0',)
        s.rule(16, y - 24, 944, y - 24)
        s.text(16, y, name, 14, GREEN if good else INK, 'start', 600 if good else 500)
        s.mono(430, y, r, 13, RED if name.startswith('Полная') else INK2, 'end')
        s.mono(560, y, nerr + ' из 28', 13, INK2, 'end')
        s.mono(690, y, sm, 13, RED if bad else GREEN, 'end')
        words, line, lines = miss.split(), '', []
        for w in words:
            if len(line) + len(w) > 28:
                lines.append(line)
                line = w
            else:
                line = (line + ' ' + w).strip()
        lines.append(line)
        for i, ln in enumerate(lines):
            s.text(712, y + i * 16, ln, 12, INK2)
        y += 56
    s.rule(16, y - 24, 944, y - 24)
    s.note(16, y + 2, ['Объём L: 60 магазинов, 3 года истории, 28 ночей. «Маг.-мес. с ошибкой» — магазино-месяцы, где выручка в витрине',
                       'дальше ±0,5 % от 1С в последнюю ночь, воскресенье после сверки. Прогон автора, eval/reference-run.json пакета 08.'],
           11.5, INK3)
    return s.save(p_('razbor08-strategies.svg'))


if __name__ == '__main__':
    only = set(sys.argv[1:])
    for fn in [main_scheme, architecture, strategies]:
        if not only or fn.__name__ in only:
            print(fn())
