from datetime import date, timedelta

import pytest

from src.eval import splits


def test_loyo_has_embargo():
    dates = []
    for y in [2020, 2021, 2022]:
        for i in range(365):
            dates.append(date(y, 1, 1) + timedelta(days=i))
    loyo = splits.leave_one_year_out(dates, embargo_days=14)
    for train, test in loyo:
        splits.check_no_leakage(train, test, 14)
        assert len(train) > 0
        assert len(test) > 0


def test_loyo_runs_for_all_years():
    dates = []
    for y in [2020, 2021, 2022]:
        for i in range(365):
            dates.append(date(y, 1, 1) + timedelta(days=i))
    loyo = splits.leave_one_year_out(dates, embargo_days=14)
    # One split per year, and the final year (block) is included.
    assert len(loyo) == 3
    test_years = set()
    for train, test in loyo:
        test_years.add(min(d.year for d in test))
    assert test_years == {2020, 2021, 2022}


def test_loyo_no_train_date_within_embargo_either_side():
    dates = []
    for y in [2018, 2019, 2020, 2021, 2022]:
        for i in range(365):
            dates.append(date(y, 1, 1) + timedelta(days=i))
    embargo = 14
    loyo = splits.leave_one_year_out(dates, embargo_days=embargo)
    for train, test in loyo:
        test_set = set(test)
        for td in test:
            for d in train:
                # No training date within embargo_days on either side.
                assert not (0 < abs((td - d).days) <= embargo), (
                    f"train date {d} within embargo of test {td}"
                )


def test_loyo_empty_train_raises():
    # Only one year: leaving it out leaves no training data.
    dates = [date(2020, 1, 1) + timedelta(days=i) for i in range(365)]
    with pytest.raises(ValueError):
        splits.leave_one_year_out(dates, embargo_days=14)


def test_loyo_empty_train_after_embargo_raises():
    # Two years but the second year's only non-test data is inside the embargo.
    dates = []
    for y in [2020, 2021]:
        for i in range(365):
            dates.append(date(y, 1, 1) + timedelta(days=i))
    with pytest.raises(ValueError):
        splits.leave_one_year_out(dates, embargo_days=400)
