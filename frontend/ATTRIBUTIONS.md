# ATTRIBUTIONS — Third-party libraries and assets

This file catalogues every external library and asset bundled with the ICEFLOW
frontend, with its source URL, author, licence and date of verification. It is
maintained per the Stage C honesty requirement: every bundled asset is listed
here with its licence, and no asset over 5 MB is bundled.

## Libraries (bundled via npm)

| Library | Source | Author | Licence | Version | Date verified |
|---------|--------|--------|---------|---------|---------------|
| three | https://github.com/mrdoob/three.js/ | mrdoob | MIT | ^0.160.1 | 2026-11-01 |
| @react-three/fiber | https://github.com/pmndrs/react-three-fiber | pmndrs | MIT | ^8.18.0 | 2026-11-01 |
| @react-three/drei | https://github.com/pmndrs/drei | pmndrs | MIT | ^9.122.0 | 2026-11-01 |
| react | https://react.dev/ | Meta | MIT | ^18.3.1 | 2026-11-01 |
| react-dom | https://react.dev/ | Meta | MIT | ^18.3.1 | 2026-11-01 |
| mapbox-gl | https://github.com/mapbox/mapbox-gl-js | Mapbox | BSD-3-Clause | ^3.33.0 | 2026-11-01 |
| zustand | https://github.com/pmndrs/zustand | pmndrs | MIT | ^4.5.5 | 2026-11-01 |
| @tanstack/react-query | https://tanstack.com/query/latest | TanStack | MIT | ^5.59.0 | 2026-11-01 |
| lucide-react | https://lucide.dev/ | Lucide contributors | ISC | ^0.454.0 | 2026-11-01 |
| recharts | https://recharts.org/ | Recharts contributors | MIT | ^2.13.0 | 2026-11-01 |

## 3D ship asset (Stage C)

Three searches were performed for a CC0/CC-BY icebreaker or research-vessel glTF
(Poly Pizza, Quaternius, Kenney, Sketchfab downloadable):

| # | Source | Author | Licence | File size | Date verified | Decision |
|---|--------|--------|---------|-----------|---------------|----------|
| 1 | https://www.innerscene.com/tools/library/3d-parts/research-vessel-c43c97fe | Innerscene (original model) | CC0 (public domain) | 4.4 MB | 2026-11-01 | Not downloaded — direct .glb file URL not obtainable from the library page (only "Download GLB" button); kept as reference |
| 2 | https://poly.pizza/m/mEQj2wZ3GC | Quaternius | CC0 (public domain) | Not measured (page only) | 2026-11-01 | Not downloaded — direct glTF file URL not extracted from Poly Pizza page; kept as reference |
| 3 | https://github.com/Papyszoo/CC0-Public-Domain-Models/blob/main/packs/kenney-watercraft-kit/models/ship_cargo_a/ship_cargo_a.glb | Kenney (watercraft kit) | CC0 (public domain) | 106,856 bytes (~104 KB) | 2026-11-01 | **Downloaded and used** — valid glTF v2, under 5 MB, clearly CC0 licensed |

Decision: The Kenney watercraft-ship glTF (search 3) was downloaded into
`frontend/public/models/ship.glb` (106,856 bytes, valid glTF binary version 2,
CC0 licensed, under the 5 MB limit) and is used as the ship mesh with a
procedural-hull fallback if the load fails. The Innerscene research vessel and
Quaternius ship were searched but not bundled because a direct, downloadable
file URL could not be obtained from their library pages.

No Sketchfab model was downloaded: the icebreaker models found on Sketchfab did
not display a clear CC0/CC-BY licence in the search results (licence field blank
or unspecified), so they do not meet the "clearly licensed" requirement.

## Attribution text (for display)

The bundled ship mesh is derived from Kenney's Watercraft Kit
(https://kenney.nl/assets/watercraft-kit), released under CC0 1.0 Universal
(public domain, no attribution required). Bundled via the
CC0-Public-Domain-Models mirror
(https://github.com/Papyszoo/CC0-Public-Domain-Models).

All other 3D content (ocean shader, sky dome, ice floes, procedural-hull
fallback) is generated in code and carries no third-party attribution.
