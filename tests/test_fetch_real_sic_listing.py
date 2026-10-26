from datetime import date

from scripts import fetch_real_sic


def test_listing_parsed_into_date_filename_map():
    html_2005 = 'href="sic_pss25_20050101_F13_v06r00.nc"'
    html_2015 = 'href="sic_pss25_20150101_F17_v06r00.nc"'
    html_2025 = 'href="sic_pss25_20250101_am2_v06r00.nc"'
    listings = {2005: html_2005, 2015: html_2015, 2025: html_2025}
    date_to_filename = fetch_real_sic.collect_listing_filenames(listings)
    assert date_to_filename[date(2005, 1, 1)] == "sic_pss25_20050101_F13_v06r00.nc"
    assert date_to_filename[date(2015, 1, 1)] == "sic_pss25_20150101_F17_v06r00.nc"
    assert date_to_filename[date(2025, 1, 1)] == "sic_pss25_20250101_am2_v06r00.nc"


def test_dates_not_in_listing_are_gaps():
    # Listing only has Jan 1 and Jan 3; Jan 2 is missing.
    html = (
        'href="sic_pss25_20240101_am2_v06r00.nc"\n'
        'href="sic_pss25_20240103_am2_v06r00.nc"'
    )
    date_to_filename = fetch_real_sic.collect_listing_filenames({2024: html})
    requested = fetch_real_sic.requested_date_range(date(2024, 1, 1), date(2024, 1, 3))
    gaps = fetch_real_sic.find_gaps(date_to_filename, requested)
    assert date(2024, 1, 2) in gaps
    assert date(2024, 1, 1) not in gaps
    assert date(2024, 1, 3) not in gaps


def test_no_silent_filename_fallback():
    # A date absent from the listing must NOT be silently assigned a guessed
    # filename; download_file relies solely on the listing map (KeyError if missing).
    date_to_filename = {date(2024, 1, 1): "sic_pss25_20240101_am2_v06r00.nc"}
    missing = date(2024, 1, 2)
    assert missing not in date_to_filename
    requested = fetch_real_sic.requested_date_range(date(2024, 1, 1), date(2024, 1, 2))
    gaps = fetch_real_sic.find_gaps(date_to_filename, requested)
    assert gaps == [missing]


def test_date_to_filename_map_across_sensor_change():
    # Simulated listings across the F13 / F17 / am2 sensor transitions.
    html_2005 = 'href="sic_pss25_20050101_F13_v06r00.nc"'
    html_2015 = 'href="sic_pss25_20150101_F17_v06r00.nc"'
    html_2025 = 'href="sic_pss25_20250101_am2_v06r00.nc"'
    listings = {2005: html_2005, 2015: html_2015, 2025: html_2025}
    date_to_filename = fetch_real_sic.collect_listing_filenames(listings)
    assert date_to_filename[date(2005, 1, 1)].endswith("_F13_v06r00.nc")
    assert date_to_filename[date(2015, 1, 1)].endswith("_F17_v06r00.nc")
    assert date_to_filename[date(2025, 1, 1)].endswith("_am2_v06r00.nc")
    requested = [date(2005, 1, 1), date(2010, 1, 1), date(2015, 1, 1), date(2024, 1, 1)]
    gaps = fetch_real_sic.find_gaps(date_to_filename, requested)
    assert set(gaps) == {date(2010, 1, 1), date(2024, 1, 1)}
