"""Lead + company directory: search (masked previews) and reveal (full rows,
optionally imported into a list), with Gojiberry's search_leads filters.

Two sources:
- 'workspace' (default): every person/company any agent has ever found
- 'linkedin': a live LinkedIn people search through your seat; results are
  cached and become contacts only when revealed
There are no credits - revealing is free; the cost is LinkedIn page views.
"""
from __future__ import annotations

from typing import Any

from db.database import get_conn
from sales import linkedin as li
from sales.db import jsonb
from sales.lists import add_contacts_to_list, upsert_contact

_MASKED = ("id", "first_name", "job_title", "location", "industry")


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    return [x for x in (v if isinstance(v, list) else [v]) if x]


def search_leads(
    *, source: str = "workspace", name: str | None = None, company: str | None = None,
    job_title: Any = None, location: Any = None, industry: Any = None, company_size: Any = None,
    company_url: Any = None, has_recent_activity: bool | None = None,
    has_recently_changed_job: bool | None = None, has_recent_funding_round: bool | None = None,
    company_last_funding_round_since: str | None = None, is_company_hiring: bool | None = None,
    exclude_list_id: int | None = None, page: int = 1, limit: int = 10,
) -> dict:
    titles, locs, inds, sizes, curls = (_as_list(x) for x in (job_title, location, industry, company_size, company_url))
    if source == "linkedin":
        return _live_search(name, company, titles, locs, limit)
    if not any([name, company, titles, locs, inds, sizes, curls, has_recent_activity, has_recently_changed_job,
                has_recent_funding_round, company_last_funding_round_since, is_company_hiring]):
        return {"items": [], "total": 0, "page": page, "limit": limit, "note": "at least one filter is required"}
    where, vals, order = ["NOT c.rejected"], [], []
    if name:
        where.append("c.full_name ILIKE %s")
        vals.append(f"%{name}%")
    if company:
        where.append("c.company ILIKE %s")
        vals.append(f"%{company}%")
    if titles:
        where.append("(" + " OR ".join(["c.job_title ILIKE %s OR c.headline ILIKE %s"] * len(titles)) + ")")
        for t in titles:
            vals += [f"%{t}%", f"%{t}%"]
    if locs:
        where.append("(" + " OR ".join(["c.location ILIKE %s"] * len(locs)) + ")")
        vals += [f"%{x}%" for x in locs]
    if sizes:
        where.append("co.size = ANY(%s)")
        vals.append(sizes)
    if curls:
        where.append("(c.company_url = ANY(%s) OR co.linkedin_url = ANY(%s))")
        vals += [curls, curls]
    if has_recent_activity:
        where.append("c.intent_at >= now() - interval '90 days'")
    if has_recently_changed_job:
        where.append("c.intent_type = 'RECENTLY_CHANGED_JOB' AND c.created_at >= now() - interval '90 days'")
    if has_recent_funding_round:
        where.append("co.last_funding_at >= now() - interval '12 months'")
    if company_last_funding_round_since:
        where.append("co.last_funding_at >= %s::date")
        vals.append(company_last_funding_round_since)
    if is_company_hiring:
        where.append("co.is_hiring")
    if exclude_list_id:
        where.append("NOT EXISTS (SELECT 1 FROM sales_list_contacts x WHERE x.contact_id = c.id AND x.list_id = %s)")
        vals.append(exclude_list_id)
    boost_vals: list = []
    if inds:  # soft preference, like Gojiberry: boosts, doesn't filter
        order.append("(" + " OR ".join(["COALESCE(c.industry, co.industry, '') ILIKE %s"] * len(inds)) + ") DESC")
        boost_vals = [f"%{x}%" for x in inds]
    order.append("c.total_score DESC NULLS LAST, c.id")
    limit = max(1, min(int(limit), 100))
    page = max(1, int(page))
    base = f"FROM sales_contacts c LEFT JOIN sales_companies co ON co.id = c.company_id WHERE {' AND '.join(where)}"
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) n {base}", vals).fetchone()["n"]
        rows = conn.execute(
            f"SELECT c.id, c.first_name, c.job_title, c.location, COALESCE(c.industry, co.industry) AS industry "
            f"{base} ORDER BY {', '.join(order)} LIMIT %s OFFSET %s",
            (*vals, *boost_vals, limit, (page - 1) * limit),
        ).fetchall()
    return {"items": [{**{k: r.get(k) for k in _MASKED}, "source": "workspace"} for r in rows],
            "total": total, "page": page, "limit": limit}


def _live_search(name: str | None, company: str | None, titles: list[str], locs: list[str], limit: int) -> dict:
    seat = li.default_seat()
    if not li.has_session(seat):
        raise li.NoSession("live directory search needs a logged-in LinkedIn seat")
    query = " ".join(x for x in [name, (titles or [None])[0], company, (locs or [None])[0]] if x)
    if not query:
        return {"items": [], "total": 0, "note": "at least one filter is required"}
    people = li.call("search_people", {"query": query, "max": min(limit, 30)}, seat) or []
    items = []
    with get_conn() as conn:
        for p in people:
            r = conn.execute(
                "INSERT INTO sales_directory_cache (profile_url, payload) VALUES (%s, %s) "
                "ON CONFLICT (profile_url) DO UPDATE SET payload = EXCLUDED.payload, created_at = now() RETURNING id",
                (p["profile_url"], jsonb(p)),
            ).fetchone()
            first = (p.get("full_name") or "").split(" ")[0]
            items.append({"id": f"li-{r['id']}", "first_name": first, "job_title": p.get("headline"),
                          "location": p.get("location"), "industry": None, "source": "linkedin"})
    return {"items": items, "total": len(items), "page": 1, "limit": limit}


def reveal_leads(ids: list, list_id: int | None = None) -> dict:
    """Full lead objects; with list_id, imported into that list too."""
    from sales.signals import _cand

    revealed, to_import = [], []
    for raw in ids[:100]:
        sid = str(raw)
        if sid.startswith("li-"):
            with get_conn() as conn:
                r = conn.execute("SELECT payload FROM sales_directory_cache WHERE id = %s", (int(sid[3:]),)).fetchone()
            if not r:
                continue
            c = _cand(r["payload"], "DIRECTORY", "linkedin search", intent="Found via directory search")
            if not c:
                continue
            cid, _ = upsert_contact(c)
        else:
            cid = int(sid)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT c.*, to_jsonb(co.*) AS company_obj FROM sales_contacts c "
                "LEFT JOIN sales_companies co ON co.id = c.company_id WHERE c.id = %s", (cid,),
            ).fetchone()
        if row:
            revealed.append(row)
            if row.get("first_name") and row.get("last_name") and not row["rejected"]:
                to_import.append(cid)
    imported = add_contacts_to_list(list_id, to_import) if list_id else 0
    return {"leads": revealed, "imported": imported}


def search_companies(
    *, company_size: Any = None, headquarters: Any = None, industry: Any = None, is_b2b: bool | None = None,
    is_hiring: bool | None = None, technologies_used: Any = None, page: int = 1, limit: int = 20,
) -> dict:
    sizes, hqs, inds, techs = (_as_list(x) for x in (company_size, headquarters, industry, technologies_used))
    if not any([sizes, hqs, inds, techs, is_b2b is not None, is_hiring]):
        return {"items": [], "total": 0, "note": "at least one filter is required"}
    where, vals, boost = ["true"], [], []
    if sizes:
        where.append("size = ANY(%s)")
        vals.append(sizes)
    if hqs:
        where.append("(" + " OR ".join(["headquarters ILIKE %s"] * len(hqs)) + ")")
        vals += [f"%{h}%" for h in hqs]
    if is_b2b is not None:
        where.append("is_b2b = %s")
        vals.append(is_b2b)
    if is_hiring:
        where.append("is_hiring")
    if techs:
        where.append("technologies && %s")
        vals.append([t.lower() for t in techs])
    order = "id"
    if inds:
        order = "(" + " OR ".join(["COALESCE(industry, '') ILIKE %s"] * len(inds)) + ") DESC, id"
        boost = [f"%{i}%" for i in inds]
    limit = max(1, min(int(limit), 100))
    w = " AND ".join(where)
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) n FROM sales_companies WHERE {w}", vals).fetchone()["n"]
        rows = conn.execute(
            f"SELECT id, size, industry, headquarters FROM sales_companies WHERE {w} ORDER BY {order} LIMIT %s OFFSET %s",
            (*vals, *boost, limit, (max(1, page) - 1) * limit),
        ).fetchall()
    return {"items": rows, "total": total, "page": page, "limit": limit}


def reveal_companies(ids: list[int]) -> list[dict]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM sales_companies WHERE id = ANY(%s) ORDER BY id", (ids[:100],)).fetchall()


def directory_industries() -> dict:
    with get_conn() as conn:
        seen = [r["industry"] for r in conn.execute(
            "SELECT industry, COUNT(*) n FROM (SELECT industry FROM sales_contacts UNION ALL "
            "SELECT industry FROM sales_companies) x WHERE industry IS NOT NULL GROUP BY industry ORDER BY n DESC LIMIT 200"
        ).fetchall()]
    grouped = {
        "Technology": ["Software Development & SaaS", "IT Services and IT Consulting", "Computer Hardware",
                       "Internet Publishing", "Cybersecurity", "Artificial Intelligence"],
        "Finance": ["Financial Services", "Banking", "Insurance", "Venture Capital and Private Equity", "Fintech"],
        "Real Estate & Construction": ["Real Estate", "Construction", "Architecture and Planning"],
        "Health": ["Hospitals and Health Care", "Medical Devices", "Pharmaceutical Manufacturing", "Wellness and Fitness"],
        "Commerce": ["Retail", "E-commerce", "Consumer Goods", "Wholesale"],
        "Services": ["Marketing Services", "Advertising Services", "Business Consulting and Services",
                     "Staffing and Recruiting", "Legal Services", "Accounting"],
        "Media & Education": ["Online Audio and Video Media", "Media Production", "E-Learning Providers",
                              "Education Administration Programs", "Higher Education"],
        "Industry": ["Manufacturing", "Logistics, Transportation and Supply Chain", "Automotive",
                     "Oil and Gas", "Renewable Energy"],
    }
    flat = list(dict.fromkeys([i for v in grouped.values() for i in v] + seen))
    return {"industries": flat, "grouped": grouped, "seen_in_workspace": seen}
