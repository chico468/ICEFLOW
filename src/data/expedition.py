"""
The Indian Antarctic programme: who sails, when, to where, and under what law.

This module exists because the problem statement is not "route a ship through ice in general".
It is about the Indian Scientific Expedition to Antarctica, which has a specific fleet, a narrow
seasonal window, two stations that are resupplied in completely different ways, and a legal
framework that governs both. A route planner that ignores those constraints would produce
answers that are correct physics and useless operations.

Everything here is factual programme context, not model output, so it is not labelled synthetic.
Figures that are approximate or planned rather than published are marked in place.
"""
from __future__ import annotations

from typing import Any, Dict, List

# --------------------------------------------------------------------------------------
# Institutional and legal framing
# --------------------------------------------------------------------------------------
PROGRAMME: Dict[str, Any] = {
    "name": "Indian Scientific Expedition to Antarctica (ISEA)",
    "since": 1981,
    "ministry": "Ministry of Earth Sciences (MoES)",
    "nodal_agency": "National Centre for Polar and Ocean Research (NCPOR)",
    "agency_location": "Headland Sada, Vasco da Gama, Goa",
    "legal_framework": [
        {
            "instrument": "Indian Antarctic Act, 2022",
            "relevance": (
                "Domestic law governing Indian activity in Antarctica. Requires a permit for "
                "vessel operations and imposes environmental obligations that a route planner "
                "has to respect, not merely note."
            ),
        },
        {
            "instrument": "Antarctic Treaty and the Protocol on Environmental Protection",
            "relevance": (
                "Antarctic Specially Protected Areas must be avoided or entered only under "
                "permit; minimising time spent operating in them is a planning objective."
            ),
        },
        {
            "instrument": "IMO Polar Code (MSC.385(94)) and POLARIS (MSC.1/Circ.1519)",
            "relevance": (
                "Sets the operational limits this system enforces as a hard constraint: a route "
                "may not be recommended through ice where POLARIS prohibits operation."
            ),
        },
        {
            "instrument": "IMO Polar Code heavy fuel oil provisions",
            "relevance": (
                "Antarctic operations run on marine gas oil. The fuel and emissions model in "
                "this system is MGO throughout, at 3.206 kg CO2 per kg fuel."
            ),
        },
    ],
}

# --------------------------------------------------------------------------------------
# The season. This is the constraint most easily overlooked: the window is narrow, and a
# forecast that saves two days in February is worth far more than one that saves two in June,
# because in June no ship is going.
# --------------------------------------------------------------------------------------
SEASON: Dict[str, Any] = {
    "window": "Austral summer, roughly December to March",
    "typical_departure": "Late November to December, from Cape Town or Goa",
    "station_relief": "December to February, when the fast ice breaks out",
    "latest_safe_return": "Early March, before the pack re-forms",
    "why_it_matters": (
        "The sailing window is about 90 days. Days saved inside it are days of science, and days "
        "lost can mean a station goes unrelieved for a year, so transit time is the metric that "
        "matters most to this programme - more than fuel."
    ),
    # The environment model's reference date is 26 November: the southbound departure, not the
    # February ice minimum. That is deliberate. Late November is when the pack is still extensive
    # and the routing problem is hardest, so it is the honest case to demonstrate. Planning
    # against the February minimum would flatter the system by giving it easier ice.
    "model_reference_date": "26 November (day 330), the southbound departure",
    "model_reference_day_of_year": 330,
    "why_that_date": (
        "Late November is the hard case: the ice edge sits near 60 S and the pack has not yet "
        "retreated. Choosing the February minimum instead would make every route look easier "
        "than it is."
    ),
}

# --------------------------------------------------------------------------------------
# How the two stations are actually supplied. They could hardly be more different, and the
# difference is why each destination carries a separate navigable anchorage.
# --------------------------------------------------------------------------------------
RESUPPLY_OPERATIONS: List[Dict[str, Any]] = [
    {
        "station": "Maitri Station",
        "sector": "Queen Maud Land, Princess Astrid Coast",
        "approach": "India Bay",
        "method": "Shelf-ice edge offloading followed by an overland traverse",
        "constraint": (
            "Maitri is roughly 80 km inland on the Schirmacher Oasis. No ship can reach it. "
            "Cargo is landed on the shelf ice and hauled inland by convoy, so the planner routes "
            "to the ice edge and the last leg is not a marine problem at all."
        ),
        "air_link": "Novolazarevskaya (Novo) runway, shared with the Russian programme",
    },
    {
        "station": "Bharati Station",
        "sector": "Larsemann Hills, Prydz Bay",
        "approach": "Quilty Bay and the Prydz Bay fast-ice edge",
        "method": "Working the fast-ice edge, with helicopter and over-ice transfer",
        "constraint": (
            "Bharati is coastal, but Prydz Bay carries heavy fast ice and the Amery Ice Shelf "
            "calves large tabular bergs directly into the approach. Reaching the anchorage is a "
            "genuine ice-navigation problem, which is why it is the default demonstration leg."
        ),
        "neighbours": "Progress (Russia), Zhongshan (China) and Davis (Australia) are close by",
    },
]

# --------------------------------------------------------------------------------------
# The fleet, and the gap in it.
# --------------------------------------------------------------------------------------
FLEET_NOTE: Dict[str, Any] = {
    "current_practice": (
        "NCPOR charters ice-class tonnage for the expedition, most often MV Vasiliy Golovnin. "
        "India's own ORV Sagar Nidhi, operated by NIOT, became the first Indian-owned vessel to "
        "reach Antarctica in 2010, but she is ice-strengthened for roughly 40 cm of ice rather "
        "than ice-breaking."
    ),
    "the_gap": (
        "India has no dedicated polar research vessel. This system lets the consequence be "
        "measured rather than argued: plan the same passage with each hull and compare where "
        "the planner refuses to go. In 1.5 m ice at 6/10 concentration, Sagar Nidhi cannot make "
        "way at all, the chartered Golovnin manages about 2.6 knots, and a notional PC4 polar "
        "research vessel manages about 4.2. That difference is the business case, in physics."
    ),
    "vessel_keys": ["vasiliy_golovnin", "sagar_nidhi", "arc7_resupply", "polar_research_vessel"],
}


def programme_context() -> Dict[str, Any]:
    """Everything above, for the API and the interface."""
    return {
        "programme": PROGRAMME,
        "season": SEASON,
        "resupply_operations": RESUPPLY_OPERATIONS,
        "fleet": FLEET_NOTE,
        "is_synthetic": False,
        "source": "Published programme, institutional and regulatory context; not model output.",
    }
