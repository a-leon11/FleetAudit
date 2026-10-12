"""Synthetic dealer fleet-contract book with planted anomalies.

Everything here is invented: dealers, customers, vehicle models, rate sheets,
programs and policy limits. The generator builds a clean background book that
follows policy, plants known anomaly patterns plus look-alikes that are legal,
and writes the answer key to ground_truth.json so detection can be scored.

Only `random.Random` is used, so a seed reproduces the same book anywhere.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from random import Random

from . import finance as fin
from .config import AS_OF, LEASE_TERMS, LOAN_TERMS, ORIG_END, ORIG_START, POLICY, TIERS

# ---------------------------------------------------------------- catalogue
MODELS = [  # code, segment, MSRP for model year 2024 (MXN)
    ("SDN-C1", "compact_sedan", 342_000),
    ("SDN-C2", "compact_sedan", 398_000),
    ("SUV-M1", "midsize_suv", 689_000),
    ("PKP-L1", "half_ton_pickup", 724_000),
    ("PKP-L2", "half_ton_pickup", 861_000),
    ("PKP-H1", "heavy_pickup", 1_084_000),
    ("VAN-C1", "cargo_van", 879_000),
    ("CHS-C1", "chassis_cab", 1_152_000),
    ("EVN-C1", "electric_van", 1_418_000),
]
MODEL_YEARS = range(2023, 2028)
RESIDUAL_36 = {"compact_sedan": 42, "midsize_suv": 50, "half_ton_pickup": 52,
               "heavy_pickup": 50, "cargo_van": 45, "chassis_cab": 44, "electric_van": 38}
RESIDUAL_TERM_ADJ = {24: 8, 36: 0, 48: -7}
TIER_SPREAD = {"A": 0.0, "B": 1.5, "C": 3.25, "D": 5.5}
TERM_ADJ = {24: -0.2, 36: 0.0, 48: 0.35, 60: 0.7, 72: 1.1}

INDUSTRIES = {
    "logistics": (["Transportes", "Logística", "Fletes"], ["VAN-C1", "PKP-H1", "CHS-C1", "EVN-C1"], 0.30),
    "construction": (["Constructora", "Obras y Proyectos"], ["PKP-H1", "PKP-L2", "CHS-C1"], 0.25),
    "utilities": (["Servicios Eléctricos", "Redes"], ["PKP-L1", "PKP-L2", "VAN-C1"], 0.35),
    "rental": (["Arrendadora", "Renta de Autos"], ["SDN-C1", "SDN-C2", "SUV-M1"], 0.60),
    "field_services": (["Servicios Técnicos", "Mantenimiento"], ["PKP-L1", "VAN-C1", "SDN-C2"], 0.45),
    "agribusiness": (["Agroindustrias", "Granjas"], ["PKP-L1", "PKP-H1", "PKP-L2"], 0.20),
    "distribution": (["Distribuidora", "Comercializadora"], ["VAN-C1", "EVN-C1", "SDN-C1"], 0.35),
}
CUSTOMER_WORDS = ["Vega Roja", "Peñasco", "Alborada", "Tres Ríos", "Cañada Fría", "Lomas Grises",
                  "Puerto Viejo", "Arroyo Seco", "Mesa Blanca", "Cerro Prieto", "Las Ánimas",
                  "Bajío Verde", "Encinal", "Sabinal", "Palo Blanco", "Media Luna", "Rincón Hondo",
                  "Agua Clara", "Tierra Alta", "Los Pinos Dos", "Piedra Larga", "Ojo de Agua",
                  "La Cumbrera", "San Lorenzo Norte", "Costa Brava", "El Mezquital", "Nogalera"]
DEALER_PREFIX = ["Grupo Automotriz", "Autos", "Motores", "Camiones", "Flotillas",
                 "Distribuidora Automotriz", "Agencia"]
DEALER_WORDS = ["Cerro Azul", "Río Bravo", "Sierra Alta", "Valle Real", "Puerta Norte", "Mesa Larga",
                "Ciprés", "Laguna Seca", "Bahía Clara", "Altamira Sur", "Los Robles", "Cumbres",
                "Mirador", "Huasteca", "Encino", "Paso Ancho", "Lomas del Sol", "Arcos"]
REGIONS = {
    "Noreste": ["Monterrey", "Saltillo", "Reynosa"],
    "Norte": ["Chihuahua", "Hermosillo", "Torreón"],
    "Centro": ["Ciudad de México", "Querétaro", "Puebla"],
    "Occidente": ["Guadalajara", "León"],
    "Sureste": ["Mérida", "Villahermosa"],
}
APPROVERS = [  # id, level, authority (MXN)
    ("AP-01", 1, 2_500_000), ("AP-02", 1, 2_500_000), ("AP-03", 1, 2_500_000), ("AP-04", 1, 2_500_000),
    ("AP-05", 2, 6_000_000), ("AP-06", 2, 6_000_000), ("AP-07", 2, 6_000_000),
    ("AP-08", 3, 15_000_000), ("AP-09", 3, 15_000_000),
    ("AP-10", 4, 250_000_000),
]
VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
OVERRIDE_CODES = ["FLEET_HISTORY", "GUARANTOR", "CASH_COLLATERAL"]


@dataclass
class Contract:
    key: int
    deal_key: int
    dealer_id: str
    customer_id: str
    approver_id: str
    product: str
    model_code: str
    model_year: int
    vin: str
    contract_date: date
    entered_at: date
    funded_date: date
    term_months: int
    cash_price: float
    down_payment: float
    addons: float
    amount_financed: float
    residual_pct: float | None
    residual_value: float | None
    annual_km: int | None
    credit_score: int
    credit_tier: str
    override_code: str | None
    buy_rate: float
    contract_rate: float
    program_id: str | None
    subvention_mxn: float
    monthly_payment: float
    status: str = "ACTIVE"
    close_date: date | None = None
    force: tuple | None = None          # forced performance, e.g. ("good",) or ("termination", 9)


@dataclass
class Customer:
    customer_id: str
    name: str
    industry: str
    region: str
    base_score: int
    weight: float
    dealers: list[str]
    onboarded: date | None = None


class Book:
    def __init__(self, seed: int, n_months_deals: tuple[int, int] = (16, 24)):
        self.rng = Random(seed)
        self.seed = seed
        self.deal_range = n_months_deals
        self.contracts: list[Contract] = []
        self.deals: dict[int, list[Contract]] = {}
        self.vins: set[str] = set()
        self.deal_dates: dict[tuple[str, str], list[date]] = {}
        self.planted: set[int] = set()
        self.truth: dict = {"contracts": {}, "dealers": {}, "customers": {}, "lookalikes": {}}
        self._next_key = 0
        self._next_deal = 0
        self._build_reference()

    # ------------------------------------------------------------ reference
    def _build_reference(self) -> None:
        r = self.rng
        self.catalog = {}
        for code, seg, base in MODELS:
            for y in MODEL_YEARS:
                msrp = round(base * 1.045 ** (y - 2024), -2)
                self.catalog[(code, y)] = (seg, msrp, round(msrp * r.uniform(0.915, 0.945), -2))
        self.segment = {code: seg for code, seg, _ in MODELS}

        self.residual_table = {(seg, t): RESIDUAL_36[seg] + RESIDUAL_TERM_ADJ[t]
                               for seg in RESIDUAL_36 for t in LEASE_TERMS}

        # month-by-month base rate: a policy-rate style walk in quarter-point steps
        self.months = []
        d = date(2023, 1, 1)
        while d <= AS_OF:
            self.months.append(d)
            d = fin.add_months(d, 1)
        base, self.base_rate = 11.0, {}
        for m in self.months:
            base = min(14.0, max(9.0, base + r.choice([-0.25, 0, 0, 0, 0.25, 0.5])))
            self.base_rate[m] = base
        self.sheet = {(m, t, term): round(self.base_rate[m] + TIER_SPREAD[t] + TERM_ADJ[term], 2)
                      for m in self.months for t in TIERS for term in TERM_ADJ}

        # manufacturer incentive programs
        self.programs = []
        starts = sorted(ORIG_START + timedelta(days=r.randint(0, (ORIG_END - ORIG_START).days - 150))
                        for _ in range(8))
        for i, s in enumerate(starts, 1):
            e = s + timedelta(days=r.randint(60, 120))
            models = r.sample([m[0] for m in MODELS], r.randint(1, 3))
            self.programs.append({"program_id": f"PRG-{i:02d}", "name": f"Programa Flotilla {i:02d}",
                                  "start_date": s, "end_date": e,
                                  "program_rate": r.choice([3.9, 5.9, 7.9, 8.9]),
                                  "max_term": r.choice([36, 48]), "models": sorted(models)})

        self.approvers = {a: (lvl, auth) for a, lvl, auth in APPROVERS}

        # dealers
        names = r.sample([f"{p} {w}" for p in DEALER_PREFIX for w in DEALER_WORDS], 41)
        self.dealers = {}
        regions = list(REGIONS)
        for i, name in enumerate(names, 1):
            reg = regions[(i - 1) % len(regions)]
            self.dealers[f"D-{i:02d}"] = {"name": name, "region": reg, "city": r.choice(REGIONS[reg]),
                                          "weight": r.lognormvariate(0, 0.6), "onboarded": None}
        self.small_dealer = "D-41"                     # only used by a look-alike
        self.dealers[self.small_dealer]["weight"] = 0.0

        # customers
        self.customers: dict[str, Customer] = {}
        used = set()
        for i in range(1, 221):
            ind = r.choice(list(INDUSTRIES))
            while True:
                name = f"{r.choice(INDUSTRIES[ind][0])} {r.choice(CUSTOMER_WORDS)} S.A. de C.V."
                if name not in used:
                    used.add(name)
                    break
            reg = r.choice(regions)
            local = [d for d, v in self.dealers.items() if v["region"] == reg and v["weight"] > 0]
            prefs = r.sample(local, min(len(local), r.randint(1, 3)))
            score = int(min(830, max(600, r.gauss(712, 42))))
            self.customers[f"C-{i:04d}"] = Customer(f"C-{i:04d}", name, ind, reg, score,
                                                    r.paretovariate(1.6), prefs)

    # --------------------------------------------------------------- pricing
    def tier_for(self, score: int) -> str:
        for t, (mn, _, _) in TIERS.items():
            if score >= mn:
                return t
        raise ValueError(score)

    def rate(self, d: date, tier: str, term: int) -> float:
        return self.sheet[(date(d.year, d.month, 1), tier, term)]

    def eligible_programs(self, d: date, model: str, term: int) -> list[dict]:
        return [p for p in self.programs
                if p["start_date"] <= d <= p["end_date"] and model in p["models"] and term <= p["max_term"]]

    def program(self, pid: str) -> dict:
        return next(p for p in self.programs if p["program_id"] == pid)

    def reprice(self, c: Contract) -> None:
        c.amount_financed = round(c.cash_price - c.down_payment + c.addons, 2)
        if c.product == "LEASE":
            _, msrp, _ = self.catalog[(c.model_code, c.model_year)]
            c.residual_value = round(msrp * c.residual_pct / 100, 2)
        c.subvention_mxn = 0.0
        if c.program_id:
            market = self.rate(c.contract_date, c.credit_tier, c.term_months)
            c.subvention_mxn = round(fin.subvention(c.product, c.amount_financed, c.residual_value,
                                                    self.program(c.program_id)["program_rate"],
                                                    market, c.term_months), 2)
        c.monthly_payment = round(fin.payment(c.product, c.amount_financed, c.residual_value,
                                              c.contract_rate, c.term_months), 2)

    def table_residual(self, c: Contract) -> float:
        base = self.residual_table[(self.segment[c.model_code], c.term_months)]
        if c.annual_km and c.annual_km > POLICY.high_mileage_km:
            base += POLICY.high_mileage_adj_pp
        return base

    def pick_approver(self, total: float) -> str:
        levels = sorted({lvl for lvl, auth in self.approvers.values() if auth >= total})
        lvl = levels[0] if (self.rng.random() < 0.75 or len(levels) == 1) else levels[1]
        return self.rng.choice(sorted(a for a, (l, _) in self.approvers.items() if l == lvl))

    def new_vin(self) -> str:
        while True:
            v = "9XF" + "".join(self.rng.choice(VIN_CHARS) for _ in range(14))
            if v not in self.vins:
                self.vins.add(v)
                return v

    def spacing_ok(self, cust: str, dealer: str, d: date, gap: int = 15, ignore=()) -> bool:
        return all(abs((d - x).days) > gap for x in self.deal_dates.get((cust, dealer), []) if x not in ignore)

    # ------------------------------------------------------------------ deals
    def make_deal(self, cust: Customer, dealer: str, d: date, *, product=None, model=None, term=None,
                  units=None, program="auto", approver=None, model_year=None, vin=None,
                  score=None, record=True) -> list[Contract]:
        r = self.rng
        ind = INDUSTRIES[cust.industry]
        product = product or ("LEASE" if r.random() < ind[2] else "LOAN")
        model = model or r.choice(ind[1])
        term = term or (r.choices(LOAN_TERMS, [3, 4, 3, 1])[0] if product == "LOAN"
                        else r.choices(LEASE_TERMS, [2, 5, 2])[0])
        units = units or min(15, 1 + int(math.log(1 - r.random()) / math.log(0.7)))
        model_year = model_year or d.year + (1 if d.month >= 8 else 0)
        seg, msrp, invoice = self.catalog[(model, model_year)]
        score = score or int(max(600, min(830, cust.base_score + r.randint(-8, 8))))
        tier = self.tier_for(score)

        cash = round(msrp * r.uniform(0.94, 0.995), -2)
        down = round(cash * r.choice([0, .05, .10, .15, .20] if product == "LOAN" else [0, 0, .05, .10]), -2)
        addons = round(cash * r.uniform(0, 0.10), -2)
        cap = TIERS[tier][2] * invoice
        if cash - down + addons > cap:
            down += math.ceil((cash - down + addons - cap) / 100) * 100

        if program == "auto":
            progs = self.eligible_programs(d, model, term)
            prog = min(progs, key=lambda p: p["program_rate"]) if progs and r.random() < 0.5 else None
        else:
            prog = self.program(program) if program else None
        buy = prog["program_rate"] if prog else self.rate(d, tier, term)
        if prog:
            markup = 0
        elif product == "LOAN":
            markup = r.choices([0, 50, 100, 150, 200], [3, 4, 5, 4, 4])[0]
        else:
            markup = r.choices([0, 25, 50, 75, 100], [3, 4, 5, 4, 4])[0]
        km = r.choices([20_000, 30_000, 40_000, 50_000, 60_000], [2, 4, 3, 2, 1])[0] if product == "LEASE" else None

        deal_key = self._next_deal
        self._next_deal += 1
        out = []
        for _ in range(units):
            c = Contract(
                key=self._next_key, deal_key=deal_key, dealer_id=dealer, customer_id=cust.customer_id,
                approver_id="", product=product, model_code=model, model_year=model_year,
                vin=vin or self.new_vin(), contract_date=d,
                entered_at=d + timedelta(days=r.choice([0, 0, 0, 1, 1, 2])),
                funded_date=d + timedelta(days=r.randint(1, 7)), term_months=term,
                cash_price=cash, down_payment=down, addons=addons, amount_financed=0.0,
                residual_pct=None, residual_value=None, annual_km=km, credit_score=score,
                credit_tier=tier, override_code=None, buy_rate=buy,
                contract_rate=round(buy + markup / 100, 2), program_id=prog["program_id"] if prog else None,
                subvention_mxn=0.0, monthly_payment=0.0)
            self._next_key += 1
            if product == "LEASE":
                c.residual_pct = float(self.table_residual(c))
            self.reprice(c)
            out.append(c)
        total = sum(c.amount_financed for c in out)
        appr = approver or self.pick_approver(total)
        for c in out:
            c.approver_id = appr
        if record:
            self.record(out)
        return out

    def record(self, out: list[Contract]) -> None:
        c = out[0]
        self.contracts.extend(out)
        self.deals[c.deal_key] = out
        self.deal_dates.setdefault((c.customer_id, c.dealer_id), []).append(c.contract_date)

    def deal_total(self, deal_key: int) -> float:
        return sum(c.amount_financed for c in self.deals[deal_key])

    def fix_approver(self, deal_key: int) -> None:
        """Keep a modified deal inside its approver's authority (so only the intended rule fires)."""
        total = self.deal_total(deal_key)
        appr = self.deals[deal_key][0].approver_id
        if self.approvers[appr][1] < total:
            appr = self.pick_approver(total)
            for c in self.deals[deal_key]:
                c.approver_id = appr

    def random_date(self, start: date = ORIG_START, end: date = ORIG_END) -> date:
        return start + timedelta(days=self.rng.randint(0, (end - start).days))

    def fresh(self, d: date, *, dealer=None, cust=None, gap=15, **kw) -> list[Contract] | None:
        """Make a deal for a random customer at one of their dealers, respecting deal spacing."""
        r = self.rng
        for _ in range(200):
            cu = cust or self.customers[r.choice(sorted(self.customers))]
            dl = dealer or r.choice(cu.dealers or sorted(k for k, v in self.dealers.items() if v["weight"] > 0))
            if self.spacing_ok(cu.customer_id, dl, d, gap):
                return self.make_deal(cu, dl, d, **kw)
        return None

    # ------------------------------------------------------------- background
    def background(self) -> None:
        r = self.rng
        custs = sorted(self.customers)
        weights = [self.customers[c].weight for c in custs]
        m = date(ORIG_START.year, ORIG_START.month, 1)
        while m <= ORIG_END:
            for _ in range(r.randint(*self.deal_range)):
                cu = self.customers[r.choices(custs, weights)[0]]
                if not cu.dealers:
                    continue
                dl = r.choices(cu.dealers, [self.dealers[x]["weight"] for x in cu.dealers])[0]
                last = fin.add_months(m, 1) - timedelta(days=1)
                for _ in range(5):
                    d = m + timedelta(days=r.randint(0, (min(last, ORIG_END) - m).days))
                    if self.spacing_ok(cu.customer_id, dl, d):
                        self.make_deal(cu, dl, d)
                        break
            m = fin.add_months(m, 1)

    # ------------------------------------------------------------------ plants
    def mark(self, pattern: str, contracts: list[Contract]) -> None:
        self.truth["contracts"].setdefault(pattern, []).extend(c.key for c in contracts)
        self.planted.update(c.key for c in contracts)

    def look(self, pattern: str, items: list) -> None:
        self.truth["lookalikes"].setdefault(pattern, []).extend(items)
        self.planted.update(c.key for c in items if isinstance(c, Contract))

    def free(self, pred) -> list[Contract]:
        return [c for c in self.contracts if c.key not in self.planted and pred(c)]

    def choose(self, n: int, cands: list[Contract], prefer: list[str] | None = None,
               share: float = 0.6) -> list[Contract]:
        r = self.rng
        picked: list[Contract] = []
        if prefer:
            pref = [c for c in cands if c.dealer_id in prefer]
            picked = r.sample(pref, min(len(pref), round(n * share)))
        rest = [c for c in cands if c not in picked]
        picked += r.sample(rest, min(len(rest), n - len(picked)))
        return picked

    def plant(self) -> None:
        r = self.rng
        vol = {}
        for c in self.contracts:
            vol[c.dealer_id] = vol.get(c.dealer_id, 0) + 1
        top = sorted(vol, key=lambda k: (-vol[k], k))[:15]
        self.aggressive = sorted(r.sample(top, 2))
        self.epd_dealers = sorted(r.sample([d for d in top if d not in self.aggressive], 2))
        self.truth["dealers"]["aggressive_dealer"] = self.aggressive
        self.truth["dealers"]["epd_cluster"] = self.epd_dealers
        P = POLICY

        # R01 markup above cap
        for c in self.choose(15, self.free(lambda c: not c.program_id), self.aggressive):
            cap = P.markup_cap_loan_bps if c.product == "LOAN" else P.markup_cap_lease_bps
            c.contract_rate = round(c.buy_rate + (cap + r.choice([50, 75, 100, 150, 200, 250])) / 100, 2)
            self.reprice(c)
            self.mark("markup_over_cap", [c])

        # R02 residual above the residual table
        for i, c in enumerate(self.choose(12, self.free(lambda c: c.product == "LEASE"), self.aggressive, 0.5)):
            if i < 4:
                c.annual_km = 50_000          # high mileage: the table drops, so the breach is bigger
            c.residual_pct = self.table_residual(c) + r.choice([3, 4, 5, 6, 7, 8])
            self.reprice(c)
            self.mark("residual_inflation", [c])

        # R03 payment that does not reconcile with the contract terms
        for c in self.choose(12, self.free(lambda c: True)):
            c.monthly_payment = round(c.monthly_payment * r.uniform(0.86, 0.96), 2)
            self.mark("payment_mismatch", [c])

        # R06 power booking: price over sticker, heavy add-ons, no down payment
        n = 0
        deals = [k for k, cs in self.deals.items() if len(cs) <= 2 and all(c.key not in self.planted for c in cs)]
        pref = [k for k in deals if self.deals[k][0].dealer_id in self.aggressive]
        order = r.sample(pref, min(len(pref), 4)) + r.sample(deals, len(deals))
        done = set()
        for k in order:
            if n >= 12:
                break
            if k in done:
                continue
            done.add(k)
            for c in self.deals[k]:
                _, msrp, _ = self.catalog[(c.model_code, c.model_year)]
                c.cash_price = round(msrp * r.uniform(1.04, 1.12), -2)
                c.addons = round(c.cash_price * r.uniform(0.16, 0.24), -2)
                c.down_payment = 0.0
                self.reprice(c)
            self.fix_approver(k)
            self.mark("power_booking", self.deals[k])
            n += len(self.deals[k])

        # R07 incentive outside its program (expired window or ineligible model)
        n = 0
        for c in r.sample(self.free(lambda c: not c.program_id), len(self.free(lambda c: not c.program_id))):
            if n >= 10:
                break
            expired = [p for p in self.programs if c.model_code in p["models"] and c.term_months <= p["max_term"]
                       and 5 <= (c.contract_date - p["end_date"]).days <= 45]
            wrong_model = [p for p in self.programs if p["start_date"] <= c.contract_date <= p["end_date"]
                           and c.model_code not in p["models"] and c.term_months <= p["max_term"]]
            p = (expired or wrong_model or [None])[0]
            if not p:
                continue
            c.program_id = p["program_id"]
            c.buy_rate = c.contract_rate = p["program_rate"]
            self.reprice(c)
            self.mark("incentive_misuse", [c])
            n += 1

        # R08 credit tier better than the score supports, no documented override
        n = 0
        deals = [k for k, cs in self.deals.items() if len(cs) <= 3 and cs[0].credit_tier != "A"
                 and not cs[0].program_id and all(c.key not in self.planted for c in cs)]
        for k in r.sample(deals, len(deals)):
            if n >= 12:
                break
            for c in self.deals[k]:
                better = "ABCD"["ABCD".index(c.credit_tier) - 1]
                markup = round((c.contract_rate - c.buy_rate) * 100)
                c.credit_tier = better
                c.buy_rate = self.rate(c.contract_date, better, c.term_months)
                c.contract_rate = round(c.buy_rate + markup / 100, 2)
                self.reprice(c)
            self.mark("tier_inflation", self.deals[k])
            n += len(self.deals[k])

        self._plant_backdating()
        self._plant_splits()
        self._plant_authority()
        self._plant_duplicate_vins()
        self._plant_evasive()
        self._lookalikes()

    def _plant_backdating(self) -> None:
        r = self.rng
        # program kind: signed inside the window, keyed in after it closed
        n = 0
        for p in r.sample(self.programs, len(self.programs)):
            if n >= 5:
                break
            d = p["end_date"] - timedelta(days=r.randint(0, 6))
            if not (ORIG_START <= d <= ORIG_END):
                continue
            entered = max(p["end_date"] + timedelta(days=3), d + timedelta(days=17)) + timedelta(days=r.randint(0, 18))
            deal = self.fresh(d, model=r.choice(p["models"]), term=min(36, p["max_term"]), units=r.randint(1, 2),
                              program=p["program_id"])
            if deal:
                for c in deal:
                    c.entered_at = entered
                self.mark("backdating", deal)
                n += 1
        # rate kind: signed late in a month, keyed in after the rate sheet went up
        jumps = [m for i, m in enumerate(self.months[:-1])
                 if self.base_rate[self.months[i + 1]] - self.base_rate[m] >= 0.25
                 and ORIG_START <= m <= ORIG_END]
        for m in r.sample(jumps, min(3, len(jumps))):
            nxt = fin.add_months(m, 1)
            d = nxt - timedelta(days=r.randint(1, 8))
            deal = self.fresh(d, product="LOAN", units=1, program=None)
            if deal:
                last = fin.add_months(nxt, 1) - timedelta(days=1)
                for c in deal:
                    c.entered_at = min(d + timedelta(days=r.randint(17, 30)), last)
                self.mark("backdating", deal)

    def deal_in_range(self, cu, dealer, d, lo, hi, auth, **kw) -> list[Contract] | None:
        """Build a deal whose total lands in [lo, hi] x authority, then record it."""
        for _ in range(80):
            probe = self.make_deal(cu, dealer, d, units=1, record=False, **kw)[0]
            m = max(1, int(hi * auth // probe.amount_financed))
            deal = self.make_deal(cu, dealer, d, units=m, record=False,
                                  **{**kw, "product": probe.product, "model": probe.model_code,
                                     "term": probe.term_months})
            if lo * auth <= sum(c.amount_financed for c in deal) <= hi * auth:
                self.record(deal)
                return deal
        return None

    def _plant_splits(self, pattern: str = "split_deal", groups: int = 4, gap: tuple[int, int] = (0, 3)) -> None:
        r = self.rng
        made = 0
        while made < groups:
            cu = self.customers[r.choice(sorted(self.customers))]
            if not cu.dealers:
                continue
            dl = r.choice(cu.dealers)
            d0 = self.random_date(ORIG_START, ORIG_END - timedelta(days=3 * gap[1] + 5))
            if not self.spacing_ok(cu.customer_id, dl, d0, 3 * gap[1] + 25):
                continue
            model = r.choice(INDUSTRIES[cu.industry][1])
            group, d = [], d0
            for i in range(r.randint(2, 3)):
                d = d0 if i == 0 else d + timedelta(days=r.randint(*gap))
                appr = r.choice(["AP-01", "AP-02", "AP-03", "AP-04"])
                deal = self.deal_in_range(cu, dl, d, 0.74, 0.97, self.approvers[appr][1], program=None,
                                          product="LOAN", model=model, approver=appr)
                if not deal:
                    break
                group += deal
            if len({c.deal_key for c in group}) < 2:
                for c in group:
                    self.contracts.remove(c)
                continue
            self.mark(pattern, group)
            made += 1

    def _plant_authority(self) -> None:
        r = self.rng
        made = 0
        while made < 4:
            cu = self.customers[r.choice(sorted(self.customers))]
            if not cu.dealers:
                continue
            dl = r.choice(cu.dealers)
            d = self.random_date()
            if not self.spacing_ok(cu.customer_id, dl, d, 25):
                continue
            appr = r.choice(["AP-01", "AP-02", "AP-03", "AP-05", "AP-06"])
            deal = self.deal_in_range(cu, dl, d, 1.15, 1.6, self.approvers[appr][1], program=None, approver=appr)
            if deal:
                self.mark("authority_exceeded", deal)
                made += 1

    def _plant_duplicate_vins(self) -> None:
        r = self.rng
        cands = self.free(lambda c: c.contract_date <= date(2025, 9, 30))
        made = 0
        for a in r.sample(cands, len(cands)):
            if made >= 6:
                break
            d = a.funded_date + timedelta(days=r.randint(30, 200))
            if d > ORIG_END:
                continue
            others = [k for k in sorted(self.dealers) if k != a.dealer_id and self.dealers[k]["weight"] > 0]
            b = self.fresh(d, dealer=r.choice(others), product=a.product, model=a.model_code, units=1,
                           model_year=a.model_year, vin=a.vin)
            if not b or b[0].customer_id == a.customer_id:
                if b:  # undo: same customer would be a refinance, not a double funding
                    self.contracts.remove(b[0])
                    del self.deals[b[0].deal_key]
                continue
            a.force = ("good",)
            self.planted.add(a.key)
            self.mark("duplicate_vin", b)
            made += 1

    def _plant_evasive(self) -> None:
        """Variants built to slip past the first-line rules."""
        r = self.rng
        # split spread over weeks: each piece outside the 7-day window of the last
        self._plant_splits("split_deal_slow", groups=2, gap=(9, 13))
        # cloned VIN with one character changed, so an exact match misses it
        cands = self.free(lambda c: c.contract_date <= date(2025, 9, 30))
        made = 0
        for a in r.sample(cands, len(cands)):
            if made >= 3:
                break
            d = a.funded_date + timedelta(days=r.randint(30, 200))
            if d > ORIG_END:
                continue
            pos = r.randint(9, 16)
            vin = a.vin[:pos] + r.choice([ch for ch in VIN_CHARS if ch != a.vin[pos]]) + a.vin[pos + 1:]
            if vin in self.vins:
                continue
            self.vins.add(vin)
            others = [k for k in sorted(self.dealers) if k != a.dealer_id and self.dealers[k]["weight"] > 0]
            b = self.fresh(d, dealer=r.choice(others), product=a.product, model=a.model_code, units=1,
                           model_year=a.model_year, vin=vin)
            if not b:
                continue
            a.force = ("good",)
            self.planted.add(a.key)
            self.mark("vin_near_duplicate", b)
            made += 1
        # backdating that keeps the keying lag just under the threshold
        made = 0
        for p in r.sample(self.programs, len(self.programs)):
            if made >= 3:
                break
            k = r.randint(0, 3)
            d = p["end_date"] - timedelta(days=k)
            if not (ORIG_START <= d <= ORIG_END):
                continue
            entered = p["end_date"] + timedelta(days=r.randint(2, POLICY.backdate_lag_days - 1 - k))
            deal = self.fresh(d, model=r.choice(p["models"]), term=min(36, p["max_term"]), units=1,
                              program=p["program_id"])
            if deal:
                for c in deal:
                    c.entered_at = entered
                self.mark("backdating_short", deal)
                made += 1

    # ------------------------------------------------------------- look-alikes
    def _lookalikes(self) -> None:
        r = self.rng
        P = POLICY
        for c in r.sample(self.free(lambda c: not c.program_id), 5):        # markup exactly at cap
            cap = P.markup_cap_loan_bps if c.product == "LOAN" else P.markup_cap_lease_bps
            c.contract_rate = round(c.buy_rate + cap / 100, 2)
            self.reprice(c)
            self.look("markup_at_cap", [c])
        for c in r.sample(self.free(lambda c: c.product == "LEASE"), 5):    # residual within tolerance
            c.residual_pct = self.table_residual(c) + r.choice([0.5, 0.8])
            self.reprice(c)
            self.look("residual_within_tolerance", [c])
        for c in r.sample(self.free(lambda c: True), 5):                     # one-peso rounding
            c.monthly_payment = round(c.monthly_payment + r.choice([-1, 1]), 2)
            self.look("payment_rounding", [c])
        for c in r.sample(self.free(lambda c: c.credit_tier == "A" and not c.program_id), 5):
            _, msrp, _ = self.catalog[(c.model_code, c.model_year)]           # high advance, inside cap
            c.cash_price, c.down_payment = msrp, 0.0
            c.addons = round(msrp * 0.14, -2)
            self.reprice(c)
            self.fix_approver(c.deal_key)
            self.look("high_advance_within_cap", [c])
        n = 0
        for p in r.sample(self.programs, len(self.programs)):                # signed on the last day
            if n >= 4 or p["end_date"] > ORIG_END:
                continue
            deal = self.fresh(p["end_date"], model=p["models"][0], term=min(36, p["max_term"]), units=1,
                              program=p["program_id"])
            if deal:
                self.look("incentive_last_day", deal)
                n += 1
        n = 0                                                                # documented tier override
        deals = [k for k, cs in self.deals.items() if len(cs) <= 2 and cs[0].credit_tier != "A"
                 and not cs[0].program_id and all(c.key not in self.planted for c in cs)]
        for k in r.sample(deals, len(deals)):
            if n >= 5:
                break
            total = self.deal_total(k)
            appr = r.choice([a for a, (lvl, auth) in self.approvers.items() if lvl >= 3 and auth >= total])
            code = r.choice(OVERRIDE_CODES)
            for c in self.deals[k]:
                better = "ABCD"["ABCD".index(c.credit_tier) - 1]
                markup = round((c.contract_rate - c.buy_rate) * 100)
                c.credit_tier, c.override_code, c.approver_id = better, code, appr
                c.buy_rate = self.rate(c.contract_date, better, c.term_months)
                c.contract_rate = round(c.buy_rate + markup / 100, 2)
                self.reprice(c)
            self.look("tier_override_documented", self.deals[k])
            n += 1
        n = 0                                                                # late keying, no benefit
        for c in r.sample(self.free(lambda c: not c.program_id), len(self.free(lambda c: not c.program_id))):
            if n >= 5:
                break
            e = c.contract_date + timedelta(days=r.randint(17, 30))
            if e <= AS_OF and self.rate(e, c.credit_tier, c.term_months) <= c.buy_rate:
                c.entered_at = e
                self.look("late_entry_no_benefit", [c])
                n += 1
        self._split_lookalikes()
        self._vin_lookalikes()
        self._small_dealer()

    def _split_lookalikes(self) -> None:
        r = self.rng
        made = 0
        while made < 2:                                      # two near-limit deals, a month apart
            cu = self.customers[r.choice(sorted(self.customers))]
            if not cu.dealers:
                continue
            dl = r.choice(cu.dealers)
            d0 = self.random_date(ORIG_START, ORIG_END - timedelta(days=40))
            d1 = d0 + timedelta(days=r.randint(20, 30))
            if not (self.spacing_ok(cu.customer_id, dl, d0, 25) and self.spacing_ok(cu.customer_id, dl, d1, 25)):
                continue
            g1 = self.deal_in_range(cu, dl, d0, 0.74, 0.97, 2_500_000, program=None, approver="AP-01")
            g2 = self.deal_in_range(cu, dl, d1, 0.74, 0.97, 2_500_000, program=None, approver="AP-02")
            if g1 and g2:
                self.look("split_far_apart", g1 + g2)
                made += 1
        made = 0
        while made < 2:                                      # same week, approver authority covers both
            cu = self.customers[r.choice(sorted(self.customers))]
            if not cu.dealers:
                continue
            dl = r.choice(cu.dealers)
            d0 = self.random_date(ORIG_START, ORIG_END - timedelta(days=10))
            if not self.spacing_ok(cu.customer_id, dl, d0, 25):
                continue
            g1 = self.deal_in_range(cu, dl, d0, 0.40, 0.48, 6_000_000, program=None, approver="AP-05")
            g2 = self.deal_in_range(cu, dl, d0 + timedelta(days=r.randint(1, 4)), 0.40, 0.48, 6_000_000,
                                    program=None, approver="AP-06")
            if g1 and g2:
                self.look("split_authorized", g1 + g2)
                made += 1
        made = 0
        while made < 2:                                      # near-limit deal plus a small add-on order
            cu = self.customers[r.choice(sorted(self.customers))]
            if not cu.dealers:
                continue
            dl = r.choice(cu.dealers)
            d = self.random_date(ORIG_START, ORIG_END - timedelta(days=5))
            if not self.spacing_ok(cu.customer_id, dl, d, 25):
                continue
            g1 = self.deal_in_range(cu, dl, d, 0.85, 0.97, 2_500_000, program=None, approver="AP-04")
            if not g1:
                continue
            g2 = self.make_deal(cu, dl, d + timedelta(days=r.randint(1, 3)), units=1, program=None,
                                approver="AP-04", model="SDN-C1")
            self.look("near_limit_plus_small_order", g1 + g2)
            made += 1
        made = 0
        while made < 3:                                      # single deal right at the limit
            cu = self.customers[r.choice(sorted(self.customers))]
            if not cu.dealers:
                continue
            dl = r.choice(cu.dealers)
            d = self.random_date()
            if not self.spacing_ok(cu.customer_id, dl, d, 25):
                continue
            deal = self.deal_in_range(cu, dl, d, 0.90, 1.0, 2_500_000, program=None, approver="AP-03")
            if deal:
                self.look("deal_at_authority", deal)
                made += 1

    def _vin_lookalikes(self) -> None:
        """VIN re-financed after the first contract terminated: legal re-use."""
        r = self.rng
        made = 0
        cands = self.free(lambda c: c.product == "LEASE" and c.contract_date <= date(2025, 3, 31))
        for a in r.sample(cands, len(cands)):
            if made >= 3:
                break
            j_max = min(a.term_months - 1, fin.months_between(a.contract_date, date(2026, 1, 15)))
            if j_max < 6:
                continue
            j = r.randint(6, j_max)
            close = fin.add_months(a.contract_date, j)
            d = close + timedelta(days=r.randint(10, 60))
            if d > ORIG_END:
                continue
            b = self.fresh(d, product="LEASE", model=a.model_code, units=1, model_year=a.model_year, vin=a.vin)
            if not b:
                continue
            a.force = ("termination", j)
            self.look("vin_after_termination", [a] + b)
            made += 1

    def _small_dealer(self) -> None:
        """A tiny dealer with one early default: high raw rate, too little data to flag."""
        r = self.rng
        dl = self.small_dealer
        reg = self.dealers[dl]["region"]
        custs = sorted(c for c, v in self.customers.items() if v.region == reg) or sorted(self.customers)
        made = []
        for i in range(4):
            d = date(2025, 2, 1) + timedelta(days=40 * i + r.randint(0, 20))
            deal = self.fresh(d, dealer=dl, cust=self.customers[r.choice(custs)], units=1)
            if deal:
                made += deal
        if made:
            made[0].force = ("epd", 1)
            self.look("small_dealer_one_epd", [dl])
            self.planted.update(c.key for c in made)

    # ------------------------------------------------------------ performance
    def performance(self) -> None:
        r = self.rng
        base_default = {"A": 0.01, "B": 0.02, "C": 0.04, "D": 0.07}
        for c in self.contracts:
            n = c.term_months
            if c.force:
                kind = c.force[0]
            elif c.dealer_id in self.epd_dealers and r.random() < 0.22:
                kind = "epd"
            else:
                u = r.random()
                p_def = base_default[c.credit_tier]
                if u < p_def * 0.3:
                    kind = "epd"
                elif u < p_def:
                    kind = "default"
                elif u < p_def + 0.04:
                    kind = "termination" if c.product == "LEASE" else "payoff"
                else:
                    kind = "good"
            c.perf = kind
            c.default_at = None
            if kind == "epd":
                c.default_at = c.force[1] if c.force and len(c.force) > 1 else r.choice([1, 2])
            elif kind == "default":
                c.default_at = r.randint(4, max(4, n))
            c.close_at = None
            if kind in ("termination", "payoff"):
                c.close_at = c.force[1] if c.force and len(c.force) > 1 else r.randint(6, n - 1)

            maturity = fin.add_months(c.contract_date, n)
            if c.default_at:
                chargeoff = fin.add_months(c.contract_date, c.default_at) + timedelta(days=120)
                if fin.add_months(c.contract_date, c.default_at) <= AS_OF and chargeoff <= AS_OF \
                        and chargeoff <= maturity + timedelta(days=120):
                    c.status, c.close_date = "CHARGED_OFF", chargeoff
            elif c.close_at and fin.add_months(c.contract_date, c.close_at) <= AS_OF:
                c.status = "TERMINATED_EARLY" if c.product == "LEASE" else "PAID_OFF"
                c.close_date = fin.add_months(c.contract_date, c.close_at)
            if c.status == "ACTIVE" and maturity <= AS_OF:
                c.status = "MATURED" if c.product == "LEASE" else "PAID_OFF"
                c.close_date = maturity

    def payments(self) -> list[dict]:
        r = self.rng
        rows = []
        for c in self.contracts:
            k = 1
            while True:
                due = fin.add_months(c.contract_date, k)
                if due > AS_OF or k > c.term_months or (c.close_date and due > c.close_date):
                    break
                missed = c.default_at is not None and k >= c.default_at
                paid = None
                if not missed:
                    u = r.random()
                    delay = r.randint(0, 3) if u < 0.94 else (r.randint(4, 25) if u < 0.99 else r.randint(31, 45))
                    paid = due + timedelta(days=delay)
                    if paid > AS_OF:
                        paid = None
                rows.append({"contract_id": c.contract_id, "installment": k, "due_date": due,
                             "amount_due": c.monthly_payment, "paid_date": paid,
                             "amount_paid": c.monthly_payment if paid else 0.0})
                k += 1
        return rows

    # --------------------------------------------------------------- exposure
    def exposure_events(self, cust: str) -> list[tuple[date, float, list[Contract]]]:
        cs = [c for c in self.contracts if c.customer_id == cust]
        events = []
        for ev in sorted({c.funded_date for c in cs}):
            total = 0.0
            for c in cs:
                if c.funded_date <= ev and (c.close_date is None or c.close_date > ev):
                    k = fin.months_between(c.contract_date, ev)
                    total += fin.balance(c.product, c.amount_financed, c.residual_value, c.contract_rate,
                                         c.term_months, c.monthly_payment, k)
            events.append((ev, total, [c for c in cs if c.funded_date == ev]))
        return events

    def limits(self) -> None:
        r = self.rng
        self.limit_rows = []
        events = {cid: self.exposure_events(cid) for cid in sorted(self.customers)}
        for cid, cu in self.customers.items():
            dates = [c.contract_date for c in self.contracts if c.customer_id == cid]
            cu.onboarded = (min(dates) if dates else self.random_date()) - timedelta(days=r.randint(15, 400))
        eligible = [cid for cid, ev in events.items()
                    if len(ev) >= 3 and max(t for _, t, _ in ev) >= 3_000_000
                    and not any(c.key in self.planted for _, _, cs in ev for c in cs)]
        chosen = r.sample(eligible, 6)
        breach, raised = sorted(chosen[:3]), sorted(chosen[3:])
        for cid in sorted(self.customers):
            ev = events[cid]
            peak = max((t for _, t, _ in ev), default=0.0)
            on = self.customers[cid].onboarded
            if cid in breach:
                lim = math.floor(peak * r.uniform(0.72, 0.85) / 100_000) * 100_000
                self.limit_rows.append((cid, on, lim))
                hit = [c for d, t, cs in ev if t > lim for c in cs]
                self.mark("exposure_breach", hit)
            elif cid in raised:
                low = math.floor(peak * r.uniform(0.72, 0.85) / 100_000) * 100_000
                i = next(i for i, (_, t, _) in enumerate(ev) if t > low)
                t_star = ev[i][0]
                prev = ev[i - 1][0] if i > 0 else on
                raise_on = max(prev + timedelta(days=1), t_star - timedelta(days=r.randint(1, 30)))
                high = math.ceil(peak * r.uniform(1.3, 1.6) / 100_000) * 100_000
                self.limit_rows += [(cid, on, low), (cid, raise_on, high)]
            else:
                lim = math.ceil(max(peak, 1_000_000) * r.uniform(1.25, 1.9) / 100_000) * 100_000
                self.limit_rows.append((cid, on, lim))
        self.truth["customers"]["exposure_breach"] = breach
        self.truth["lookalikes"]["limit_raised_before_deal"] = raised

    # ------------------------------------------------------------------ write
    def assign_ids(self) -> None:
        order = sorted(self.contracts, key=lambda c: (c.contract_date, c.deal_key, c.key))
        deal_ids = {}
        for i, c in enumerate(order, 1):
            c.contract_id = f"FC-{i:05d}"
            if c.deal_key not in deal_ids:
                deal_ids[c.deal_key] = f"DL-{len(deal_ids) + 1:05d}"
            c.deal_id = deal_ids[c.deal_key]
        self.contracts = order
        for c in self.contracts:
            self.dealers[c.dealer_id].setdefault("first", c.contract_date)   # order is by date
        for d in self.dealers.values():
            first = d.get("first") or ORIG_START
            d["onboarded"] = first - timedelta(days=self.rng.randint(30, 900))


def generate(seed: int = 7) -> Book:
    b = Book(seed)
    b.background()
    b.plant()
    b.performance()
    b.limits()
    b.assign_ids()
    return b


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for row in rows:
            w.writerow({k: ("" if v is None else v) for k, v in row.items()})


CONTRACT_FIELDS = ["contract_id", "deal_id", "dealer_id", "customer_id", "approver_id", "product",
                   "model_code", "model_year", "vin", "contract_date", "entered_at", "funded_date",
                   "term_months", "cash_price", "down_payment", "addons", "amount_financed",
                   "residual_pct", "residual_value", "annual_km", "credit_score", "credit_tier",
                   "override_code", "buy_rate", "contract_rate", "program_id", "subvention_mxn",
                   "monthly_payment", "status", "close_date"]


def write(book: Book, out: Path) -> None:
    out = Path(out)
    b = book
    _write(out / "dealers.csv", [{"dealer_id": k, "name": v["name"], "region": v["region"], "city": v["city"],
                                  "onboarded": v["onboarded"]} for k, v in sorted(b.dealers.items())])
    _write(out / "customers.csv", [{"customer_id": c.customer_id, "name": c.name, "industry": c.industry,
                                    "region": c.region, "onboarded": c.onboarded}
                                   for c in sorted(b.customers.values(), key=lambda c: c.customer_id)])
    _write(out / "customer_limits.csv", [{"customer_id": c, "effective_date": d, "limit_mxn": l}
                                         for c, d, l in sorted(b.limit_rows)])
    _write(out / "approvers.csv", [{"approver_id": a, "name": f"Analista de crédito {a[-2:]}" if lvl < 4
                                    else "Comité de crédito", "level": lvl, "authority_mxn": auth}
                                   for a, lvl, auth in APPROVERS])
    _write(out / "vehicle_catalog.csv", [{"model_code": m, "model_year": y, "segment": s, "msrp": p, "invoice": i}
                                         for (m, y), (s, p, i) in sorted(b.catalog.items())])
    _write(out / "residual_table.csv", [{"segment": s, "term_months": t, "residual_pct": v}
                                        for (s, t), v in sorted(b.residual_table.items())])
    _write(out / "rate_sheet.csv", [{"sheet_month": m, "tier": t, "term_months": term, "buy_rate": v}
                                    for (m, t, term), v in sorted(b.sheet.items())])
    _write(out / "incentive_programs.csv", [{k: p[k] for k in ("program_id", "name", "start_date", "end_date",
                                                                "program_rate", "max_term")} for p in b.programs])
    _write(out / "program_models.csv", [{"program_id": p["program_id"], "model_code": m}
                                        for p in b.programs for m in p["models"]])
    _write(out / "contracts.csv", [{f: getattr(c, f) for f in CONTRACT_FIELDS} for c in b.contracts])
    _write(out / "payments.csv", b.payments())


def write_truth(book: Book, path: Path) -> None:
    ids = {c.key: c.contract_id for c in book.contracts}

    def conv(items):
        return sorted(ids[x.key] if isinstance(x, Contract) else ids.get(x, x) for x in items)

    t = book.truth
    out = {
        "seed": book.seed,
        "note": "Answer key for the synthetic book. Detection code never reads this file.",
        "contracts": {k: conv(v) for k, v in sorted(t["contracts"].items())},
        "dealers": {k: sorted(v) for k, v in sorted(t["dealers"].items())},
        "customers": {k: sorted(v) for k, v in sorted(t["customers"].items())},
        "lookalikes": {k: conv(v) for k, v in sorted(t["lookalikes"].items())},
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
