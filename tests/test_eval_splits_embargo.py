from datetime import date, timedelta
from src.eval import splits


def test_loyo_has_embargo():
    dates = []
    for y in [2020, 2021, 2022]:
        for i in range(365):
            dates.append(date(y, 1, 1) + timedelta(days=i))
    loyo = splits.leave_one_year_out(dates, embargo_days=14)
    for train, test in loyo:
        splits.check_no_leakage(train, test, 14)
