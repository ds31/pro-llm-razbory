# -*- coding: utf-8 -*-
"""Схемы архитектуры для статей блога — SVG в editorial-стиле сайта.

Светлый холст, hairline-рамки, чёрные чернила, цвет только как пунктуация
(один акцент на схему — то, о чём спор). Подписи узлов — Inter, подписи
стрелок и метрики — JetBrains Mono; внутри <img> веб-шрифты страницы не
грузятся, поэтому у каждого семейства есть системный фолбэк.

Использование (из статьи-скрипта или REPL):
    from scheme import Scheme
    s = Scheme(960, 420, title='…')
    a = s.box(40, 80, 180, 64, 'Источник', 'Postgres')
    b = s.box(320, 80, 180, 64, 'Хранилище', 'ClickHouse', accent=True)
    s.arrow(a.r, b.l, 'CDC, 1 мин')
    s.save('web/public/blog/img/schemes/имя.svg')

Координаты — на сетке 8px; ширина 960 = колонка prose в масштабе 1:1.
"""
from dataclasses import dataclass
from xml.sax.saxutils import escape

# Палитра сайта v2, вариант B «Тушь и Байкал» (web/src/styles/tokens.css). Картинки статей,
# нарисованные до 2026-10, остаются в палитре v1 — их не перегенерируем.
INK, INK2, INK3 = '#14181d', '#3a4048', '#5b6169'
HAIR, HAIR_CARD, PAUSE = '#e4dfd2', '#d8d2c2', '#efebdf'
PAPER = '#f7f5ee'
ACCENTS = {
    'teal': ('#245f86', 'rgba(36,95,134,0.08)'),
    'orange': ('#e17100', 'rgba(251,136,65,0.08)'),
    'green': ('#0b7d4f', 'rgba(47,216,138,0.12)'),
    'blue': ('#155dfc', 'rgba(124,196,255,0.12)'),
    'red': ('#d9363e', 'rgba(255,100,103,0.08)'),
}
SANS = "Onest, 'Onest Variable', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
MONO = "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace"


@dataclass
class Node:
    x: float
    y: float
    w: float
    h: float

    @property
    def l(self): return (self.x, self.y + self.h / 2)
    @property
    def r(self): return (self.x + self.w, self.y + self.h / 2)
    @property
    def t(self): return (self.x + self.w / 2, self.y)
    @property
    def b(self): return (self.x + self.w / 2, self.y + self.h)
    @property
    def c(self): return (self.x + self.w / 2, self.y + self.h / 2)

    def at(self, side, k=0.5):
        """Точка на стороне side ('l','r','t','b') на доле k длины стороны."""
        if side == 'l': return (self.x, self.y + self.h * k)
        if side == 'r': return (self.x + self.w, self.y + self.h * k)
        if side == 't': return (self.x + self.w * k, self.y)
        return (self.x + self.w * k, self.y + self.h)


class Scheme:
    def __init__(self, w, h, title='', accent='teal'):
        self.w, self.h, self.title = w, h, title
        self.acc, self.acc_soft = ACCENTS[accent]
        self.back, self.front = [], []

    # --- примитивы -------------------------------------------------------
    def text(self, x, y, s, size=13, color=INK, anchor='start', weight=400,
             family=SANS, layer='front', italic=False):
        style = ' font-style="italic"' if italic else ''
        (self.front if layer == 'front' else self.back).append(
            f'<text x="{x:g}" y="{y:g}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{color}" text-anchor="{anchor}"{style}>{escape(s)}</text>')

    def mono(self, x, y, s, size=11, color=INK2, anchor='start', layer='front'):
        self.text(x, y, s, size, color, anchor, 400, MONO, layer)

    def box(self, x, y, w, h, label, sub=None, accent=False, muted=False,
            dashed=False, fill=None, size=14, sub2=None):
        stroke = self.acc if accent else (HAIR_CARD if not muted else HAIR)
        bg = fill or (self.acc_soft if accent else ('#ffffff' if not muted else PAUSE))
        dash = ' stroke-dasharray="4 4"' if dashed else ''
        sw = 1.5 if accent else 1
        self.back.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="8" '
                         f'fill="{bg}" stroke="{stroke}" stroke-width="{sw}"{dash}/>')
        lines = [label] + ([sub] if sub else []) + ([sub2] if sub2 else [])
        total = size + (len(lines) - 1) * 16
        cy = y + h / 2 - total / 2 + size - 2
        col = self.acc if accent else (INK if not muted else INK2)
        self.text(x + w / 2, cy, label, size, col, 'middle', 500)
        for i, s in enumerate(lines[1:]):
            self.mono(x + w / 2, cy + 17 * (i + 1), s, 11, INK2, 'middle')
        return Node(x, y, w, h)

    def group(self, x, y, w, h, label, accent=False, fill=PAUSE, note=None):
        stroke = self.acc if accent else HAIR_CARD
        self.back.insert(0, f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="10" '
                            f'fill="{fill}" stroke="{stroke}" stroke-dasharray="5 4"/>')
        self.text(x + 14, y + 20, label.upper(), 10.5, self.acc if accent else INK3, 'start',
                  600, SANS, 'back')
        if note:
            self.mono(x + w - 14, y + 20, note, 10.5, INK3, 'end', 'back')
        return Node(x, y, w, h)

    def pill(self, x, y, s, accent=False):
        w = 7.2 * len(s) + 20
        stroke = self.acc if accent else HAIR_CARD
        self.front.append(f'<rect x="{x:g}" y="{y - 14:g}" width="{w:g}" height="20" rx="10" '
                          f'fill="{"#fff" if not accent else self.acc_soft}" stroke="{stroke}"/>')
        self.mono(x + w / 2, y, s, 11, self.acc if accent else INK2, 'middle')
        return w

    def line(self, pts, accent=False, dashed=False, head=True, width=None):
        col = self.acc if accent else INK2
        sw = width or (1.6 if accent else 1.1)
        dash = ' stroke-dasharray="4 4"' if dashed else ''
        mk = f' marker-end="url(#{"ha" if accent else "h"})"' if head else ''
        d = ' '.join(f'{x:g},{y:g}' for x, y in pts)
        self.back.append(f'<polyline points="{d}" fill="none" stroke="{col}" stroke-width="{sw}" '
                         f'stroke-linejoin="round"{dash}{mk}/>')

    def arrow(self, a, b, label=None, accent=False, dashed=False, via=None,
              lpos=0.5, loff=(0, -7), both=False, anchor='middle'):
        """Стрелка a→b. via — промежуточные точки (для ломаных). Подпись у середины
        самого длинного отрезка (или lpos на прямой)."""
        pts = [a] + (via or []) + [b]
        self.line(pts, accent, dashed)
        if both:
            self.line(list(reversed(pts[:2])), accent, dashed)
        if label:
            segs = list(zip(pts, pts[1:]))
            (x1, y1), (x2, y2) = max(segs, key=lambda s: abs(s[1][0] - s[0][0]) + abs(s[1][1] - s[0][1]))
            lx, ly = x1 + (x2 - x1) * lpos + loff[0], y1 + (y2 - y1) * lpos + loff[1]
            self.mono(lx, ly, label, 10.5, self.acc if accent else INK2, anchor)

    def note(self, x, y, lines, size=11.5, color=INK2, anchor='start'):
        for i, s in enumerate(lines if isinstance(lines, list) else [lines]):
            self.text(x, y + i * (size + 5), s, size, color, anchor)

    def rule(self, x1, y1, x2, y2, dashed=True):
        dash = ' stroke-dasharray="3 4"' if dashed else ''
        self.back.append(f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" stroke="{HAIR_CARD}"{dash}/>')

    # --- вывод -----------------------------------------------------------
    def svg(self):
        head = f'<text x="24" y="34" font-family="{SANS}" font-size="20" font-weight="700" fill="{INK}">{escape(self.title)}</text>' if self.title else ''
        marker = lambda i, c: (f'<marker id="{i}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
                               f'markerHeight="7" orient="auto-start-reverse"><path d="M0,1 L9,5 L0,9 z" fill="{c}"/></marker>')
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" '
                f'width="{self.w}" height="{self.h}" role="img" aria-label="{escape(self.title)}">'
                f'<defs>{marker("h", INK2)}{marker("ha", self.acc)}</defs>'
                f'<rect width="{self.w}" height="{self.h}" fill="{PAPER}"/>'
                f'<rect x="0" y="0" width="{self.w}" height="3" fill="{ACCENTS["green"][0]}"/>'
                + head + ''.join(self.back) + ''.join(self.front) + '</svg>')

    def save(self, path):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.svg())
        return path
