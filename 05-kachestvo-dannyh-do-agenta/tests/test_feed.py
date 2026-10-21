from datetime import date

from razbor05 import defects as D
from razbor05.feed import FEED_END, FEED_START, MONTH_END, calendar_closed_through, make_feed


def test_feed_is_deterministic(base):
    a, b = make_feed(base, 46), make_feed(base, 46)
    assert a.truth_sales == b.truth_sales and len(a.loads) == len(b.loads)


def test_feed_shape(base):
    feed = make_feed(base)
    n_days = (FEED_END - FEED_START).days + 1
    assert sum(1 for ld in feed.loads.values() if ld.kind == "sales") == 12 * n_days
    assert sum(1 for ld in feed.loads.values() if ld.kind == "stock") == 12
    ld = feed.sales_load(4, date(2026, 10, 10))
    assert ld.received_on == date(2026, 10, 11)
    assert feed.stock_load(4).received_on == date(2026, 11, 2)
    assert all(r[4] < 1000 for rows in feed.truth_sales.values() for r in rows)


def test_calendar_close():
    assert calendar_closed_through(date(2026, 10, 31)) == date(2026, 9, 30)
    assert calendar_closed_through(date(2026, 11, 1)) == MONTH_END


def test_defects_change_feed_not_truth(base):
    feed = make_feed(base)
    before = list(feed.truth_sales[(4, date(2026, 10, 28))])
    inj = D.kopecks(feed, 4, date(2026, 10, 28))
    assert feed.truth_sales[(4, date(2026, 10, 28))] == before
    lid = next(iter(inj.loads))
    assert float(feed.sales[lid][0][5]) == round(float(before[0][5]) * 100, 2)
    fix = [ld for ld in feed.loads.values() if ld.on_request]
    assert len(fix) == 1 and fix[0].replaces and fix[0].received_on is None


def test_random_defects_reproducible(base):
    import random
    a, b = make_feed(base, 7), make_feed(base, 7)
    da = [i.defect for i in D.random_defects(a, random.Random(7))]
    db = [i.defect for i in D.random_defects(b, random.Random(7))]
    assert da == db and 3 <= len(da) <= 6
