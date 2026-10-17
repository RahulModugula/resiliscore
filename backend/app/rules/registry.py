"""Registry of discount mandates, grants, caps and regulations that bear on a parcel's premium.

Every entry carries its source URL and the date that source was read. `verified` is True only when the
figure was read in a primary or official document; otherwise it is False and `note` says what is missing.
Read 2026-10-17.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

RuleType = Literal["DISCOUNT_MANDATE", "GRANT", "CAP", "REGULATION"]


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    jurisdiction: str
    type: RuleType
    summary: str
    amount_or_range: str
    effective_date: str | None
    source_url: str
    source_date: str
    verified: bool
    note: str = ""


_READ = "2026-10-17"

RULES: tuple[Rule, ...] = (
    Rule(
        id="CA_CCR_2644_9",
        jurisdiction="CA",
        type="DISCOUNT_MANDATE",
        summary=(
            "Insurers that use wildfire risk in rating must file a discount for each listed community, "
            "immediate-surroundings and structure mitigation factor, and disclose each measure's premium effect."
        ),
        amount_or_range="Regulation sets no percentage; CDI reports company discounts of about 4% to over 40%",
        effective_date="2022-10-01",
        source_url="https://www.law.cornell.edu/regulations/california/10-CCR-2644.9",
        source_date=_READ,
        verified=True,
        note=(
            "Regulation text read at the source URL. The 4%-40% range is from the CDI wildfire briefing of "
            "2026-03-27 (https://www.insurance.ca.gov/0400-news/0100-press-releases/2026/upload/"
            "nr017CDIWildfireSafetyandInsurabilityBriefing032720262-2.pdf), seen in a search snippet "
            "and not opened in full."
        ),
    ),
    Rule(
        id="CA_FAIR_PLAN_WILDFIRE_CAP",
        jurisdiction="CA",
        type="CAP",
        summary="FAIR Plan wildfire-hardening discounts (up to 12 measures) are capped on the wildfire portion of premium.",
        amount_or_range="Up to 16.4% off the wildfire portion of a Dwelling Fire premium",
        effective_date="2025-11-15",
        source_url="https://www.cfpnet.com/wp-content/uploads/2025/11/Wildfire-Hardening-Discounts-for-Dwelling-Fire-Commercial-Policies-2025.11.15.pdf",
        source_date=_READ,
        verified=True,
        note=(
            "16.4% is the figure in the FAIR Plan's own discount document (seen in a search snippet). Separate "
            "2025 CDI releases say up to 20%; the two were not reconciled."
        ),
    ),
    Rule(
        id="LA_FORTIFY_HOMES_GRANT",
        jurisdiction="LA",
        type="GRANT",
        summary="Louisiana Fortify Homes grants for an IBHS FORTIFIED Roof on an owner-occupied single-family home.",
        amount_or_range="Up to $10,000",
        effective_date=None,
        source_url="https://www.wafb.com/2026/09/24/louisiana-homeowners-could-qualify-up-49-hurricane-insurance-discount/",
        source_date=_READ,
        verified=True,
        note=(
            "Grant cap confirmed by several news sources. Application rounds are lotteries and the latest "
            "registration window seen closed 2026-06-19, so check ldi.la.gov/fortifyhomes for the next round."
        ),
    ),
    Rule(
        id="LA_REG_136",
        jurisdiction="LA",
        type="DISCOUNT_MANDATE",
        summary=(
            "Regulation 136 (Bulletin 2026-04, issued 2026-04-29): insurers must discount the hurricane portion of "
            "the premium for FORTIFIED homes, by zone and designation, on new and renewed policies."
        ),
        amount_or_range=(
            "South/Central/North: Roof 29/27/16%, Silver 43/35/20%, Gold 49/42/24% of the hurricane portion"
        ),
        effective_date="2027-01-01",
        source_url="https://www.insurancejournal.com/news/southcentral/2026/03/10/861210.htm",
        source_date=_READ,
        verified=True,
        note=(
            "Table read in Insurance Journal (2026-03-10); the bulletin date comes from "
            "https://www.insurancebusinessmag.com/us/news/risk-compliance-legal/"
            "louisiana-orders-every-property-insurer-to-discount-fortified-homes-by-january-2027-575095.aspx. "
            "The bulletin itself (ldi.la.gov/fortifiedbenchmarks) was not opened."
        ),
    ),
    Rule(
        id="LA_SB_355",
        jurisdiction="LA",
        type="DISCOUNT_MANDATE",
        summary="Reported 20% minimum FORTIFIED discount.",
        amount_or_range="20% minimum (reported)",
        effective_date=None,
        source_url="https://www.insurancebusinessmag.com/us/news/risk-compliance-legal/louisiana-orders-every-property-insurer-to-discount-fortified-homes-by-january-2027-575095.aspx",
        source_date=_READ,
        verified=False,
        note="No source confirming SB 355 or a 20% floor was found; Regulation 136 is the confirmed mandate.",
    ),
    Rule(
        id="AL_STRENGTHEN_ALABAMA_HOMES",
        jurisdiction="AL",
        type="GRANT",
        summary="Strengthen Alabama Homes pays for wind-resistance upgrades to FORTIFIED Roof or Silver on owner-occupied single-family homes.",
        amount_or_range="100% of the mitigation cost, up to $10,000",
        effective_date=None,
        source_url="https://strengthenalabamahomes.com/",
        source_date=_READ,
        verified=True,
        note=(
            "Grant cap quoted from the program site. Eligible counties change by round. Alabama's FORTIFIED "
            "premium-discount percentages were not verified."
        ),
    ),
    Rule(
        id="NY_DFS_CL_2024_07",
        jurisdiction="NY",
        type="REGULATION",
        summary=(
            "Insurers using AI systems or external consumer data in underwriting and pricing must govern them, "
            "test for unfair discrimination, document them, supervise vendors and disclose adverse decisions."
        ),
        amount_or_range="Not applicable",
        effective_date="2024-07-11",
        source_url="https://www.dfs.ny.gov/industry-guidance/circular-letters/cl2024-07",
        source_date=_READ,
        verified=True,
        note="Title, date and scope read at the source; the specific obligations come from the coordinator's summary.",
    ),
)

_BY_ID = {r.id: r for r in RULES}


def get(rule_id: str) -> Rule:
    return _BY_ID[rule_id]


def by_jurisdiction(state: str) -> list[Rule]:
    return [r for r in RULES if r.jurisdiction == state]


def ids() -> list[str]:
    return list(_BY_ID)
