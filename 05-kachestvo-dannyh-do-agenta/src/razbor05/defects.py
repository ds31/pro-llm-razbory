"""Дефекты загрузки с известной правдой.

Каждый дефект портит поток (`Feed.sales/stock/products/loads`), а правда (`Feed.truth_*`) остаётся как было
на самом деле. Возвращается `Injection`: какое правило должно его поймать и по каким строкам или разделам.
Исправленный файл от источника (`on_request`) приходит, только если ворота его попросили.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .feed import FEED_START, MONTH_END, Feed, days

NEW_SKU_CATEGORY = ("Напитки", "Утро")


@dataclass
class Injection:
    defect: str
    rule: str                                   # правило, которое должно поймать
    rows: set = field(default_factory=set)      # (load_id, row_no) испорченных строк
    loads: set = field(default_factory=set)     # файлы целиком
    parts: set = field(default_factory=set)     # (store_id, day) разделы, которых коснулся дефект
    fixes: set = field(default_factory=set)     # исправленные файлы, которые источник пришлёт по запросу
    note: str = ""


DEFECTS = {
    # id: (название, правило, что делает с данными)
    "scanner": ("ошибка сканера, qty = 9999", "R01", "строка с количеством 9999 попадает в выручку"),
    "reload": ("повторная загрузка дневного пакета", "R02", "все файлы дня загружены второй раз"),
    "missing": ("магазин не прислал файл за день", "C01", "день магазина приходит с опозданием"),
    "kopecks": ("сумма в копейках вместо рублей", "R04", "суммы файла умножены на 100"),
    "negative_stock": ("отрицательные остатки в снимке", "R06", "у части SKU остаток со знаком минус"),
    "future_date": ("дата из будущего", "R03", "у файла год 2027 вместо 2026"),
    "unknown_sku": ("SKU, которого нет в справочнике", "R05", "новинка продаётся раньше, чем пришла карточка"),
    "dup_card": ("карточка-дубль в справочнике", "R07", "вторая карточка на тот же SKU"),
    "truncated": ("тихий: файл обрезан по лимиту строк", "R08", "касса выгружает не больше N строк"),
}


def _rows_of(feed: Feed, load_id: int, kind: str = "sales") -> set:
    rows = (feed.sales if kind == "sales" else feed.stock if kind == "stock" else feed.products)[load_id]
    return {(load_id, n) for n in range(1, len(rows) + 1)}


def scanner(feed: Feed, store_id: int, day: date, n: int = 1, rng: random.Random | None = None) -> Injection:
    rng = rng or random.Random(0)
    ld = feed.sales_load(store_id, day)
    inj = Injection("scanner", "R01", parts={(store_id, day)})
    for _ in range(n):
        sku = feed.skus[rng.randrange(len(feed.skus))]
        price = round(feed.prices[sku], 2)
        feed.sales[ld.load_id].append([feed.take_sale_id(), day, store_id, sku, 9999, round(9999 * price, 2)])
        inj.rows.add((ld.load_id, len(feed.sales[ld.load_id])))
    return inj


def reload(feed: Feed, day: date, after: int = 1, stores: list[int] | None = None) -> Injection:
    """Пакет файлов дня загружен второй раз (через `after` дней после первого)."""
    stores = stores or [s for s, _ in feed.stores]
    inj = Injection("reload", "R02")
    for s in stores:
        src = feed.sales_load(s, day)
        ld = feed.new_load("sales", s, day, src.received_on + timedelta(after), label="reload")
        feed.sales[ld.load_id] = [list(r) for r in feed.sales[src.load_id]]
        inj.rows |= _rows_of(feed, ld.load_id)
        inj.loads.add(ld.load_id)
        inj.parts.add((s, day))
    return inj


def missing(feed: Feed, store_id: int, day: date, late: int = 4) -> Injection:
    """Магазин не прислал файл вовремя: файл приходит на `late` дней позже."""
    ld = feed.sales_load(store_id, day)
    ld.received_on = ld.received_on + timedelta(late)
    return Injection("missing", "C01", parts={(store_id, day)}, loads={ld.load_id})


def _fix_load(feed: Feed, kind: str, store_id: int, day: date, lag: int, rows: list) -> int:
    ld = feed.new_load(kind, store_id, day, None, replaces=True, on_request=True, lag=lag, label="fix")
    (feed.sales if kind == "sales" else feed.stock)[ld.load_id] = [list(r) for r in rows]
    return ld.load_id


def kopecks(feed: Feed, store_id: int, day: date, lag: int = 2) -> Injection:
    ld = feed.sales_load(store_id, day)
    for r in feed.sales[ld.load_id]:
        r[5] = round(float(r[5]) * 100, 2)
    fix = _fix_load(feed, "sales", store_id, day, lag, feed.truth_sales[(store_id, day)])
    return Injection("kopecks", "R04", rows=_rows_of(feed, ld.load_id), loads={ld.load_id}, parts={(store_id, day)},
                     fixes={fix})


def future_date(feed: Feed, store_id: int, day: date, lag: int = 2) -> Injection:
    ld = feed.sales_load(store_id, day)
    for r in feed.sales[ld.load_id]:
        r[1] = r[1].replace(year=r[1].year + 1)
    fix = _fix_load(feed, "sales", store_id, day, lag, feed.truth_sales[(store_id, day)])
    return Injection("future_date", "R03", rows=_rows_of(feed, ld.load_id), loads={ld.load_id},
                     parts={(store_id, day)}, fixes={fix})


def negative_stock(feed: Feed, store_id: int, n: int = 15, lag: int = 2,
                   rng: random.Random | None = None) -> Injection:
    rng = rng or random.Random(0)
    ld = feed.stock_load(store_id)
    rows = feed.stock[ld.load_id]
    inj = Injection("negative_stock", "R06", parts={(store_id, MONTH_END)})
    for k in rng.sample(range(len(rows)), n):
        rows[k][3] = -rng.randint(1, 30)
        inj.rows.add((ld.load_id, k + 1))
    inj.fixes.add(_fix_load(feed, "stock", store_id, MONTH_END, lag, feed.truth_stock[store_id]))
    return inj


def unknown_sku(feed: Feed, start: date, card_late: int = 6, share: float = 0.5,
                rng: random.Random | None = None, sku: str = "SKU-0201", price: float = 149.0) -> Injection:
    """Новинка продаётся с `start`, карточка в справочнике появляется через `card_late` дней после первой продажи."""
    rng = rng or random.Random(0)
    inj = Injection("unknown_sku", "R05")
    category, brand = NEW_SKU_CATEGORY
    for d in days(start, MONTH_END):
        for s, _ in feed.stores:
            if rng.random() >= share:
                continue
            qty = rng.randint(1, 4)
            row = (feed.take_sale_id(), d, s, sku, qty, round(qty * price, 2))
            feed.truth_sales[(s, d)].append(row)
            ld = feed.sales_load(s, d)
            feed.sales[ld.load_id].append(list(row))
            inj.rows.add((ld.load_id, len(feed.sales[ld.load_id])))
            inj.parts.add((s, d))
    card_day = start + timedelta(1 + card_late)
    card = (sku, "Товар 201", category, brand, datetime(card_day.year, card_day.month, card_day.day, 6, 0))
    feed.truth_products.append(card)
    ld = feed.new_load("products", None, card_day, card_day, label="catalog")
    feed.products[ld.load_id] = [list(card)]
    return inj


def dup_card(feed: Feed, day: date, sku: str = "SKU-0003") -> Injection:
    """В справочник пришла вторая карточка на уже существующий SKU (как ловушка дублей пакета 01)."""
    k = int(sku.split("-")[1])
    ld = feed.new_load("products", None, day, day, label="catalog")
    category = _category_of(k)
    feed.products[ld.load_id] = [[sku, f"Товар {k} (новая карточка)", category, _brand_of(k),
                                  datetime(day.year, day.month, day.day, 6, 0)]]
    return Injection("dup_card", "R07", rows={(ld.load_id, 1)}, loads={ld.load_id})


def truncated(feed: Feed, store_id: int, first: date, n_days: int = 10, cap: int = 10) -> Injection:
    """Тихий дефект: касса выгружает не больше `cap` строк в файл — файлы правдоподобного размера."""
    inj = Injection("truncated", "R08")
    for d in days(first, min(first + timedelta(n_days - 1), MONTH_END)):
        ld = feed.sales_load(store_id, d)
        if len(feed.sales[ld.load_id]) > cap:
            del feed.sales[ld.load_id][cap:]
            inj.loads.add(ld.load_id)
            inj.parts.add((store_id, d))
    return inj


# категории и бренды — как в генераторе пакета 01
_CATS = ["Молочные продукты", "Бакалея", "Напитки", "Бытовая химия", "Снеки", "Заморозка"]
_BRANDS = ["Полдень", "Северная марка", "Добрый двор", "Сокол", "Луговое",
           "Бережок", "Простые вещи", "Утро", "Ладья", "Своё"]


def _category_of(k: int) -> str:
    return _CATS[(k - 1) % len(_CATS)]


def _brand_of(k: int) -> str:
    return _BRANDS[(k * 7) % len(_BRANDS)]


# --------------------------------------------------------------------------- витрина и случайные сценарии
SHOWCASE_STORE = 4      # регион «Восток»: его видят вопросы про регион и про магазин


def showcase(feed: Feed, defect: str) -> Injection | None:
    """Один дефект в фиксированном месте — для таблицы «что искажает и что ловит»."""
    s = SHOWCASE_STORE
    rng = random.Random(46)
    match defect:
        case "clean":
            return None
        case "scanner":
            return scanner(feed, s, date(2026, 10, 20), n=1, rng=rng)
        case "reload":
            return reload(feed, date(2026, 10, 21), after=2)
        case "missing":
            return missing(feed, s, date(2026, 10, 31), late=4)
        case "kopecks":
            return kopecks(feed, s, date(2026, 10, 28), lag=2)
        case "negative_stock":
            return negative_stock(feed, s, n=15, lag=2, rng=rng)
        case "future_date":
            return future_date(feed, s, date(2026, 10, 29), lag=2)
        case "unknown_sku":
            return unknown_sku(feed, date(2026, 10, 25), card_late=8, rng=rng)
        case "dup_card":
            return dup_card(feed, date(2026, 10, 15), sku="SKU-0003")
        case "truncated":
            return truncated(feed, s, date(2026, 10, 22), n_days=10, cap=10)
    raise ValueError(defect)


def random_defects(feed: Feed, rng: random.Random, k: int | None = None) -> list[Injection]:
    """Случайный сценарий: k дефектов разных типов в разных разделах октября, со случайной силой."""
    types = list(DEFECTS)
    k = k or rng.randint(3, 6)
    # порядок внесения фиксирован: обрезка — до дописанных строк, повторная загрузка копирует итоговый файл
    order = ["truncated", "unknown_sku", "scanner", "kopecks", "future_date", "missing", "negative_stock",
             "dup_card", "reload"]
    chosen = sorted(rng.sample(types, k), key=order.index)
    used: set = set()
    out = []
    store_ids = [s for s, _ in feed.stores]

    def free_part():
        while True:
            p = (rng.choice(store_ids), FEED_START + timedelta(rng.randrange(31)))
            if p not in used:
                used.add(p)
                return p

    for t in chosen:
        if t == "scanner":
            s, d = free_part()
            out.append(scanner(feed, s, d, n=rng.randint(1, 3), rng=rng))
        elif t == "reload":
            d = FEED_START + timedelta(rng.randrange(31))
            stores = None if rng.random() < 0.5 else [rng.choice(store_ids)]
            out.append(reload(feed, d, after=rng.randint(0, 3), stores=stores))
        elif t == "missing":
            s, d = free_part()
            out.append(missing(feed, s, d, late=rng.randint(1, 6)))
        elif t == "kopecks":
            s, d = free_part()
            out.append(kopecks(feed, s, d, lag=rng.randint(1, 3)))
        elif t == "negative_stock":
            out.append(negative_stock(feed, rng.choice(store_ids), n=rng.randint(3, 20), lag=rng.randint(1, 3),
                                      rng=rng))
        elif t == "future_date":
            s, d = free_part()
            out.append(future_date(feed, s, d, lag=rng.randint(1, 3)))
        elif t == "unknown_sku":
            out.append(unknown_sku(feed, FEED_START + timedelta(rng.randrange(28)), card_late=rng.randint(1, 8),
                                   share=0.3, rng=rng))
        elif t == "dup_card":
            d = FEED_START + timedelta(rng.randrange(31))
            out.append(dup_card(feed, d, sku=f"SKU-{rng.randint(1, 200):04d}"))
        elif t == "truncated":
            s, d = free_part()
            out.append(truncated(feed, s, d, n_days=rng.randint(1, 10), cap=rng.randint(4, 11)))
    return out
