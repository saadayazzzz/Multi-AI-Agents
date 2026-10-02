"""Lists, contacts and companies - the shared store both agents work on."""
from __future__ import annotations

import csv
import io
from typing import Any

from db.database import get_conn
from sales.db import jsonb

# ----------------------------------------------------------------- lists --


def create_list(name: str, custom_fields: dict | None = None) -> dict:
    with get_conn() as conn:
        return conn.execute(
            "INSERT INTO sales_lists (name, custom_fields) VALUES (%s, %s) RETURNING *",
            (name, jsonb(custom_fields) if custom_fields else None),
        ).fetchone() | {"contact_count": 0}


_LIST_SELECT = """
    SELECT l.*, l.campaign_agent_id AS campaign_id,
           (SELECT COUNT(*) FROM sales_list_contacts lc WHERE lc.list_id = l.id) AS contact_count
    FROM sales_lists l
"""


def list_lists() -> list[dict]:
    with get_conn() as conn:
        return conn.execute(_LIST_SELECT + " ORDER BY l.id DESC").fetchall()


def get_list(list_id: int) -> dict | None:
    with get_conn() as conn:
        return conn.execute(_LIST_SELECT + " WHERE l.id = %s", (list_id,)).fetchone()


def update_list(list_id: int, name: str | None = None, custom_fields: dict | None = None) -> dict | None:
    with get_conn() as conn:
        if name is not None:
            conn.execute("UPDATE sales_lists SET name = %s, updated_at = now() WHERE id = %s", (name, list_id))
        if custom_fields is not None:
            conn.execute(
                "UPDATE sales_lists SET custom_fields = %s, updated_at = now() WHERE id = %s",
                (jsonb(custom_fields), list_id),
            )
    return get_list(list_id)


def delete_list(list_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sales_lists WHERE id = %s", (list_id,))


def add_contacts_to_list(list_id: int, contact_ids: list[int]) -> int:
    added = 0
    with get_conn() as conn:
        for cid in contact_ids:
            r = conn.execute(
                "INSERT INTO sales_list_contacts (list_id, contact_id) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING RETURNING contact_id",
                (list_id, cid),
            ).fetchone()
            added += 1 if r else 0
        conn.execute("UPDATE sales_lists SET updated_at = now() WHERE id = %s", (list_id,))
    return added


def remove_contacts_from_list(list_id: int, contact_ids: list[int]) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM sales_list_contacts WHERE list_id = %s AND contact_id = ANY(%s)",
            (list_id, contact_ids),
        )
        return cur.rowcount


# ------------------------------------------------------------- companies --


def _clean_domain(d: str | None) -> str | None:
    if not d:
        return None
    d = d.lower().strip().replace("https://", "").replace("http://", "")
    d = d.removeprefix("www.").split("/")[0].strip()
    return d or None


def upsert_company(data: dict[str, Any]) -> int | None:
    """Find-or-create by domain, then LinkedIn URL, then exact name.
    Only fills columns that are still empty - never overwrites known data."""
    name = (data.get("name") or "").strip()
    domain = _clean_domain(data.get("domain") or data.get("website"))
    li = data.get("linkedin_url") or None
    if not (name or domain or li):
        return None
    cols = [
        "industry", "size", "company_type", "headquarters", "description",
        "is_b2b", "is_hiring", "last_funding_at", "last_funding_round", "website",
    ]
    with get_conn() as conn:
        row = None
        if domain:
            row = conn.execute("SELECT id FROM sales_companies WHERE lower(domain) = %s", (domain,)).fetchone()
        if not row and li:
            row = conn.execute("SELECT id FROM sales_companies WHERE linkedin_url = %s", (li,)).fetchone()
        if not row and name:
            row = conn.execute(
                "SELECT id FROM sales_companies WHERE lower(name) = lower(%s) ORDER BY id LIMIT 1", (name,)
            ).fetchone()
        if row:
            cid = row["id"]
            sets, vals = [], []
            # domain/linkedin_url are unique keys - never backfilled here, so a
            # name match can't collide with another company's identity.
            for c in cols:
                v = data.get(c)
                if v not in (None, ""):
                    sets.append(f"{c} = COALESCE({c}, %s)")
                    vals.append(v)
            if data.get("technologies"):
                sets.append("technologies = (SELECT ARRAY(SELECT DISTINCT unnest(technologies || %s::text[])))")
                vals.append(list(data["technologies"]))
            if sets:
                conn.execute(
                    f"UPDATE sales_companies SET {', '.join(sets)}, updated_at = now() WHERE id = %s",
                    (*vals, cid),
                )
            return cid
        return conn.execute(
            f"""INSERT INTO sales_companies (name, domain, linkedin_url, technologies, {', '.join(cols)})
                VALUES (%s, %s, %s, %s, {', '.join(['%s'] * len(cols))}) RETURNING id""",
            (name or domain or li, domain, li, list(data.get("technologies") or []),
             *[data.get(c) for c in cols]),
        ).fetchone()["id"]


# -------------------------------------------------------------- contacts --


def split_name(full: str | None) -> tuple[str | None, str | None]:
    if not full:
        return None, None
    parts = full.strip().split()
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


CONTACT_FIELDS = [
    "first_name", "last_name", "full_name", "job_title", "headline", "profile_url", "location",
    "company_id", "company", "company_url", "website", "industry", "email", "email_status",
    "phone", "intent_type", "intent", "intent_url", "intent_at", "signal_value", "scoring",
    "total_score", "agent_id", "connection_degree", "open_to_work", "notes", "custom",
]


def _normalize_profile_url(u: str | None) -> str | None:
    if not u:
        return None
    u = u.strip().split("?")[0].rstrip("/")
    if "linkedin.com/" in u and not u.startswith("http"):
        u = "https://" + u
    return u.replace("://linkedin.com", "://www.linkedin.com")


def upsert_contact(data: dict[str, Any]) -> tuple[int, bool]:
    """Insert a contact, or return the existing one (matched by LinkedIn
    profile URL, then email). Returns (id, created)."""
    d = dict(data)
    d["profile_url"] = _normalize_profile_url(d.get("profile_url"))
    if not d.get("full_name") and (d.get("first_name") or d.get("last_name")):
        d["full_name"] = " ".join(x for x in (d.get("first_name"), d.get("last_name")) if x)
    if d.get("full_name") and not d.get("first_name"):
        d["first_name"], d["last_name"] = split_name(d["full_name"])
    if d.get("company") and not d.get("company_id"):
        d["company_id"] = upsert_company({
            "name": d["company"], "domain": d.get("website"), "linkedin_url": d.get("company_url"),
            "industry": d.get("industry"),
        })
    with get_conn() as conn:
        row = None
        if d.get("profile_url"):
            row = conn.execute(
                "SELECT id FROM sales_contacts WHERE profile_url = %s", (d["profile_url"],)
            ).fetchone()
        if not row and d.get("email"):
            row = conn.execute(
                "SELECT id FROM sales_contacts WHERE lower(email) = lower(%s) LIMIT 1", (d["email"],)
            ).fetchone()
        if row:
            return row["id"], False
        cols = [c for c in CONTACT_FIELDS if d.get(c) is not None]
        vals = [jsonb(d[c]) if c in ("scoring", "custom") else d[c] for c in cols]
        if d.get("email"):
            cols.append("email_enriched")
            vals.append(True)
        r = conn.execute(
            f"INSERT INTO sales_contacts ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id",
            vals,
        ).fetchone()
        return r["id"], True


def contact_exists(profile_url: str | None) -> bool:
    url = _normalize_profile_url(profile_url)
    if not url:
        return False
    with get_conn() as conn:
        return bool(conn.execute("SELECT 1 FROM sales_contacts WHERE profile_url = %s", (url,)).fetchone())


def get_contact(contact_id: int) -> dict | None:
    with get_conn() as conn:
        c = conn.execute("SELECT * FROM sales_contacts WHERE id = %s", (contact_id,)).fetchone()
        if not c:
            return None
        c["lists"] = [r["list_id"] for r in conn.execute(
            "SELECT list_id FROM sales_list_contacts WHERE contact_id = %s", (contact_id,)
        ).fetchall()]
        c["campaign_status"] = conn.execute(
            "SELECT id, campaign_agent_id, step_id, step_number, type, state, due_at, done_at, "
            "subject, body, error FROM sales_campaign_status WHERE contact_id = %s "
            "ORDER BY campaign_agent_id, step_number",
            (contact_id,),
        ).fetchall()
    return c


_UPDATABLE = set(CONTACT_FIELDS) | {"email_enriched", "phone_enriched", "unsubscribed"}


def update_contact(contact_id: int, fields: dict[str, Any]) -> dict | None:
    sets, vals = [], []
    for k, v in fields.items():
        if k not in _UPDATABLE:
            continue
        sets.append(f"{k} = %s")
        vals.append(jsonb(v) if k in ("scoring", "custom") else v)
    if sets:
        with get_conn() as conn:
            conn.execute(
                f"UPDATE sales_contacts SET {', '.join(sets)}, updated_at = now() WHERE id = %s",
                (*vals, contact_id),
            )
    return get_contact(contact_id)


def reject_contact(contact_id: int, reason: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sales_contacts SET rejected = true, rejected_reason = %s, updated_at = now() WHERE id = %s",
            (reason, contact_id),
        )
        # A rejected lead is never contacted: stop anything still queued.
        conn.execute(
            "UPDATE sales_campaign_status SET state = 'skipped', error = 'contact rejected', updated_at = now() "
            "WHERE contact_id = %s AND state IN ('waiting', 'pending', 'manual')",
            (contact_id,),
        )


def unreject_contact(contact_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sales_contacts SET rejected = false, rejected_reason = NULL, updated_at = now() WHERE id = %s",
            (contact_id,),
        )


def list_contacts(
    *, list_id: int | None = None, agent_id: int | None = None, intent_type: str | None = None,
    search: str | None = None, score_from: float | None = None, score_to: float | None = None,
    date_from: str | None = None, date_to: str | None = None, include_rejected: bool = True,
    page: int = 1, limit: int = 20,
) -> dict:
    where, vals = ["true"], []
    join = ""
    if list_id is not None:
        join = "JOIN sales_list_contacts lc ON lc.contact_id = c.id AND lc.list_id = %s"
        vals.append(list_id)
    if agent_id is not None:
        where.append("c.agent_id = %s")
        vals.append(agent_id)
    if intent_type:
        where.append("c.intent_type = %s")
        vals.append(intent_type)
    if search:
        where.append(
            "(c.full_name ILIKE %s OR c.email ILIKE %s OR c.company ILIKE %s OR c.website ILIKE %s "
            "OR c.location ILIKE %s OR c.job_title ILIKE %s)"
        )
        vals.extend([f"%{search}%"] * 6)
    if score_from is not None:
        where.append("c.total_score >= %s")
        vals.append(score_from)
    if score_to is not None:
        where.append("c.total_score <= %s")
        vals.append(score_to)
    if date_from:
        where.append("c.created_at >= %s::timestamptz")
        vals.append(date_from)
    if date_to:
        where.append("c.created_at <= %s::timestamptz")
        vals.append(date_to)
    if not include_rejected:
        where.append("NOT c.rejected")
    limit = max(1, min(int(limit), 200))
    page = max(1, int(page))
    base = f"FROM sales_contacts c {join} WHERE {' AND '.join(where)}"
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) n {base}", vals).fetchone()["n"]
        items = conn.execute(
            f"SELECT c.* {base} ORDER BY c.created_at DESC, c.id DESC LIMIT %s OFFSET %s",
            (*vals, limit, (page - 1) * limit),
        ).fetchall()
    return {"items": items, "total": total, "page": page, "limit": limit}


def intent_type_counts() -> list[dict]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT intent_type, COUNT(*)::int AS count FROM sales_contacts "
            "WHERE intent_type IS NOT NULL GROUP BY intent_type ORDER BY count DESC"
        ).fetchall()


# ------------------------------------------------------------ CSV import --

_CSV_ALIASES = {
    "first_name": {"first name", "firstname", "first_name"},
    "last_name": {"last name", "lastname", "last_name"},
    "full_name": {"name", "full name", "full_name"},
    "job_title": {"title", "job title", "job_title", "position"},
    "company": {"company", "company name", "organization"},
    "website": {"website", "domain", "company website"},
    "email": {"email", "email address", "e-mail"},
    "phone": {"phone", "phone number", "mobile"},
    "profile_url": {"linkedin", "linkedin url", "profile url", "profile_url", "linkedin profile"},
    "location": {"location", "country", "city"},
    "industry": {"industry"},
}


def import_csv(list_id: int, text: str) -> dict:
    reader = csv.DictReader(io.StringIO(text))
    mapping = {}
    for h in reader.fieldnames or []:
        key = h.strip().lower()
        for field, names in _CSV_ALIASES.items():
            if key in names:
                mapping[h] = field
    created = existing = skipped = 0
    ids = []
    for row in reader:
        d = {mapping[h]: (v or "").strip() or None for h, v in row.items() if h in mapping}
        if not (d.get("profile_url") or d.get("email")) or not (d.get("full_name") or d.get("first_name")):
            skipped += 1
            continue
        d["intent_type"] = "IMPORT"
        cid, new = upsert_contact(d)
        ids.append(cid)
        created += new
        existing += not new
    add_contacts_to_list(list_id, ids)
    return {"created": created, "existing": existing, "skipped": skipped, "mapped_columns": mapping}
