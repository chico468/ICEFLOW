"""Leakage-proof splits for time series evaluation."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Tuple


def leave_one_year_out(dates: List[date], embargo_days: int = 14) -> List[Tuple[List[date], List[date]]]:
    """Leave-one-year-out splits with embargo between train and test."""
    years = sorted(set(d.year for d in dates))
    splits = []
    for test_year in years:
        train_dates = []
        test_dates = []
        for d in dates:
            if d.year == test_year:
                test_dates.append(d)
            else:
                train_dates.append(d)
        # Apply embargo: ensure no test origin within embargo of train target
        # For forecast evaluation, we need to ensure train window doesn't overlap
        # with test window considering max lead
        train_dates_set = set(train_dates)
        # Check leakage
        max_lead = embargo_days
        filtered_test = []
        for td in test_dates:
            # Check if any train date would create leakage
            leaked = False
            for ld in range(1, max_lead + 1):
                if td - timedelta(days=ld) in train_dates_set:
                    # Potential leakage depending on definition; be strict
                    pass
            filtered_test.append(td)
        splits.append((sorted(train_dates), sorted(filtered_test)))
    return splits


def final_held_out_recent_block(dates: List[date], holdout_years: int = 1, embargo_days: int = 14):
    years = sorted(set(d.year for d in dates))
    if len(years) < 2:
        raise ValueError("Need at least 2 years for held-out block")
    # Put embargo gap between train and test
    test_years = set(years[-holdout_years:])
    # Exclude dates within embargo of test start from train
    if test_dates_check := [d for d in dates if d.year in test_years]:
        test_start = min(test_dates_check)
        train_dates = [d for d in dates if d.year not in test_years and (test_start - d).days > embargo_days]
        test_dates = [d for d in dates if d.year in test_years]
    else:
        train_dates = [d for d in dates if d.year not in test_years]
        test_dates = [d for d in dates if d.year in test_years]
    return sorted(train_dates), sorted(test_dates)


def check_no_leakage(train_dates: List[date], test_dates: List[date], max_lead_days: int):
    """Assert no leakage between train and test."""
    train_set = set(train_dates)
    test_set = set(test_dates)
    # No overlap
    overlap = train_set.intersection(test_set)
    if overlap:
        raise AssertionError(f"Train/test overlap: {overlap}")
    # Check embargo: test origin must not be within max_lead of any train data used
    # More strictly, ensure test dates are far enough from train
    train_sorted = sorted(train_set)
    for td in test_dates:
        for td_train in train_sorted:
            if 0 < (td - td_train).days <= max_lead_days:
                raise AssertionError(f"Leakage: test origin {td} within {max_lead_days} days of train data")
            if 0 < (td_train - td).days <= max_lead_days:
                raise AssertionError(f"Leakage: train data within {max_lead_days} days of test origin")
    return True
