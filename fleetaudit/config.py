"""Policy thresholds and scoring weights.

Every threshold the SQL rules use lives here. `db.load` writes the policy into
one-row tables, so the SQL in sql/03_rules.sql never hard-codes a number.
All values are invented for this simulation.
"""
from dataclasses import asdict, dataclass, field
from datetime import date

AS_OF = date(2026, 6, 30)
ORIG_START = date(2023, 7, 1)
ORIG_END = date(2026, 3, 31)

# tier -> (minimum commercial credit score, rank, maximum advance as share of invoice)
TIERS = {
    "A": (720, 1, 1.25),
    "B": (680, 2, 1.20),
    "C": (640, 3, 1.15),
    "D": (600, 4, 1.10),
}

LOAN_TERMS = (36, 48, 60, 72)
LEASE_TERMS = (24, 36, 48)


@dataclass(frozen=True)
class Policy:
    markup_cap_loan_bps: int = 200        # dealer reserve over buy rate, retail-style loans
    markup_cap_lease_bps: int = 100
    markup_cap_program_bps: int = 0       # subvented programs: no dealer markup
    addon_cap: float = 0.15               # add-ons as share of cash price
    price_cap: float = 1.02               # cash price as share of MSRP
    residual_tolerance_pp: float = 1.0    # booked residual vs residual table
    high_mileage_km: int = 40_000         # above this, residual table is reduced
    high_mileage_adj_pp: float = -3.0
    payment_tolerance_abs: float = 2.0    # MXN
    payment_tolerance_pct: float = 0.0025
    split_window_days: int = 7
    split_near_limit: float = 0.70        # deal at >= 70% of approver authority
    slow_split_window_days: int = 30      # wider net for splits spread over weeks
    backdate_lag_days: int = 15           # entry later than contract date by more than this
    backdate_rate_gain: float = 0.25      # rate-sheet move that makes backdating pay
    epd_min_seasoned: int = 12            # dealer needs this many seasoned contracts
    epd_ratio: float = 2.0                # Wilson lower bound vs portfolio EPD rate
    epd_min_count: int = 3
    override_min_level: int = 3           # tier overrides need an L3+ approver
    as_of: date = AS_OF

    def row(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Scoring:
    points: dict = field(default_factory=lambda: {
        "R01": 25,   # markup over cap
        "R02": 25,   # residual above table
        "R03": 20,   # payment does not reconcile (25 when understated)
        "R04": 30,   # split deal under approval authority
        "R05": 40,   # VIN financed twice while first contract open
        "R06": 20,   # advance over policy (+10 per extra breach)
        "R07": 25,   # incentive outside its program
        "R08": 25,   # credit tier better than score, no valid override
        "R09": 30,   # backdated contract that captured a benefit
        "R10": 30,   # customer over exposure limit at funding
        "R12": 30,   # deal above approver authority
        "R13": 35,   # VIN one character away from an open contract
        "R14": 15,   # near-limit deals spread over a month (weak signal, review only)
    })
    understated_payment_points: int = 25
    extra_advance_breach_points: int = 10
    outlier_points: int = 10              # statistical layer, top share of contracts
    outlier_share: float = 0.01
    medium: int = 25
    high: int = 50
    dealer_epd_points: int = 40


POLICY = Policy()
SCORING = Scoring()
