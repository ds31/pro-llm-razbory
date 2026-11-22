# -*- coding: utf-8 -*-
"""Схемы разбора 07 «Почему AI-агент в проде теряет задачи и пишет клиенту дважды?» (рубрика «Агент в проде»).

Запуск: python3 web/tools/schemes_razbor_07.py → web/public/blog/img/schemes/razbor07-*.svg
В пакете перерисовать в папку schemes/: SCHEMES_OUT=schemes python3 schemes/schemes_razbor_07.py
Факты: прогон автора (pro-llm-razbory/07-agent-24-7/eval/reference-run.json) — ночь по умолчанию, seed 48,
1 000 задач; сбои по одному на той же ночи; без LLM, виртуальные часы.
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


def result(s, x, y, w, lines, ok):
    """Итог конфигурации справа: крупные цифры."""
    col = GREEN if ok else RED
    s.back.append(f'<rect x="{x}" y="{y}" width="{w}" height="{24 + 34 * len(lines)}" rx="8" fill="#ffffff" '
                  f'stroke="{col}" stroke-width="1.5"/>')
    for i, (big, small) in enumerate(lines):
        s.text(x + 14, y + 36 + 34 * i, big, 20, col, 'start', 700)
        s.text(x + 22 + 13 * len(big), y + 36 + 34 * i, small, 12.5, INK2)


# ------------------------------------------------ главная: агент в обработчике API против очереди с ключами
def main():
    s = Scheme(960, 560, title='Наивная схема и прод: один агент, 1 000 вопросов за ночь', accent='green')
    # наивная
    s.group(16, 56, 928, 196, 'Наивная: агент внутри обработчика API', note='SDK по умолчанию')
    bot = s.box(32, 92, 128, 64, 'Бот магазина', 'ждёт 60 с', muted=True)
    api = s.box(196, 92, 252, 64, 'API = агент', 'план → ответ → письмо → итог', sub2='3 вызова модели')
    llm = s.box(484, 92, 150, 64, 'Модель', 'лимит 50 в минуту', muted=True)
    s.arrow(bot.r, api.l)
    s.arrow(api.r, llm.l, both=True)
    result(s, 670, 82, 258, [('180', 'задач потеряно'), ('22', 'ответа пришли дважды')], ok=False)
    fails = [('429 в пике', 'два повтора SDK кончились — 500, задача потеряна'),
             ('бот не дождался', 'переспросил — агент выполнил вопрос дважды, два письма'),
             ('kill -9', 'все запросы в работе пропали, в журнале обрыв')]
    y = 186
    for tag, text in fails:
        w = s.pill(32, y, tag)
        s.text(32 + w + 10, y, text, 12.5, INK2)
        y += 22
    # прод
    s.group(16, 272, 928, 230, 'Прод: очередь, аренда, ретраи, ключи, трасса', accent=True)
    bot2 = s.box(32, 312, 128, 64, 'Бот магазина', 'ключ задачи', muted=True)
    api2 = s.box(196, 312, 120, 64, 'API', '202 сразу', sub2='дубль по ключу')
    q = s.box(352, 312, 132, 64, 'Очередь', 'аренда 60 с', sub2='продление 15 с', accent=True)
    wk = s.box(520, 312, 120, 64, '4 воркера', 'таймаут 30 с', sub2='backoff')
    s.arrow(bot2.r, api2.l)
    s.arrow(api2.r, q.l, None, accent=True)
    s.arrow(q.r, wk.l, None, accent=True)
    dlq = s.box(352, 412, 132, 56, 'Dead-letter', '6 битых задач', sub2='с причиной', muted=True)
    s.arrow(wk.b, dlq.r, None, dashed=True, via=[(580, 440)])
    s.mono(494, 458, '400 или 6 попыток', 10.5, INK2)
    result(s, 670, 302, 258, [('0', 'потеряно'), ('0', 'дублей: письмо с ключом')], ok=True)
    for i, line in enumerate(['трасса до конца: 1 000 из 1 000', 'kill -9: задачу берёт другой воркер',
                              'письмо ушло, упал итог: повтор', 'второе письмо не уходит: ключ']):
        s.mono(674, 416 + 18 * i, line, 11, INK2)
    s.rule(16, 520, 944, 520)
    s.note(16, 544, ['Цена очереди — ожидание в пике: p95 до ответа 8,9 мин против 36,6 с у наивной (у неё — только по дошедшим ответам).'],
           12, INK3)
    return s.save(p_('razbor07-main.svg'))


# ------------------------------------------------ архитектура шаблона деплоя
def architecture():
    s = Scheme(960, 540, title='Шаблон деплоя агента 24/7 в docker compose', accent='green')
    bot = s.box(16, 104, 132, 70, 'Бот магазина', 'POST /tasks', sub2='Idempotency-Key', muted=True)
    s.group(172, 60, 500, 208, 'docker compose', accent=True, note='restart: unless-stopped · init')
    api = s.box(192, 104, 140, 70, 'api', '202 за миллисекунды', sub2='/healthz · /stats')
    vol = s.box(356, 104, 140, 70, 'том queue', 'SQLite WAL', sub2='tasks · mail', accent=True)
    w1 = s.box(520, 92, 136, 44, 'worker 1', 'аренда + heartbeat', size=13)
    w2 = s.box(520, 144, 136, 44, 'worker 2', 'SIGTERM: доделать', size=13)
    s.arrow(bot.r, api.l)
    s.arrow(api.r, vol.l, None, accent=True)
    s.arrow((vol.x + 140, 114), w1.l, None, accent=True, both=True)
    s.arrow((vol.x + 140, 166), w2.l, None, accent=True, both=True)
    s.mono(192, 214, 'healthcheck у api и воркеров · stop_grace_period 120 с', 10.5, INK2)
    s.mono(192, 234, 'лимит памяти 512m · журнал 10m × 5 · порт только на localhost', 10.5, INK2)
    # внешнее
    model = s.box(704, 60, 240, 44, 'Модель', 'лимит в минуту → 429, 529', muted=True, size=13)
    mail = s.box(704, 112, 240, 44, 'Почтовый шлюз', 'Idempotency-Key = ключ:reply', accent=True, size=13)
    logs = s.box(704, 164, 240, 44, 'Сборщик логов', 'JSON: задача, мс, токены, $', muted=True, size=13)
    mon = s.box(704, 216, 240, 44, 'Мониторинг', 'очередь, возраст, dead-letter', muted=True, size=13)
    s.arrow(w1.r, model.l)
    s.arrow(w2.r, mail.l, None, accent=True, via=[(680, 166), (680, 134)])
    s.arrow((672, 186), logs.l, None, dashed=True)
    s.arrow((672, 238), mon.l, None, dashed=True)
    # где ломается
    s.text(16, 306, 'Где ломается и что спасает', 14, INK, 'start', 600)
    rows = [('kill -9 воркера', 'аренда истекает через 60 с, задачу берёт другой воркер'),
            ('429 в пике', 'повтор через retry-after провайдера или backoff с джиттером'),
            ('зависший вызов', 'таймаут 30 с вместо 10 минут SDK по умолчанию'),
            ('письмо ушло, упал итог', 'повтор задачи, второе письмо не уходит: ключ уже был'),
            ('битая задача', 'сразу в dead-letter с причиной, попытки не жжёт'),
            ('рестарт, деплой', 'задачи лежат на томе; SIGTERM — воркер доделывает задачу')]
    y = 336
    for tag, text in rows:
        s.rule(16, y - 18, 944, y - 18)
        s.text(16, y, tag, 13, RED, 'start', 500)
        s.text(230, y, text, 13, INK2)
        y += 24
    s.rule(16, 476, 944, 476)
    s.note(16, 500, ['Хаос-тест deploy/chaos.sh: 100 задач, повторы с тем же ключом, воркер убивает себя kill -9 сразу после',
                     'письма примерно в 10 % задач. Прогон автора: все задачи done, 100 писем на 100 задач, дублей 0.'],
           12, INK3)
    return s.save(p_('razbor07-architecture.svg'))


# ------------------------------------------------ сбои по одному
FAULTS = [
    # (сбой, наивная, очередь без ключей, прод) — «потеряно · дубли», seed 48, 1 000 задач
    ('Без сбоев', '0 · 0', '0 · 0', '0 · 0'),
    ('Лимит 50 в минуту, утренний пик', '173 · 3', '0 · 32', '0 · 0'),
    ('Перегрузка 529, 1 % вызовов', '0 · 0', '0 · 0', '0 · 0'),
    ('Обрыв посреди ответа, 1 %', '0 · 0', '0 · 0', '0 · 0'),
    ('Вызов завис, 0,5 %', '0 · 6', '0 · 0', '0 · 0'),
    ('kill -9 раз в 30 минут', '0 · 2', '0 · 0', '0 · 0'),
    ('Ответ API потерялся, 1 %', '0 · 10', '0 · 10', '0 · 0'),
    ('Битая задача, 0,5 %', '6 · 0', '0 · 0', '0 · 0'),
    ('Всё вместе', '180 · 22', '0 · 40', '0 · 0'),
]


def faults():
    s = Scheme(960, 470, title='Какой сбой что делает: потеряно · дубли на 1 000 задач', accent='green')
    cols = [(16, 'Сбой', 'start'), (560, 'Наивная', 'end'), (750, 'Очередь без ключей', 'end'), (944, 'Прод', 'end')]
    y0 = 76
    for x, t, a in cols:
        s.text(x, y0, t, 12, INK3, a, 600)
    y = y0 + 34
    for name, a, b, c in FAULTS:
        last = name == 'Всё вместе'
        s.rule(16, y - 22, 944, y - 22, dashed=not last)
        s.text(16, y, name, 14, INK, 'start', 700 if last else 500)
        for x, v in ((560, a), (750, b), (944, c)):
            bad = v != '0 · 0'
            s.mono(x, y, v, 14 if last else 13, RED if bad else GREEN, 'end')
        y += 36
    s.rule(16, y - 22, 944, y - 22)
    s.note(16, y + 2, ['SDK с двумя повторами сам переживает редкие 529 и обрывы. Ломают схему пик лимита, зависание с таймаутом',
                       '10 минут, kill -9 и потерянный ответ. Битые задачи прод не теряет: шесть лежат в dead-letter с причиной.'],
           12, INK3)
    return s.save(p_('razbor07-faults.svg'))


if __name__ == '__main__':
    only = set(sys.argv[1:])
    for fn in [main, architecture, faults]:
        if not only or fn.__name__ in only:
            print(fn())
