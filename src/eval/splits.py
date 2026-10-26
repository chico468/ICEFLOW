"""Leakage-proof splits for time series evaluation."""
from __future__ import annotations

from datetime import date, timedelta
from typing import List, Tuple

import numpy as np


def _to_ordinals(dates: List[date]) -> np.ndarray:
    return np.array(sorted({d.toordinal() for d in dates}), dtype=np.int64)


def check_no_leakage(train_dates: List[date], test_dates: List[date], max_lead_days: int):
    """Assert no leakage between train and test.

    No date may appear in both sets, the train set must be non-empty, and no
    training date may sit within ``max_lead_days`` of a test date on either side.
    """
    if not train_dates:
        raise AssertionError("Empty training set: cannot evaluate without history.")
    train_set = set(train_dates)
    test_set = set(test_dates)
    overlap = train_set.intersection(test_set)
    if overlap:
        raise AssertionError(f"Train/test overlap: {sorted(overlap)}")
    tr = _to_ordinals(train_dates)
    for td in test_dates:
        o = td.toordinal()
        pos = int(np.searchsorted(tr, o))
        candidates = []
        if pos < len(tr):
            candidates.append(int(tr[pos]))
        if pos > 0:
            candidates.append(int(tr[pos - 1]))
        for c in candidates:
            diff = abs(o - c)
            if 0 < diff <= max_lead_days:
                raise AssertionError(
                    f"Leakage: train date within {max_lead_days} days of test origin {td}"
                )
    return True


def leave_one_year_out(
    dates: List[date], embargo_days: int = 14
) -> List[Tuple[List[date], List[date]]]:
    """Leave-one-year-out cross-validation.

    For each calendar year present in ``dates``:
      * test dates  = all dates falling in that year
      * train dates = dates from *all other* years, excluding a window of
        ``embargo_days`` on both sides of the test year (``test_start - embargo``
        and ``test_end + embargo``).

    This trains on every other year (both earlier and later), so the earliest
    year never has an empty training set. An empty training set raises.
    """
    years = sorted({d.year for d in dates})
    splits_list: List[Tuple[List[date], List[date]]] = []
    for test_year in years:
        test_dates = [d for d in dates if d.year == test_year]
        if not test_dates:
            continue
        test_start = min(test_dates)
        test_end = max(test_dates)
        lo_bound = test_start - timedelta(days=embargo_days)
        hi_bound = test_end + timedelta(days=embargo_days)
        train_dates = [
            d for d in dates
            if d.year != test_year and (d < lo_bound or d > hi_bound)
        ]
        if not train_dates:
            raise ValueError(
                f"leave_one_year_out left an empty training set for year {test_year}; "
                f"need data from at least one other year."
            )
        check_no_leakage(train_dates, test_dates, embargo_days)
        splits_list.append((sorted(train_dates), sorted(test_dates)))
    return splits_list


def final_held_out_recent_block(dates: List[date], holdout_years: int = 1, embargo_days: int = 14):
    """Hold out the most recent ``holdout_years`` calendar years as the test set.

    Training data is everything from earlier years, embargoed by ``embargo_days``
    before the first test date.
    """
    years = sorted({d.year for d in dates})
    if len(years) < 2:
        raise ValueError("Need at least 2 years for held-out block")
    test_years = set(years[-holdout_years:])
    test_dates_check = [d for d in dates if d.year in test_years]
    if test_dates_check:
        test_start = min(test_dates_check)
        train_dates = [
            d for d in dates
            if d.year not in test_years and (test_start - d).days > embargo_days
        ]
        test_dates = [d for d in dates if d.year in test_years]
    else:
        train_dates = [d for d in dates if d.year not in test_years]
        test_dates = [d for d in dates if d.year in test_years]
    if not train_dates:
        raise ValueError("Empty training set after embargo.")
    check_no_leakage(train_dates, test_dates, embargo_days)
    return sorted(train_dates), sorted(test_dates)
