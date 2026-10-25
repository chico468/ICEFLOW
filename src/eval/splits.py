"""Leakage-proof splits for time series evaluation."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Tuple


def leave_one_year_out(dates: List[date], embargo_days: int = 14) -> List[Tuple[List[date], List[date]]]:
    """Leave-one-year-out splits with embargo between train and test."""
    years = sorted(set(d.year for d in dates))
    splits_list = []
    for test_year in years:
        test_dates = [d for d in dates if d.year == test_year]
        test_start = min(test_dates) if test_dates else None
        if test_start:
            train_dates = [d for d in dates if d.year != test_year and (test_start - d).days > embargo_days]
        else:
            train_dates = [d for d in dates if d.year != test_year]
        check_no_leakage(train_dates, test_dates, embargo_days)
        splits_list.append((sorted(train_dates), sorted(test_dates)))
    return splits_list


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
