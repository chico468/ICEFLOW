# Evaluation on real data (baselines only)

**Disclaimers:** Baselines only; no ML model has been evaluated on real data. Data source: real. Record length: 7305 days. Train years: [2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023], Test years: [2024].

**IIEE:** Goessling et al. 2016 definition, weighted by cell area (m^2 from projection areal scale), exclude land/missing from both, reported in million km^2.

**Domains:** RMSE/skill reported over all ocean cells AND over the variable-ice zone (climatology 5-95% on DOY). Headline is variable-ice zone.

**Sectors:** Weddell Sea (-60W to 20E), Indian Ocean (20E to 90E), Western Pacific (90E to 160E), Ross Sea (160E to 130W), Bellingshausen-Amundsen (130W to 60W). From src/eval/regions.py.

**Gaps:** Skipped origins/targets with missing data, no silent interpolation. n reported per table cell.

**Trend:** Climatology evaluated as 'climatology' (no trend) and 'climatology+trend' (linear, training years only).

**Leads:** 1, 3, 7, 14 days. All seasons + austral departure season (Nov-Mar).

**Method:** Leave-one-year-out cross-validation with a max-lead-day embargo on both sides of the held-out year (includes the final recent block).

## Headline results (sector-aggregated)

| domain | season | sector | baseline | lead | rmse | rmse_ci | mae | bias | iiee | n |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all_ocean | all | all | persistence | 1 | 0.0348 | [0.0318,0.0379] | 0.0092 | -0.0000 | 0.068 | 36520 |
| all_ocean | all | all | damped | 1 | 0.0351 | [0.0321,0.0384] | 0.0109 | -0.0000 | 0.068 | 36520 |
| all_ocean | all | all | climatology | 1 | 0.1172 | [0.1099,0.1243] | 0.0441 | 0.0000 | 0.445 | 36520 |
| all_ocean | all | all | climatology+trend | 1 | 0.1186 | [0.1113,0.1256] | 0.0442 | 0.0003 | 0.440 | 36520 |
| variable_ice_zone_5_95 | all | all | persistence | 1 | 0.0558 | [0.0516,0.0602] | 0.0241 | 0.0000 | 0.059 | 36520 |
| variable_ice_zone_5_95 | all | all | damped | 1 | 0.0564 | [0.0521,0.0608] | 0.0282 | 0.0000 | 0.059 | 36520 |
| variable_ice_zone_5_95 | all | all | climatology | 1 | 0.1901 | [0.1790,0.2005] | 0.1144 | 0.0002 | 0.405 | 36520 |
| variable_ice_zone_5_95 | all | all | climatology+trend | 1 | 0.1925 | [0.1815,0.2030] | 0.1146 | 0.0012 | 0.397 | 36520 |
| all_ocean | all | all | persistence | 3 | 0.0582 | [0.0524,0.0643] | 0.0164 | -0.0000 | 0.136 | 36510 |
| all_ocean | all | all | damped | 3 | 0.0567 | [0.0510,0.0627] | 0.0190 | -0.0000 | 0.138 | 36510 |
| all_ocean | all | all | climatology | 3 | 0.1172 | [0.1099,0.1243] | 0.0441 | 0.0000 | 0.445 | 36510 |
| all_ocean | all | all | climatology+trend | 3 | 0.1186 | [0.1113,0.1256] | 0.0442 | 0.0003 | 0.440 | 36510 |
| variable_ice_zone_5_95 | all | all | persistence | 3 | 0.0935 | [0.0854,0.1023] | 0.0430 | -0.0000 | 0.120 | 36510 |
| variable_ice_zone_5_95 | all | all | damped | 3 | 0.0912 | [0.0831,0.0998] | 0.0489 | 0.0000 | 0.122 | 36510 |
| variable_ice_zone_5_95 | all | all | climatology | 3 | 0.1901 | [0.1790,0.2005] | 0.1144 | 0.0002 | 0.405 | 36510 |
| variable_ice_zone_5_95 | all | all | climatology+trend | 3 | 0.1924 | [0.1815,0.2030] | 0.1146 | 0.0011 | 0.397 | 36510 |
| all_ocean | all | all | persistence | 7 | 0.0844 | [0.0767,0.0919] | 0.0248 | -0.0000 | 0.224 | 36490 |
| all_ocean | all | all | damped | 7 | 0.0767 | [0.0696,0.0841] | 0.0272 | -0.0000 | 0.247 | 36490 |
| all_ocean | all | all | climatology | 7 | 0.1172 | [0.1099,0.1243] | 0.0441 | 0.0000 | 0.445 | 36490 |
| all_ocean | all | all | climatology+trend | 7 | 0.1186 | [0.1113,0.1256] | 0.0442 | 0.0003 | 0.439 | 36490 |
| variable_ice_zone_5_95 | all | all | persistence | 7 | 0.1358 | [0.1234,0.1475] | 0.0648 | -0.0000 | 0.200 | 36490 |
| variable_ice_zone_5_95 | all | all | damped | 7 | 0.1235 | [0.1131,0.1342] | 0.0700 | 0.0000 | 0.223 | 36490 |
| variable_ice_zone_5_95 | all | all | climatology | 7 | 0.1901 | [0.1790,0.2005] | 0.1144 | 0.0002 | 0.405 | 36490 |
| variable_ice_zone_5_95 | all | all | climatology+trend | 7 | 0.1924 | [0.1815,0.2030] | 0.1146 | 0.0011 | 0.396 | 36490 |
| all_ocean | all | all | persistence | 14 | 0.1161 | [0.1045,0.1258] | 0.0360 | -0.0001 | 0.349 | 36455 |
| all_ocean | all | all | damped | 14 | 0.0940 | [0.0863,0.1010] | 0.0350 | 0.0000 | 0.346 | 36455 |
| all_ocean | all | all | climatology | 14 | 0.1172 | [0.1099,0.1244] | 0.0441 | 0.0000 | 0.445 | 36455 |
| all_ocean | all | all | climatology+trend | 14 | 0.1186 | [0.1113,0.1256] | 0.0442 | 0.0003 | 0.439 | 36455 |
| variable_ice_zone_5_95 | all | all | persistence | 14 | 0.1871 | [0.1690,0.2031] | 0.0936 | -0.0001 | 0.318 | 36455 |
| variable_ice_zone_5_95 | all | all | damped | 14 | 0.1516 | [0.1391,0.1623] | 0.0901 | 0.0001 | 0.315 | 36455 |
| variable_ice_zone_5_95 | all | all | climatology | 14 | 0.1901 | [0.1790,0.2006] | 0.1144 | 0.0002 | 0.405 | 36455 |
| variable_ice_zone_5_95 | all | all | climatology+trend | 14 | 0.1924 | [0.1815,0.2030] | 0.1146 | 0.0011 | 0.396 | 36455 |
| all_ocean | austral_departure | all | persistence | 1 | 0.0294 | [0.0259,0.0329] | 0.0067 | 0.0014 | 0.059 | 15120 |
| all_ocean | austral_departure | all | damped | 1 | 0.0297 | [0.0263,0.0330] | 0.0081 | -0.0000 | 0.059 | 15120 |
| all_ocean | austral_departure | all | climatology | 1 | 0.1125 | [0.0981,0.1263] | 0.0404 | 0.0000 | 0.461 | 15120 |
| all_ocean | austral_departure | all | climatology+trend | 1 | 0.1137 | [0.0998,0.1272] | 0.0403 | 0.0003 | 0.456 | 15120 |
| variable_ice_zone_5_95 | austral_departure | all | persistence | 1 | 0.0482 | [0.0427,0.0536] | 0.0178 | 0.0036 | 0.057 | 15120 |
| variable_ice_zone_5_95 | austral_departure | all | damped | 1 | 0.0486 | [0.0434,0.0538] | 0.0213 | -0.0000 | 0.057 | 15120 |
| variable_ice_zone_5_95 | austral_departure | all | climatology | 1 | 0.1850 | [0.1619,0.2073] | 0.1071 | -0.0000 | 0.452 | 15120 |
| variable_ice_zone_5_95 | austral_departure | all | climatology+trend | 1 | 0.1870 | [0.1647,0.2090] | 0.1069 | 0.0008 | 0.446 | 15120 |
| all_ocean | austral_departure | all | persistence | 3 | 0.0482 | [0.0404,0.0558] | 0.0124 | 0.0042 | 0.120 | 15110 |
| all_ocean | austral_departure | all | damped | 3 | 0.0464 | [0.0395,0.0533] | 0.0143 | -0.0000 | 0.119 | 15110 |
| all_ocean | austral_departure | all | climatology | 3 | 0.1125 | [0.0981,0.1263] | 0.0404 | 0.0000 | 0.460 | 15110 |
| all_ocean | austral_departure | all | climatology+trend | 3 | 0.1136 | [0.0997,0.1272] | 0.0402 | 0.0003 | 0.456 | 15110 |
| variable_ice_zone_5_95 | austral_departure | all | persistence | 3 | 0.0789 | [0.0666,0.0908] | 0.0327 | 0.0109 | 0.116 | 15110 |
| variable_ice_zone_5_95 | austral_departure | all | damped | 3 | 0.0761 | [0.0650,0.0869] | 0.0377 | -0.0000 | 0.114 | 15110 |
| variable_ice_zone_5_95 | austral_departure | all | climatology | 3 | 0.1850 | [0.1619,0.2073] | 0.1071 | -0.0000 | 0.452 | 15110 |
| variable_ice_zone_5_95 | austral_departure | all | climatology+trend | 3 | 0.1870 | [0.1646,0.2090] | 0.1069 | 0.0008 | 0.446 | 15110 |
| all_ocean | austral_departure | all | persistence | 7 | 0.0738 | [0.0586,0.0887] | 0.0208 | 0.0100 | 0.218 | 15090 |
| all_ocean | austral_departure | all | damped | 7 | 0.0653 | [0.0540,0.0759] | 0.0222 | -0.0000 | 0.213 | 15090 |
| all_ocean | austral_departure | all | climatology | 7 | 0.1125 | [0.0981,0.1263] | 0.0404 | 0.0000 | 0.460 | 15090 |
| all_ocean | austral_departure | all | climatology+trend | 7 | 0.1136 | [0.0997,0.1272] | 0.0402 | 0.0003 | 0.455 | 15090 |
| variable_ice_zone_5_95 | austral_departure | all | persistence | 7 | 0.1205 | [0.0966,0.1445] | 0.0546 | 0.0261 | 0.211 | 15090 |
| variable_ice_zone_5_95 | austral_departure | all | damped | 7 | 0.1067 | [0.0890,0.1239] | 0.0582 | -0.0000 | 0.205 | 15090 |
| variable_ice_zone_5_95 | austral_departure | all | climatology | 7 | 0.1850 | [0.1618,0.2073] | 0.1071 | -0.0000 | 0.452 | 15090 |
| variable_ice_zone_5_95 | austral_departure | all | climatology+trend | 7 | 0.1869 | [0.1646,0.2090] | 0.1068 | 0.0008 | 0.446 | 15090 |
| all_ocean | austral_departure | all | persistence | 14 | 0.1094 | [0.0858,0.1357] | 0.0341 | 0.0209 | 0.375 | 15055 |
| all_ocean | austral_departure | all | damped | 14 | 0.0842 | [0.0683,0.0985] | 0.0309 | 0.0000 | 0.326 | 15055 |
| all_ocean | austral_departure | all | climatology | 14 | 0.1125 | [0.0981,0.1263] | 0.0404 | 0.0000 | 0.460 | 15055 |
| all_ocean | austral_departure | all | climatology+trend | 14 | 0.1136 | [0.0997,0.1272] | 0.0402 | 0.0002 | 0.455 | 15055 |
| variable_ice_zone_5_95 | austral_departure | all | persistence | 14 | 0.1782 | [0.1409,0.2205] | 0.0890 | 0.0545 | 0.362 | 15055 |
| variable_ice_zone_5_95 | austral_departure | all | damped | 14 | 0.1377 | [0.1124,0.1609] | 0.0808 | -0.0000 | 0.315 | 15055 |
| variable_ice_zone_5_95 | austral_departure | all | climatology | 14 | 0.1850 | [0.1618,0.2073] | 0.1071 | -0.0000 | 0.452 | 15055 |
| variable_ice_zone_5_95 | austral_departure | all | climatology+trend | 14 | 0.1869 | [0.1645,0.2091] | 0.1068 | 0.0007 | 0.445 | 15055 |

## Per-sector breakdown (persistence, variable-ice zone, all seasons)

| domain | season | sector | baseline | lead | rmse | rmse_ci | mae | bias | iiee | n |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| variable_ice_zone_5_95 | all | Weddell Sea | persistence | 1 | 0.0480 | [0.0439,0.0519] | 0.0194 | -0.0000 | 0.077 | 7304 |
| variable_ice_zone_5_95 | all | Weddell Sea | persistence | 3 | 0.0843 | [0.0757,0.0925] | 0.0357 | -0.0000 | 0.162 | 7302 |
| variable_ice_zone_5_95 | all | Weddell Sea | persistence | 7 | 0.1278 | [0.1129,0.1431] | 0.0561 | -0.0001 | 0.284 | 7298 |
| variable_ice_zone_5_95 | all | Weddell Sea | persistence | 14 | 0.1842 | [0.1602,0.2100] | 0.0860 | -0.0003 | 0.472 | 7291 |
| variable_ice_zone_5_95 | all | Indian Ocean | persistence | 1 | 0.0514 | [0.0461,0.0573] | 0.0219 | 0.0000 | 0.057 | 7304 |
| variable_ice_zone_5_95 | all | Indian Ocean | persistence | 3 | 0.0863 | [0.0764,0.0969] | 0.0395 | 0.0000 | 0.114 | 7302 |
| variable_ice_zone_5_95 | all | Indian Ocean | persistence | 7 | 0.1257 | [0.1089,0.1428] | 0.0597 | -0.0000 | 0.191 | 7298 |
| variable_ice_zone_5_95 | all | Indian Ocean | persistence | 14 | 0.1778 | [0.1514,0.2065] | 0.0885 | -0.0000 | 0.311 | 7291 |
| variable_ice_zone_5_95 | all | Western Pacific | persistence | 1 | 0.0638 | [0.0589,0.0691] | 0.0302 | 0.0000 | 0.047 | 7304 |
| variable_ice_zone_5_95 | all | Western Pacific | persistence | 3 | 0.1010 | [0.0904,0.1120] | 0.0513 | 0.0000 | 0.088 | 7302 |
| variable_ice_zone_5_95 | all | Western Pacific | persistence | 7 | 0.1389 | [0.1246,0.1540] | 0.0731 | 0.0000 | 0.134 | 7298 |
| variable_ice_zone_5_95 | all | Western Pacific | persistence | 14 | 0.1822 | [0.1644,0.1978] | 0.0990 | -0.0000 | 0.195 | 7291 |
| variable_ice_zone_5_95 | all | Ross Sea | persistence | 1 | 0.0534 | [0.0495,0.0566] | 0.0230 | -0.0000 | 0.064 | 7304 |
| variable_ice_zone_5_95 | all | Ross Sea | persistence | 3 | 0.0909 | [0.0831,0.0970] | 0.0408 | -0.0000 | 0.130 | 7302 |
| variable_ice_zone_5_95 | all | Ross Sea | persistence | 7 | 0.1363 | [0.1241,0.1458] | 0.0632 | -0.0002 | 0.227 | 7298 |
| variable_ice_zone_5_95 | all | Ross Sea | persistence | 14 | 0.1929 | [0.1719,0.2137] | 0.0947 | -0.0004 | 0.370 | 7291 |
| variable_ice_zone_5_95 | all | Bellingshausen-Amundsen | persistence | 1 | 0.0625 | [0.0575,0.0678] | 0.0260 | 0.0000 | 0.051 | 7304 |
| variable_ice_zone_5_95 | all | Bellingshausen-Amundsen | persistence | 3 | 0.1052 | [0.0947,0.1161] | 0.0477 | 0.0000 | 0.104 | 7302 |
| variable_ice_zone_5_95 | all | Bellingshausen-Amundsen | persistence | 7 | 0.1503 | [0.1371,0.1650] | 0.0718 | 0.0001 | 0.166 | 7298 |
| variable_ice_zone_5_95 | all | Bellingshausen-Amundsen | persistence | 14 | 0.1985 | [0.1840,0.2136] | 0.0999 | 0.0000 | 0.241 | 7291 |
