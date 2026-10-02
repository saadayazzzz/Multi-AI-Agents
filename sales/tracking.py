"""Website-visitor agent: the tracking snippet and reverse-IP company match.

The snippet (see sales.agents.tracking_snippet) loads /api/sales/track/<id>.js,
which beacons each page view to /api/sales/track/<id>/hit. The visitor's IP
is resolved to its owning organisation (ipapi.co, free tier); consumer ISPs,
mobile carriers and clouds are dropped because they say nothing about the
visitor's employer. Business visitors on an office network resolve to their
company, which the agent then turns into decision-makers.
"""
from __future__ import annotations

import re

import httpx

from db.database import get_conn

_ISP_WORDS = re.compile(
    r"telecom|communications|broadband|cable|mobile|wireless|cellular|internet|network|isp\b|"
    r"amazon|google|microsoft|azure|cloudflare|digitalocean|ovh|hetzner|akamai|fastly|linode|"
    r"vodafone|verizon|comcast|at&t|t-mobile|orange|telefonica|jazz|zong|ptcl|telenor|airtel|jio",
    re.I,
)

SCRIPT = """(function(){try{var u=%r;var d={u:location.href,r:document.referrer||''};
var x=new XMLHttpRequest();x.open('POST',u,true);x.setRequestHeader('Content-Type','text/plain');
x.send(JSON.stringify(d));}catch(e){}})();"""


def agent_for_tracking_id(tid: str) -> dict | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, agent_type FROM source_agents WHERE tracking_script_id = %s", (tid,)
        ).fetchone()


def script_for(tid: str, base_url: str) -> str:
    return SCRIPT % f"{base_url.rstrip('/')}/api/sales/track/{tid}/hit"


def resolve_org(ip: str) -> tuple[str | None, str | None]:
    """(org name, grouping key) or (None, None) for ISPs / unknown."""
    if not ip or ip.startswith(("127.", "10.", "192.168.", "172.16.", "::1")):
        return None, None
    try:
        r = httpx.get(f"https://ipapi.co/{ip}/json/", timeout=6)
        org = (r.json() or {}).get("org")
    except Exception:  # noqa: BLE001
        return None, None
    if not org or _ISP_WORDS.search(org):
        return None, None
    org = re.sub(r"^AS\d+\s+", "", org).strip()
    key = re.sub(r"[^a-z0-9]+", "-", org.lower()).strip("-")
    return org, key


def record_hit(tid: str, ip: str, page_url: str, referrer: str, user_agent: str) -> bool:
    agent = agent_for_tracking_id(tid)
    if not agent:
        return False
    org, key = resolve_org(ip)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sales_site_visits (agent_id, ip, page_url, referrer, user_agent, org, org_domain) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (agent["id"], ip, page_url[:1000], referrer[:1000], user_agent[:400], org, key),
        )
        conn.execute("UPDATE source_agents SET script_installed = true WHERE id = %s", (agent["id"],))
    return True
