"""Price a job: take-off quantities -> mappings -> prebuilds/items -> cost -> margin -> sell.

Nothing is stored; the estimate is worked out from the take-off, the job's price-book version
and the mappings every time, so it always matches the current quantities. Money is Decimal,
rounded to cents per line, and totals are sums of the rounded lines.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (CatalogueItem, CountItem, GeneratedItem, Job, JobAllowance, LabourRate, PriceBookVersion,
                     PriceItem, PriceMapping, Prebuild, Run, Service, Sheet, Stage)
from .rules import effective_qty
from .takeoff import d2, run_waste_m

CENT = Decimal("0.01")
MAX_NESTING = 5


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class UnitCost:
    material: Decimal = Decimal(0)  # $ per unit, unrounded
    labour_hours: Decimal = Decimal(0)
    labour: Decimal = Decimal(0)
    missing: set = field(default_factory=set)  # codes the price book doesn't have


class PriceBook:
    def __init__(self, db: Session, version: PriceBookVersion):
        self.version = version
        self.items = {p.code: p for p in db.scalars(select(PriceItem).where(PriceItem.version_id == version.id))}
        self.prebuilds = {p.code: p for p in db.scalars(select(Prebuild).where(Prebuild.version_id == version.id))}
        self.rates = {r.code: r for r in db.scalars(select(LabourRate).where(LabourRate.version_id == version.id))}
        self._cache: dict[tuple, UnitCost] = {}

    def rate_for(self, code: str) -> LabourRate | None:
        return self.rates.get(code or self.version.default_labour_rate_code)

    def unit_cost(self, kind: str, code: str, depth: int = 0) -> UnitCost:
        key = (kind, code)
        if key in self._cache:
            return self._cache[key]
        uc = UnitCost()
        if kind == "item":
            item = self.items.get(code)
            if item is None:
                uc.missing.add(code)
            else:
                uc.material = Decimal(str(item.cost))
        else:
            pb = self.prebuilds.get(code)
            if pb is None:
                uc.missing.add(code)
            elif depth > MAX_NESTING:
                uc.missing.add(f"{code} (nested too deep)")
            else:
                for comp in pb.components or []:
                    qty = Decimal(str(comp.get("qty", 1)))
                    # A component can be a catalogue item or another prebuild.
                    sub_kind = "item" if comp["code"] in self.items else "prebuild" if comp["code"] in self.prebuilds else "item"
                    sub = self.unit_cost(sub_kind, comp["code"], depth + 1)
                    uc.material += sub.material * qty
                    uc.labour_hours += sub.labour_hours * qty
                    uc.labour += sub.labour * qty
                    uc.missing |= sub.missing
                hrs = Decimal(str(pb.labour_hours or 0))
                if hrs:
                    rate = self.rate_for(pb.labour_rate_code)
                    if rate is None:
                        uc.missing.add(f"labour rate {pb.labour_rate_code or self.version.default_labour_rate_code or '(no default)'}")
                    else:
                        uc.labour += hrs * Decimal(str(rate.rate))
                uc.labour_hours += hrs
        self._cache[key] = uc
        return uc


@dataclass
class Source:
    """A take-off quantity to price."""
    kind: str  # pipe | count | fitting
    service_id: int | None
    stage_id: int | None
    qty: Decimal
    uom: str
    description: str
    material: str = ""
    dn: int | None = None
    item_type: str = ""
    catalogue_code: str = ""  # a rule's output item, when set


def collect_sources(db: Session, job_id: int, include_suggested: bool = False) -> list[Source]:
    """Confirmed quantities on current sheets (plus suggestions if asked), grouped by what they are and their stage."""
    ok = ("confirmed", "suggested") if include_suggested else ("confirmed",)
    current = set(db.scalars(select(Sheet.id).where(Sheet.job_id == job_id, Sheet.is_current.is_(True))))
    pipes: dict[tuple, Decimal] = defaultdict(Decimal)
    for r in db.scalars(select(Run).where(Run.job_id == job_id)):
        if r.sheet_id in current and r.status in ok:
            total = d2(r.length_m) + d2(r.vertical_m) + run_waste_m(r)
            pipes[(r.service_id, r.material, r.dn, r.stage_id)] += total
    counts: dict[tuple, int] = defaultdict(int)
    for c in db.scalars(select(CountItem).where(CountItem.job_id == job_id)):
        if c.sheet_id in current and c.status in ok:
            counts[(c.service_id, c.item_type, c.stage_id)] += 1
    catalogue = {c.id: c.code for c in db.scalars(select(CatalogueItem))}
    fittings: dict[tuple, Decimal] = defaultdict(Decimal)
    for g in db.scalars(select(GeneratedItem).where(GeneratedItem.job_id == job_id)):
        q = effective_qty(g)
        if q > 0:
            fittings[(g.service_id, g.description, g.uom, g.stage_id, catalogue.get(g.item_id, ""))] += Decimal(str(q))

    out = [Source("pipe", s, st, q, "m", f"{mat} DN{dn}", material=mat, dn=dn) for (s, mat, dn, st), q in pipes.items()]
    out += [Source("count", s, st, Decimal(n), "ea", t, item_type=t) for (s, t, st), n in counts.items()]
    out += [Source("fitting", s, st, q, uom, d, catalogue_code=code) for (s, d, uom, st, code), q in fittings.items()]
    return out


def find_mapping(src: Source, mappings: list[PriceMapping], svc_code: str) -> PriceMapping | None:
    best = None
    for m in mappings:
        if m.source_kind != src.kind or m.service_code not in ("", svc_code):
            continue
        if src.kind == "pipe" and not (m.material == src.material and m.dn == src.dn):
            continue
        if src.kind == "count" and m.item_type != src.item_type:
            continue
        if src.kind == "fitting" and m.description.strip().lower() != src.description.strip().lower():
            continue
        if m.service_code == svc_code:
            return m  # exact service beats "any service"
        best = best or m
    return best


def margin_pct(job: Job, svc_code: str, stage_name: str) -> Decimal:
    """Stage margin overrides service margin, which overrides the job default."""
    if job.stage_margins and stage_name in job.stage_margins and job.stage_margins[stage_name] is not None:
        return Decimal(str(job.stage_margins[stage_name]))
    if job.service_margins and svc_code in job.service_margins and job.service_margins[svc_code] is not None:
        return Decimal(str(job.service_margins[svc_code]))
    return Decimal(str(job.default_margin_pct or 0))


def sell_price(cost: Decimal, pct: Decimal, basis: str) -> Decimal:
    if basis == "margin":
        if pct >= 100:
            raise ValueError("A margin must be under 100%")
        return money(cost / (1 - pct / 100))
    return money(cost * (1 + pct / 100))


def loading_for(job: Job, svc_code: str) -> tuple[Decimal, Decimal, list[str]]:
    """% loadings from accepted tender requirements (night works, access and so on) for a service.

    Returns (material %, labour %, labels). Loadings add up; each applies to the services it names,
    or every service if it names none.
    """
    mat, lab, labels = Decimal(0), Decimal(0), []
    for a in job.rate_adjustments or []:
        codes = a.get("service_codes") or []
        if codes and svc_code not in codes:
            continue
        pct = Decimal(str(a.get("percent") or 0))
        on = a.get("applies_to") or "labour"
        if on in ("labour", "all"):
            lab += pct
        if on in ("material", "all"):
            mat += pct
        labels.append(f"{a.get('label', 'Loading')} +{a.get('percent')}% {on}")
    return mat, lab, labels


def price_job(db: Session, job_id: int) -> dict:
    job = db.get(Job, job_id)
    services = {s.id: s for s in db.scalars(select(Service))}
    stages = {s.id: s for s in db.scalars(select(Stage))}
    sources = collect_sources(db, job_id)
    mappings = list(db.scalars(select(PriceMapping)))
    version = db.get(PriceBookVersion, job.price_book_version_id) if job.price_book_version_id else None
    book = PriceBook(db, version) if version else None

    lines, unmapped, missing_codes = [], [], set()
    for src in sources:
        svc = services.get(src.service_id)
        svc_code = svc.code if svc else ""
        stage = stages.get(src.stage_id)
        stage_name = stage.name if stage else "Unstaged"
        base = {"kind": src.kind, "service_code": svc_code, "stage": stage_name, "description": src.description,
                "qty": float(src.qty), "uom": src.uom, "material": src.material, "dn": src.dn, "item_type": src.item_type}
        m = find_mapping(src, mappings, svc_code)
        target_kind, target_code, factor = (m.target_kind, m.target_code, Decimal(str(m.factor))) if m else (None, None, Decimal(1))
        if m is None and src.catalogue_code:
            target_kind, target_code = "item", src.catalogue_code
        if target_code is None:
            unmapped.append(base)
            continue
        line = {**base, "target_kind": target_kind, "target_code": target_code, "factor": float(factor), "mapping_id": m.id if m else None}
        if book is None:
            lines.append(line)
            continue
        uc = book.unit_cost(target_kind, target_code)
        target_qty = src.qty * factor
        mat_pct, lab_pct, loadings = loading_for(job, svc_code)
        material = money(uc.material * target_qty * (1 + mat_pct / 100))
        labour = money(uc.labour * target_qty * (1 + lab_pct / 100))
        hours = (uc.labour_hours * target_qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cost = material + labour
        pct = margin_pct(job, svc_code, stage_name)
        sell = sell_price(cost, pct, job.margin_basis)
        target = (book.prebuilds.get(target_code) if target_kind == "prebuild" else book.items.get(target_code))
        line.update({"target_description": target.description if target else "", "target_qty": float(target_qty),
                     "material_cost": material, "labour_hours": hours, "labour_cost": labour, "cost": cost,
                     "margin_pct": pct, "sell": sell, "missing": sorted(uc.missing), "loadings": loadings,
                     "loading_cost": money(uc.material * target_qty * mat_pct / 100) + money(uc.labour * target_qty * lab_pct / 100)})
        missing_codes |= uc.missing
        lines.append(line)

    # Workbook rows (estimating.py): priced from their own rates, with or without a price book
    from .estimating import priced_lines

    workbook = priced_lines(db, job)
    for w in workbook:
        lines.append({"kind": "workbook", "service_code": w["service_code"], "stage": w["stage"], "description": w["description"],
                      "qty": w["qty"], "uom": w["uom"], "material": "", "dn": None, "item_type": "", "target_kind": "workbook",
                      "target_code": w["rate_code"], "factor": 1.0, "mapping_id": None, "workbook_id": w["id"], "section": w["section"],
                      "target_description": w["section"], "target_qty": w["qty"],
                      "material_cost": money(w["material_cost"]), "labour_hours": Decimal(str(w["labour_hours"])),
                      "labour_cost": money(w["labour_cost"]), "plant_cost": money(w["plant_cost"]),
                      "subcontract_cost": money(w["subcontract_cost"]), "cost": money(w["cost"]),
                      "margin_pct": Decimal(str(w["margin_pct"])), "sell": money(w["sell"]), "missing": [], "loadings": [],
                      "loading_cost": Decimal(0), "error": w["error"]})

    allowances = []
    for a in db.scalars(select(JobAllowance).where(JobAllowance.job_id == job_id).order_by(JobAllowance.kind, JobAllowance.id)):
        svc = services.get(a.service_id)
        stage = stages.get(a.stage_id)
        row = {"id": a.id, "kind": a.kind, "description": a.description, "service_code": svc.code if svc else "",
               "stage": stage.name if stage else "Unstaged", "amount": money(a.amount if a.kind != "exclusion" else 0),
               "apply_margin": a.apply_margin}
        if a.kind != "exclusion":
            pct = margin_pct(job, row["service_code"], row["stage"]) if a.apply_margin else Decimal(0)
            row["margin_pct"] = pct
            row["sell"] = sell_price(row["amount"], pct, job.margin_basis)
        allowances.append(row)

    priced = book is not None or bool(workbook)
    summary = None
    if priced:
        priced_lines_ = [ln for ln in lines if "cost" in ln]  # without a price book only the workbook rows have prices
        by_service: dict[str, dict] = defaultdict(lambda: defaultdict(Decimal))
        by_stage: dict[str, dict] = defaultdict(lambda: defaultdict(Decimal))
        for ln in priced_lines_:
            for bucket in (by_service[ln["service_code"] or "–"], by_stage[ln["stage"]]):
                for f in ("material_cost", "labour_cost", "plant_cost", "subcontract_cost", "cost", "sell", "labour_hours"):
                    bucket[f] += ln.get(f, Decimal(0))
        for a in allowances:
            if a["kind"] == "exclusion":
                continue
            for bucket in (by_service[a["service_code"] or "–"], by_stage[a["stage"]]):
                bucket["allowances_cost"] += a["amount"]
                bucket["cost"] += a["amount"]
                bucket["sell"] += a["sell"]
        material = sum((ln["material_cost"] for ln in priced_lines_), Decimal(0))
        labour = sum((ln["labour_cost"] for ln in priced_lines_), Decimal(0))
        plant = sum((ln.get("plant_cost", Decimal(0)) for ln in priced_lines_), Decimal(0))
        subcontract = sum((ln.get("subcontract_cost", Decimal(0)) for ln in priced_lines_), Decimal(0))
        hours = sum((ln["labour_hours"] for ln in priced_lines_), Decimal(0))
        allow_cost = sum((a["amount"] for a in allowances if a["kind"] != "exclusion"), Decimal(0))
        cost = material + labour + plant + subcontract + allow_cost
        sell = sum((ln["sell"] for ln in priced_lines_), Decimal(0)) + sum((a["sell"] for a in allowances if a["kind"] != "exclusion"), Decimal(0))
        gst = money(sell * Decimal(str(job.gst_pct)) / 100)
        stage_order = {s.name: s.order for s in stages.values()}
        loading_cost = sum((ln["loading_cost"] for ln in priced_lines_), Decimal(0))
        summary = {
            "material_cost": material, "labour_cost": labour, "labour_hours": hours, "allowances_cost": allow_cost,
            "plant_cost": plant, "subcontract_cost": subcontract, "workbook_cost": sum((ln["cost"] for ln in priced_lines_
                                                                                       if ln["kind"] == "workbook"), Decimal(0)),
            "loadings": job.rate_adjustments or [], "loading_cost": loading_cost,
            "cost": cost, "margin": sell - cost, "sell_ex_gst": sell, "gst": gst, "sell_inc_gst": sell + gst,
            "by_service": [{"service_code": k, **v} for k, v in sorted(by_service.items())],
            "by_stage": [{"stage": k, **v} for k, v in sorted(by_stage.items(), key=lambda kv: stage_order.get(kv[0], 999))],
        }
        if job.reference_total_ex_gst:
            ref = Decimal(str(job.reference_total_ex_gst))
            summary["reference_total_ex_gst"] = ref
            summary["reference_variance_pct"] = ((sell - ref) / ref * 100).quantize(Decimal("0.01")) if ref else None

    def clean(v):
        if isinstance(v, Decimal):
            return float(v)
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        if isinstance(v, list):
            return [clean(x) for x in v]
        return v

    return clean({
        "price_book": {"id": version.id, "label": version.label, "locked": version.locked} if version else None,
        "margin_basis": job.margin_basis,
        "lines": sorted(lines, key=lambda l: (l["stage"], l["service_code"], l["kind"], l["description"])),
        "unmapped": unmapped, "missing_codes": sorted(missing_codes), "allowances": allowances, "summary": summary,
    })
