"""Синтетический каталог вымышленной сети «Тёплый квартал»: обувь, одежда, товары для дома.

Две выгрузки одного каталога:
- `catalog_1c.csv` — что знает учётная система (1С): все поля заполнены, это «истина»;
- `catalog.csv` — что опубликовано в карточке (сайт, фид маркетплейса) и что увидит агент.

Карточка получается из учётной записи порчей с фиксированным seed: поле теряется (пустая строка),
а GTIN иногда приходит с ошибкой контрольной цифры. Карточка никогда не придумывает новых значений —
поэтому всё, что агент отсёк, «чинится» копированием поля из 1С.
"""
from __future__ import annotations

import csv
import io
import random

SEED = 17
COLUMNS = ["sku", "title", "category", "product_type", "brand", "description", "color", "sizes",
           "target_gender", "gtin", "price", "currency", "available", "ships_to", "delivery_days",
           "rating", "rating_count", "image_url", "image_alt", "tech_specs"]

# Вероятность, что поле не доехало из 1С до карточки
DEFECTS = {
    "color": 0.15, "sizes": 0.2, "target_gender": 0.25, "gtin": 0.12, "available": 0.15,
    "ships_to": 0.15, "delivery_days": 0.2, "rating_count": 0.25, "currency": 0.1,
    "tech_specs": 0.3, "image_alt": 0.35,
}
GTIN_TYPO = 0.06  # GTIN есть, но с ошибкой контрольной цифры

SHOE_SIZES = ["39", "40", "41", "42", "43", "44", "45"]
CLOTH_SIZES = ["XS", "S", "M", "L", "XL", "XXL"]

# Линейки товаров. Целевые линейки (под сценарии eval) подходят покупателю по цене и размеру,
# остальные — «соседи» по категории, которые агент должен отсечь честно.
def _line(cat, ptype, gender, brands, base, price, colors, sizes, count, specs, word="", core=(), rating=(4.0, 4.9)):
    return {"cat": cat, "ptype": ptype, "gender": gender, "brands": brands, "base": base, "price": price,
            "colors": colors, "sizes": sizes, "count": count, "specs": specs, "word": word, "core": core,
            "rating": rating}


LINES = [
    _line("Обувь", "Кроссовки", "Мужской", ["Тропа", "Северный шаг", "Кедр"], "Кроссовки мужские", (5490, 7990),
          ["Черный", "Серый", "Синий"], SHOE_SIZES, 10,
          ["Материал верха: текстиль с мембраной", "Мембрана: водонепроницаемая", "Подошва: резина", "Сезон: демисезон"],
          word="непромокаемые", core=("42",)),
    _line("Обувь", "Кроссовки", "Мужской", ["Тропа", "Берег"], "Кроссовки мужские летние", (3990, 6490),
          ["Белый", "Серый"], SHOE_SIZES, 3, ["Материал верха: сетка", "Подошва: ЭВА", "Сезон: лето"], core=("42",)),
    _line("Обувь", "Кроссовки", "Женский", ["Тропа", "Метелица"], "Кроссовки женские", (4990, 7990),
          ["Белый", "Розовый", "Черный"], ["36", "37", "38", "39", "40"], 3,
          ["Материал верха: текстиль", "Подошва: резина", "Сезон: демисезон"]),
    _line("Обувь", "Ботинки", "Мужской", ["Кедр", "Северный шаг"], "Ботинки мужские зимние", (7990, 12990),
          ["Черный", "Коричневый"], SHOE_SIZES, 3,
          ["Материал верха: натуральная кожа", "Утеплитель: шерсть", "Подошва: термопластичная резина", "Сезон: зима"]),
    _line("Обувь", "Кеды", "Унисекс", ["Берег"], "Кеды", (2490, 3990), ["Белый", "Черный"],
          ["37", "38", "39", "40", "41", "42", "43"], 3, ["Материал верха: хлопковая парусина", "Подошва: резина"]),
    _line("Одежда", "Куртка", "Женский", ["Метелица", "Северный шаг"], "Куртка женская пуховая", (8990, 11990),
          ["Черный", "Бежевый", "Черный"], CLOTH_SIZES, 9,
          ["Утеплитель: натуральный пух 90/10", "Ткань верха: полиэстер с водоотталкивающей пропиткой",
           "Капюшон: съёмный", "Температурный режим: до −25 °C"], word="пуховая", core=("M",)),
    _line("Одежда", "Толстовка", "Мужской", ["Кедр", "Берег"], "Толстовка мужская флисовая", (2490, 3990),
          ["Серый", "Синий", "Черный"], CLOTH_SIZES, 7,
          ["Материал: флис 280 г/м²", "Застёжка: молния", "Карманы: два боковых"], word="флисовая", core=("L",)),
    _line("Одежда", "Футболка", "Унисекс", ["Лён и хлопок"], "Футболка базовая", (790, 1490),
          ["Белый", "Черный", "Серый"], CLOTH_SIZES, 3, ["Состав: хлопок 100%", "Плотность: 180 г/м²"]),
    _line("Одежда", "Брюки", "Мужской", ["Кедр"], "Брюки мужские утеплённые", (3490, 5990),
          ["Черный", "Хаки"], CLOTH_SIZES, 3, ["Состав: софтшелл", "Утеплитель: флис"]),
    _line("Дом", "Постельное бельё", "", ["Уют", "Лён и хлопок"], "Комплект постельного белья сатин", (3490, 5990),
          ["Серый", "Серый", "Белый"], ["1,5-спальный", "2-спальный", "Евро"], 9,
          ["Ткань: сатин", "Состав: хлопок 100%", "Плотность: 125 г/м²", "В комплекте: пододеяльник, простыня, 2 наволочки"],
          word="сатин", core=("2-спальный",), rating=(4.4, 4.9)),
    _line("Дом", "Полотенце", "", ["Уют"], "Полотенце банное махровое", (690, 1490),
          ["Белый", "Голубой"], ["50×90", "70×140"], 4, ["Состав: хлопок 100%", "Плотность: 450 г/м²"]),
    _line("Дом", "Плед", "", ["Уют", "Лён и хлопок"], "Плед флисовый", (1290, 2990),
          ["Серый", "Бежевый"], ["130×170", "150×200"], 3, ["Материал: флис", "Плотность: 220 г/м²"]),
]
DESCRIPTIONS = {
    "Кроссовки": "Удобная модель на каждый день: мягкая амортизация и устойчивая колодка.",
    "Кеды": "Классические кеды для города.",
    "Ботинки": "Тёплые ботинки для городской зимы.",
    "Куртка": "Лёгкая и тёплая куртка для города.",
    "Толстовка": "Мягкая толстовка для дома и прогулок.",
    "Футболка": "Базовая футболка свободного кроя.",
    "Брюки": "Брюки для холодной погоды.",
    "Постельное бельё": "Комплект для спокойного сна.",
    "Полотенце": "Мягкое полотенце для ванной.",
    "Плед": "Тёплый плед для дома и дачи.",
}


def gtin_ok(code: str) -> bool:
    """EAN-13 с верной контрольной цифрой."""
    if len(code) != 13 or not code.isdigit():
        return False
    s = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(code[:12]))
    return (10 - s % 10) % 10 == int(code[12])


def _gtin(n: int) -> str:
    body = f"46{n:010d}"
    s = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body))
    return body + str((10 - s % 10) % 10)


def _sizes(rng: random.Random, sizes: list[str], core: tuple) -> str:
    """Непрерывный диапазон размеров; обязательные (core) всегда внутри."""
    while True:
        k = rng.randint(max(2, len(sizes) - 3), len(sizes))
        start = rng.randint(0, len(sizes) - k)
        got = sizes[start:start + k]
        if all(c in got for c in core):
            return ";".join(got)


def _erp_rows(rng: random.Random) -> list[dict]:
    rows = []
    n = 0
    for ln in LINES:
        for i in range(ln["count"]):
            n += 1
            brand = ln["brands"][i % len(ln["brands"])]
            model = f"{brand} {rng.choice(['Трейл', 'Город', 'Норд', 'Лайт', 'Про', 'Классик'])} {i + 1}"
            word = ln["word"]
            title = f"{ln['base']} {word} {model}" if word and rng.random() < 0.4 else f"{ln['base']} {model}"
            color = ln["colors"][i % len(ln["colors"])]
            pmin, pmax = ln["price"]
            rows.append({
                "sku": f"TK-{n:04d}", "title": title, "category": ln["cat"], "product_type": ln["ptype"],
                "brand": brand, "description": DESCRIPTIONS[ln["ptype"]], "color": color,
                "sizes": _sizes(rng, ln["sizes"], ln["core"]), "target_gender": ln["gender"], "gtin": _gtin(n),
                "price": str(rng.randrange(pmin, pmax + 1, 100)), "currency": "RUB",
                "available": "true" if rng.random() < 0.92 else "false",
                "ships_to": "RU;BY;KZ" if rng.random() < 0.85 else "RU",
                "delivery_days": rng.choice(["1-3", "2-4", "3-5"]),
                "rating": f"{rng.uniform(*ln['rating']):.1f}",
                "rating_count": str(rng.choice([4, 9, 14] + list(range(21, 160, 7)))),
                "image_url": f"https://example.com/img/TK-{n:04d}.jpg", "image_alt": f"{title}, цвет {color.lower()}",
                "tech_specs": "; ".join(ln["specs"]),
            })
    return rows


def _card(row: dict, rng: random.Random) -> dict:
    card = dict(row)
    for col, p in DEFECTS.items():
        if rng.random() < p:
            card[col] = ""
    if card["gtin"] and rng.random() < GTIN_TYPO:
        g = card["gtin"]
        card["gtin"] = g[:12] + str((int(g[12]) + 1) % 10)
    return card


def make_catalog(seed: int = SEED) -> tuple[list[dict], list[dict]]:
    """(карточки, учётная система) — одинаковый порядок и одинаковые sku."""
    rng = random.Random(seed)
    erp = _erp_rows(rng)
    cards = [_card(r, rng) for r in erp]
    return cards, erp


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def read_csv(path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
