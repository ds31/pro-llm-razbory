"""Пересоздать data/catalog.csv (карточки) и data/catalog_1c.csv (учётная система) с фиксированным seed.

Запуск из папки пакета: uv run python data/make_catalog.py
"""
from pathlib import Path

from razbor02.synth import SEED, make_catalog, to_csv

HERE = Path(__file__).resolve().parent


def main() -> None:
    cards, erp = make_catalog(SEED)
    (HERE / "catalog.csv").write_text(to_csv(cards), encoding="utf-8")
    (HERE / "catalog_1c.csv").write_text(to_csv(erp), encoding="utf-8")
    print(f"карточек: {len(cards)} → {HERE / 'catalog.csv'}, {HERE / 'catalog_1c.csv'}")


if __name__ == "__main__":
    main()
