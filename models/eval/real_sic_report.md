# Evaluation on real data (baselines only)

**Disclaimers:** Baselines only; no ML model has been evaluated on real data. Data source: fixtures. Record length: 800 days. Train years: [2023, 2024], Test years: [2025].

**IIEE:** Goessling et al. 2016 definition, weighted by cell area (m^2 from grid spacing), exclude land/missing from both, reported in million km^2.

**Domains:** RMSE/skill reported over all ocean cells AND over variable-ice zone (climatology 5-95% on DOY). Headline is variable-ice zone.

**Sectors:** Weddell Sea (-60W to 20E), Indian Ocean (20E to 90E), Western Pacific (90E to 160E), Ross Sea (160E to 130W), Bellingshausen-Amundsen (130W to 60W). Bharati (Prydz Bay) is in Indian Ocean sector; Maitri approach (~12E) is in Weddell sector.

**Gaps:** Skipped origins/targets with missing data, no silent interpolation. n reported per table cell.

**Trend:** Climatology evaluated with and without linear trend (fit on training years only). 2016-2023 regime change makes extrapolated trends unreliable.

**Leads:** 1, 3, 7, 14 days. All seasons + austral departure season (Nov-Mar).

