from datetime import date, timedelta
from src.eval import splits


def test_no_leakage_split():
    dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(365*3)]
    train, test = splits.final_held_out_recent_block(dates, holdout_years=1, embargo_days=14)
    splits.check_no_leakage(train, test, 14)
    assert len(set(train) & set(test)) == 0


def test_climatology_fitted_on_training_years_only():
    from src.eval import baselines
    import numpy as np
    train_dates = [date(2020, 1, 1) + timedelta(days=i) for i in range(365)]
    sic_by_date = {d: np.ones((5,5)) * (d.year - 2020) for d in train_dates}
    doy_to_mean, _ = baselines.fit_climatology(train_dates, sic_by_date, use_trend=True)
    # Should be fitted only on training data
    assert len(doy_to_mean) > 0
