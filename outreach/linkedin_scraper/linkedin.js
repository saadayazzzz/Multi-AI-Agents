// LinkedIn browser automation for the sales engine (sales/linkedin.py).
//
// Same approach as scrape.js: a real Chrome driven by playwright-core with
// the user's own saved session (storageState). Every call is one mode:
//
//   node linkedin.js <mode> '<json args>'
//
// and prints one JSON value to stdout. Exit code 2 = no session file,
// 3 = LinkedIn logged us out / showed a checkpoint (session needs a fresh
// login), anything else non-zero = failure with the message on stderr.
//
// READ modes (sourcing signals + inbox): search_posts, post_engagers,
// profile_posts, profile_views, company_followers, search_people,
// search_events, event_attendees, search_groups, group_posts, search_jobs,
// profile, company, inbox, thread.
// WRITE modes (campaign steps): invite, message, visit, like_posts, reply.
// sales/linkedin.py refuses to call a WRITE mode unless the seat has
// automation_enabled - see that module for why it's opt-in.
//
// LinkedIn ships hashed class names that change per deploy, so selectors
// here lean on what is stable: hrefs (/in/, /company/, /messaging/thread/),
// aria-labels, visible button text and activity URNs in the markup.
"use strict";
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const DEFAULT_SESSION = path.join(__dirname, "session.json");
const WIN_CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

function chromePath() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  if (fs.existsSync(WIN_CHROME)) return WIN_CHROME;
  for (const p of ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser", "/opt/pw-browsers/chromium"]) {
    if (fs.existsSync(p)) return p;
  }
  return undefined; // let playwright try its default channel
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = (lo, hi) => sleep(lo + Math.floor(Math.random() * (hi - lo)));

const TIME_RE = /(\d+)\s*(m|h|d|w|mo|yr)\b(?!\w)/i;
const UNIT_HOURS = { m: 1 / 60, h: 1, d: 24, w: 24 * 7, mo: 24 * 30, yr: 24 * 365 };
function parseRelativeTime(text) {
  const m = (text || "").match(TIME_RE);
  if (!m) return { relative: null, ageDays: null };
  const hours = Number(m[1]) * (UNIT_HOURS[m[2].toLowerCase()] ?? 1);
  return { relative: m[0], ageDays: Math.round((hours / 24) * 10) / 10 };
}

function activityDate(urn) {
  // LinkedIn activity ids are Snowflake-style: top 41 bits = ms since epoch.
  const m = /(\d{15,})/.exec(urn || "");
  if (!m) return null;
  try {
    const ms = Number(BigInt(m[1]) >> 22n);
    const d = new Date(ms);
    if (d.getFullYear() < 2010 || d > new Date()) return null;
    return d.toISOString();
  } catch (_) {
    return null;
  }
}

class NoSession extends Error {}
class LoggedOut extends Error {}

async function open(args, { headless = true } = {}) {
  const session = args.session || DEFAULT_SESSION;
  if (!fs.existsSync(session)) throw new NoSession("no session file " + session);
  const browser = await chromium.launch({ executablePath: chromePath(), headless });
  const ctx = await browser.newContext({ storageState: session, viewport: { width: 1280, height: 1400 } });
  const page = await ctx.newPage();
  if (!args.keep_media) {
    await page.route("**/*", (route) => {
      const t = route.request().resourceType();
      if (t === "image" || t === "media" || t === "font") route.abort();
      else route.continue();
    });
  }
  return { browser, ctx, page, session };
}

async function go(page, url, wait = 5000) {
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForTimeout(wait);
  const u = page.url();
  if (/\/(login|uas\/login|checkpoint|authwall)/.test(u)) throw new LoggedOut("redirected to " + u);
}

async function scroll(page, times = 5) {
  for (let i = 0; i < times; i++) {
    await page.mouse.wheel(0, 2000);
    await jitter(1500, 2600);
  }
}

// ------------------------------------------------------------- extraction --

// Post cards: anchored on author profile links + the card's own action bar,
// same heuristic scrape.js proved out, plus the activity URN for a real
// permalink and decoded timestamp.
async function extractPostCards(page, max) {
  const raw = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll('a[href*="/in/"], a[href*="/company/"]'));
    const seenCards = new Set();
    const out = [];
    for (const link of links) {
      let node = link;
      let card = null;
      for (let i = 0; i < 14 && node; i++) {
        node = node.parentElement;
        if (!node) break;
        const txt = node.innerText || "";
        if (txt.includes("Comment") && txt.includes("Like") && txt.length > 100) {
          card = node;
          break;
        }
      }
      if (!card || seenCards.has(card)) continue;
      seenCards.add(card);
      const html = card.outerHTML;
      const urn = (html.match(/urn:li:activity:\d+/) || [null])[0];
      const img = link.querySelector("img[alt]");
      let author = img ? (img.getAttribute("alt") || "") : (link.innerText || "").split("\n")[0];
      author = author.replace(/^View\s+/i, "").replace(/[’']s\s+profile.*$/i, "").replace(/,\s*graphic\.?$/i, "").trim();
      const lines = (card.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean);
      const idx = lines.findIndex((l) => author && l.startsWith(author));
      out.push({
        author: author || null,
        author_url: link.href.split("?")[0],
        headline: idx >= 0 ? lines.slice(idx + 1, idx + 4).find((l) => !/^•|followers|^\d/.test(l) && l.length > 3) || null : null,
        urn,
        text: (card.innerText || "").slice(0, 3000),
      });
    }
    return out;
  });
  const out = [];
  for (const p of raw) {
    if (!p.author || /open to work/i.test(p.author)) continue;
    const t = parseRelativeTime(p.text);
    out.push({
      author: p.author,
      profile_url: p.author_url,
      headline: p.headline,
      post_url: p.urn ? "https://www.linkedin.com/feed/update/" + p.urn + "/" : null,
      posted_at: activityDate(p.urn),
      relative_time: t.relative,
      age_days: p.urn && activityDate(p.urn)
        ? Math.round(((Date.now() - new Date(activityDate(p.urn))) / 86400000) * 10) / 10
        : t.ageDays,
      text: p.text,
    });
    if (out.length >= max) break;
  }
  return out;
}

// People rows (search results, reactions modal, profile viewers, attendees):
// every distinct /in/ link with the text block around it.
async function extractPeople(page, max, rootSelector) {
  return page.evaluate(
    ({ max, rootSelector }) => {
      const root = (rootSelector && document.querySelector(rootSelector)) || document;
      const out = [];
      const seen = new Set();
      for (const a of root.querySelectorAll('a[href*="/in/"]')) {
        const href = a.href.split("?")[0].replace(/\/$/, "");
        if (seen.has(href) || /\/in\/me$/.test(href)) continue;
        let block = a;
        for (let i = 0; i < 6 && block.parentElement; i++) {
          block = block.parentElement;
          if ((block.innerText || "").split("\n").filter(Boolean).length >= 3) break;
        }
        const lines = (block.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean);
        let name = (a.innerText || "").split("\n")[0].trim();
        const img = a.querySelector("img[alt]");
        if (!name && img) name = img.getAttribute("alt") || "";
        name = name.replace(/^View\s+/i, "").replace(/[’']s\s+profile.*$/i, "").replace(/\s*•.*$/, "").trim();
        if (!name || name.length > 80 || /^(Status|LinkedIn Member)/i.test(name)) continue;
        seen.add(href);
        const rest = lines.filter((l) => !l.startsWith(name));
        const degree = (block.innerText.match(/\b(1st|2nd|3rd)\b/) || [null])[0];
        out.push({
          full_name: name,
          profile_url: href,
          headline: rest.find((l) => l.length > 3 && !/^(•|·)|degree|connection|Connect|Message|Follow/i.test(l)) || null,
          location: rest.find((l, i) => i > 0 && /,|Area|Region|Pakistan|India|United|Australia|Canada|Germany|France/.test(l) && l.length < 80) || null,
          connection_degree: degree ? Number(degree[0]) : null,
          context: lines.join(" | ").slice(0, 600),
        });
        if (out.length >= max) break;
      }
      return out;
    },
    { max, rootSelector }
  );
}

// ------------------------------------------------------------- READ modes --

async function search_posts(a) {
  const { browser, page } = await open(a);
  try {
    const url = "https://www.linkedin.com/search/results/content/?keywords=" +
      encodeURIComponent(a.query) + "&sortBy=%22date_posted%22" + (a.date_posted ? "&datePosted=%22" + a.date_posted + "%22" : "");
    await go(page, url, 6000);
    await scroll(page, a.scrolls || 6);
    return await extractPostCards(page, a.max || 20);
  } finally {
    await browser.close();
  }
}

async function post_engagers(a) {
  const { browser, page } = await open(a);
  try {
    await go(page, a.post_url, 5000);
    const kind = a.kind || "comments";
    if (kind === "reactions") {
      const btn = page.locator('button[aria-label*="reaction" i], button:has-text("reactions")').first();
      if (!(await btn.count())) return [];
      await btn.click();
      await page.waitForTimeout(3000);
      for (let i = 0; i < 6; i++) {
        await page.evaluate(() => {
          const d = document.querySelector('[role="dialog"] .artdeco-modal__content, [role="dialog"]');
          if (d) d.scrollTop = d.scrollHeight;
        });
        await jitter(1200, 2000);
      }
      const ppl = await extractPeople(page, a.max || 50, '[role="dialog"]');
      return ppl.map((p) => ({ ...p, engagement: "reaction" }));
    }
    // comments: expand a few "load more" rounds then read commenter links
    for (let i = 0; i < 4; i++) {
      const more = page.locator('button:has-text("Load more comments"), button:has-text("more comments")').first();
      if (!(await more.count())) break;
      await more.click().catch(() => {});
      await jitter(1500, 2500);
    }
    const author = await page.evaluate(() => {
      const a = document.querySelector('a[href*="/in/"], a[href*="/company/"]');
      return a ? a.href.split("?")[0].replace(/\/$/, "") : null;
    });
    const ppl = await extractPeople(page, (a.max || 50) + 1, null);
    return ppl.filter((p) => p.profile_url !== author).slice(0, a.max || 50).map((p) => ({ ...p, engagement: "comment" }));
  } finally {
    await browser.close();
  }
}

function activityUrl(u) {
  u = u.split("?")[0].replace(/\/$/, "");
  if (/\/company\//.test(u)) return u + "/posts/?feedView=all";
  if (/\/in\//.test(u)) return u + "/recent-activity/all/";
  return u;
}

async function profile_posts(a) {
  const { browser, page } = await open(a);
  try {
    await go(page, activityUrl(a.url), 6000);
    await scroll(page, a.scrolls || 4);
    // On an author's own activity page every card is theirs; keep URNs.
    const urns = await page.evaluate(() => Array.from(new Set((document.body.innerHTML.match(/urn:li:activity:\d+/g) || []))));
    return urns.slice(0, a.max || 5).map((u) => ({
      post_url: "https://www.linkedin.com/feed/update/" + u + "/",
      posted_at: activityDate(u),
    }));
  } finally {
    await browser.close();
  }
}

async function profile_views(a) {
  const { browser, page } = await open(a);
  try {
    await go(page, "https://www.linkedin.com/me/profile-views/", 6000);
    await scroll(page, 4);
    return await extractPeople(page, a.max || 50, "main");
  } finally {
    await browser.close();
  }
}

async function company_followers(a) {
  // Admin-only page; returns [] if the seat isn't a page admin.
  const { browser, page } = await open(a);
  try {
    const id = (a.url.match(/company\/([^/]+)/) || [])[1];
    await go(page, "https://www.linkedin.com/company/" + id + "/admin/analytics/followers/", 6000);
    const btn = page.locator('button:has-text("Show all followers"), a:has-text("Show all followers")').first();
    if (await btn.count()) {
      await btn.click();
      await page.waitForTimeout(3000);
    }
    return await extractPeople(page, a.max || 50, '[role="dialog"]');
  } finally {
    await browser.close();
  }
}

async function search_people(a) {
  const { browser, page } = await open(a);
  try {
    let url = "https://www.linkedin.com/search/results/people/?keywords=" + encodeURIComponent(a.query);
    if (a.network) url += "&network=" + encodeURIComponent(JSON.stringify(a.network));
    await go(page, url, 5000);
    await scroll(page, 2);
    return await extractPeople(page, a.max || 10, "main");
  } finally {
    await browser.close();
  }
}

async function search_events(a) {
  const { browser, page } = await open(a);
  try {
    await go(page, "https://www.linkedin.com/search/results/events/?keywords=" + encodeURIComponent(a.query), 5000);
    return await page.evaluate((max) => {
      const out = [];
      const seen = new Set();
      for (const l of document.querySelectorAll('a[href*="/events/"]')) {
        const href = l.href.split("?")[0];
        if (seen.has(href) || !/\/events\/[^/]+/.test(href)) continue;
        seen.add(href);
        out.push({ url: href, title: (l.innerText || "").trim().split("\n")[0] });
        if (out.length >= max) break;
      }
      return out;
    }, a.max || 5);
  } finally {
    await browser.close();
  }
}

async function event_attendees(a) {
  const { browser, page } = await open(a);
  try {
    await go(page, a.url.replace(/\/$/, "") + "/", 5000);
    // Speakers/hosts are always public; attendee list only once attending.
    const btn = page.locator('a:has-text("attendees"), button:has-text("attendees")').first();
    if (await btn.count()) {
      await btn.click().catch(() => {});
      await page.waitForTimeout(3000);
      await scroll(page, 3);
    }
    return await extractPeople(page, a.max || 50, null);
  } finally {
    await browser.close();
  }
}

async function search_groups(a) {
  const { browser, page } = await open(a);
  try {
    await go(page, "https://www.linkedin.com/search/results/groups/?keywords=" + encodeURIComponent(a.query), 5000);
    return await page.evaluate((max) => {
      const out = [];
      const seen = new Set();
      for (const l of document.querySelectorAll('a[href*="/groups/"]')) {
        const href = l.href.split("?")[0];
        if (seen.has(href) || !/\/groups\/\d+/.test(href)) continue;
        seen.add(href);
        out.push({ url: href, title: (l.innerText || "").trim().split("\n")[0] });
        if (out.length >= max) break;
      }
      return out;
    }, a.max || 5);
  } finally {
    await browser.close();
  }
}

async function group_posts(a) {
  const { browser, page } = await open(a);
  try {
    await go(page, a.url.replace(/\/$/, "") + "/", 6000);
    await scroll(page, 4);
    return await extractPostCards(page, a.max || 20);
  } finally {
    await browser.close();
  }
}

async function search_jobs(a) {
  const { browser, page } = await open(a);
  try {
    let url = "https://www.linkedin.com/jobs/search/?keywords=" + encodeURIComponent(a.query) + "&f_TPR=r2592000";
    if (a.location) url += "&location=" + encodeURIComponent(a.location);
    await go(page, url, 6000);
    await scroll(page, 2);
    return await page.evaluate((max) => {
      const out = [];
      const seen = new Set();
      for (const l of document.querySelectorAll('a[href*="/company/"]')) {
        const href = l.href.split("?")[0].replace(/\/(life|jobs)\/?$/, "");
        const name = (l.innerText || "").trim().split("\n")[0];
        if (!name || seen.has(href)) continue;
        seen.add(href);
        let card = l;
        for (let i = 0; i < 6 && card.parentElement; i++) card = card.parentElement;
        out.push({ company: name, company_url: href, job_context: (card.innerText || "").slice(0, 400) });
        if (out.length >= max) break;
      }
      return out;
    }, a.max || 15);
  } finally {
    await browser.close();
  }
}

async function readProfile(page) {
  return page.evaluate(() => {
    const txt = (el) => (el ? (el.innerText || "").trim() : null);
    const main = document.querySelector("main") || document.body;
    const h1 = main.querySelector("h1");
    const top = h1 ? h1.closest("section") || main : main;
    const topLines = (top.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean);
    const name = txt(h1);
    const i = topLines.indexOf(name);
    const headline = i >= 0 ? topLines.slice(i + 1).find((l) => !/^(·|•)|(1st|2nd|3rd)$|^He\/|^She\/|^They\//.test(l)) : null;
    const degree = ((top.innerText || "").match(/·\s*(1st|2nd|3rd)/) || [])[1] || null;
    const loc = topLines.find((l) => /,/.test(l) && l.length < 90 && l !== headline && !/connections|followers/.test(l)) || null;
    const exp = document.querySelector("#experience");
    const expSection = exp ? exp.closest("section") : null;
    let job_title = null, company = null, company_url = null;
    if (expSection) {
      const firstItem = expSection.querySelector("li");
      if (firstItem) {
        const lines = (firstItem.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean);
        const dedup = lines.filter((l, k) => l !== lines[k - 1]);
        job_title = dedup[0] || null;
        company = (dedup[1] || "").split("·")[0].trim() || null;
      }
      const cl = expSection.querySelector('a[href*="/company/"]');
      company_url = cl ? cl.href.split("?")[0].replace(/\/$/, "") : null;
    }
    const buttons = Array.from(main.querySelectorAll("button")).map((b) => (b.getAttribute("aria-label") || b.innerText || "").trim());
    const pending = buttons.some((b) => /^Pending|withdraw/i.test(b));
    const openToWork = /#OPEN_TO_WORK|Open to work/i.test(main.innerHTML.slice(0, 200000));
    return {
      full_name: name, headline, location: loc, connection_degree: degree ? Number(degree[0]) : null,
      job_title, company, company_url, invitation_pending: pending, open_to_work: openToWork,
      can_message: buttons.some((b) => /^Message/i.test(b)),
    };
  });
}

async function profile(a) {
  const { browser, page } = await open(a);
  try {
    await go(page, a.url, 5000);
    await scroll(page, 2);
    return { profile_url: a.url, ...(await readProfile(page)) };
  } finally {
    await browser.close();
  }
}

async function company(a) {
  const { browser, page } = await open(a);
  try {
    await go(page, a.url.split("?")[0].replace(/\/$/, "") + "/about/", 5000);
    return await page.evaluate(() => {
      const main = document.querySelector("main") || document.body;
      const lines = (main.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean);
      const after = (label) => {
        const i = lines.findIndex((l) => l.toLowerCase() === label);
        return i >= 0 ? lines[i + 1] : null;
      };
      const site = Array.from(main.querySelectorAll("a[href^='http']")).map((x) => x.href).find((h) => !/linkedin\.com/.test(h)) || after("website");
      return {
        name: (main.querySelector("h1") || {}).innerText || null,
        website: site || null,
        industry: after("industry"),
        size: after("company size"),
        headquarters: after("headquarters"),
        company_type: after("type"),
        description: after("overview"),
      };
    });
  } finally {
    await browser.close();
  }
}

async function inbox(a) {
  const { browser, page } = await open(a);
  try {
    await go(page, "https://www.linkedin.com/messaging/", 6000);
    for (let i = 0; i < (a.scrolls || 2); i++) {
      await page.evaluate(() => {
        const l = document.querySelector(".msg-conversations-container__conversations-list, ul[class*=conversations]");
        if (l) l.scrollTop = l.scrollHeight;
      });
      await jitter(1200, 2000);
    }
    return await page.evaluate((max) => {
      const out = [];
      const seen = new Set();
      for (const l of document.querySelectorAll('a[href*="/messaging/thread/"]')) {
        const href = l.href.split("?")[0];
        if (seen.has(href)) continue;
        seen.add(href);
        const li = l.closest("li") || l;
        const lines = (li.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean);
        out.push({
          thread_url: href,
          attendee_full_name: lines[0] || null,
          last_time: lines.find((x) => /^(\d{1,2}:\d{2}|[A-Z][a-z]{2} \d{1,2}|\d+[mhdw]|Yesterday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)/.test(x)) || null,
          preview: lines.slice(1).filter((x) => x.length > 2).slice(-1)[0] || null,
          unread: /unread/i.test(li.className) || !!li.querySelector('[class*="unread"]'),
        });
        if (out.length >= max) break;
      }
      return out;
    }, a.max || 30);
  } finally {
    await browser.close();
  }
}

async function readThread(page, max) {
  return page.evaluate((max) => {
    const items = Array.from(document.querySelectorAll('li[class*="msg-s-message-list__event"], li[class*="event-listitem"]'));
    const out = [];
    let lastSender = null;
    let lastTime = null;
    for (const li of items) {
      const nameEl = li.querySelector('[class*="message-group__name"], [class*="profile-link"]');
      if (nameEl) lastSender = nameEl.innerText.trim();
      const timeEl = li.querySelector("time");
      if (timeEl) lastTime = timeEl.innerText.trim();
      const body = li.querySelector('[class*="event-listitem__body"], p');
      const profile = li.querySelector('a[href*="/in/"]');
      if (!body) continue;
      out.push({
        sender: lastSender,
        sender_url: profile ? profile.href.split("?")[0] : null,
        time: lastTime,
        body: body.innerText.trim(),
        id: li.getAttribute("data-event-urn") || li.id || null,
      });
    }
    return out.slice(-max);
  }, max);
}

async function thread(a) {
  const { browser, page } = await open(a);
  try {
    await go(page, a.url, 5000);
    const me = await page.evaluate(() => {
      const img = document.querySelector('img[class*="global-nav__me-photo"], button[id*="ember"] img[alt]');
      return img ? img.getAttribute("alt") : null;
    });
    return { me, messages: await readThread(page, a.max || 40) };
  } finally {
    await browser.close();
  }
}

// ------------------------------------------------------------ WRITE modes --

async function clickByLabel(page, regex, scope) {
  const root = scope ? page.locator(scope) : page;
  const buttons = root.locator("button, [role='button'], [role='menuitem'], div[aria-label]");
  const n = await buttons.count();
  for (let i = 0; i < n; i++) {
    const b = buttons.nth(i);
    const label = ((await b.getAttribute("aria-label").catch(() => null)) || (await b.innerText().catch(() => "")) || "").trim();
    if (regex.test(label) && (await b.isVisible().catch(() => false))) {
      await b.click();
      return true;
    }
  }
  return false;
}

async function invite(a) {
  const { browser, ctx, page, session } = await open(a);
  try {
    await go(page, a.url, 5000);
    const p = await readProfile(page);
    if (p.connection_degree === 1) return { status: "already_connected", ...p };
    if (p.invitation_pending) return { status: "pending", ...p };
    let ok = await clickByLabel(page, /^Invite .* to connect$|^Connect$/i, "main");
    if (!ok) {
      if (await clickByLabel(page, /^More actions$|^More$/i, "main")) {
        await jitter(800, 1500);
        ok = await clickByLabel(page, /^Invite .* to connect$|^Connect$/i);
      }
    }
    if (!ok) return { status: "connect_unavailable", ...p };
    await jitter(1500, 2500);
    if (a.note) {
      if (await clickByLabel(page, /^Add a note$/i)) {
        await page.locator('textarea[name="message"], [role="dialog"] textarea').first().fill(a.note);
        await jitter(800, 1500);
        ok = await clickByLabel(page, /^Send( invitation)?$|^Send now$/i, '[role="dialog"]');
      } else {
        return { status: "note_unavailable", ...p }; // weekly free-note limit reached
      }
    } else {
      ok = await clickByLabel(page, /^Send without a note$|^Send now$|^Send$/i, '[role="dialog"]');
    }
    await jitter(1500, 2500);
    await ctx.storageState({ path: session });
    return { status: ok ? "sent" : "failed", ...p };
  } finally {
    await browser.close();
  }
}

async function composeAndSend(page, parts, file) {
  const box = page.locator('div[role="textbox"][contenteditable="true"], .msg-form__contenteditable').last();
  await box.waitFor({ timeout: 15000 });
  for (const text of parts) {
    await box.click();
    await page.keyboard.insertText(text);
    await jitter(600, 1200);
    if (file) {
      const input = page.locator('input[type="file"]').last();
      await input.setInputFiles(file);
      await page.waitForTimeout(4000);
      file = null;
    }
    const sent = await clickByLabel(page, /^Send$/i, 'form, [class*="msg-form"]');
    if (!sent) await page.keyboard.press("Enter");
    await jitter(1500, 2800);
  }
}

async function message(a) {
  const { browser, ctx, page, session } = await open(a);
  try {
    await go(page, a.url, 5000);
    const p = await readProfile(page);
    if (!p.can_message) return { status: "not_connected", ...p };
    await clickByLabel(page, /^Message/i, "main");
    await jitter(2000, 3000);
    const parts = a.parts && a.parts.length ? a.parts : [a.text];
    await composeAndSend(page, parts, a.file || null);
    await ctx.storageState({ path: session });
    return { status: "sent", ...p };
  } finally {
    await browser.close();
  }
}

async function visit(a) {
  const { browser, page } = await open(a);
  try {
    await go(page, a.url, 4000);
    await scroll(page, 3);
    await jitter(4000, 9000);
    return { status: "sent", ...(await readProfile(page)) };
  } finally {
    await browser.close();
  }
}

async function like_posts(a) {
  const { browser, page } = await open(a);
  try {
    await go(page, activityUrl(a.url), 6000);
    await scroll(page, 2);
    const likes = page.locator('button[aria-label^="React Like"][aria-pressed="false"], button[aria-label="Like"][aria-pressed="false"]');
    const n = Math.min(await likes.count(), a.n || 1);
    for (let i = 0; i < n; i++) {
      await likes.nth(0).click();
      await jitter(2000, 4000);
    }
    return { status: n ? "sent" : "no_posts", liked: n };
  } finally {
    await browser.close();
  }
}

async function reply(a) {
  const { browser, page } = await open(a);
  try {
    await go(page, a.thread_url, 5000);
    await composeAndSend(page, a.parts && a.parts.length ? a.parts : [a.text], a.file || null);
    return { status: "sent" };
  } finally {
    await browser.close();
  }
}

// ------------------------------------------------------------------ login --

async function login(a) {
  const session = a.session || DEFAULT_SESSION;
  const browser = await chromium.launch({ executablePath: chromePath(), headless: false });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  await page.goto("https://www.linkedin.com/login", { waitUntil: "domcontentloaded", timeout: 90000 });
  const deadline = Date.now() + (a.timeout_ms || 300000);
  while (Date.now() < deadline) {
    if (page.url().includes("/feed")) {
      await ctx.storageState({ path: session });
      await browser.close();
      return { status: "saved", session };
    }
    await sleep(1500);
  }
  await browser.close();
  return { status: "timeout" };
}

const MODES = {
  login, search_posts, post_engagers, profile_posts, profile_views, company_followers,
  search_people, search_events, event_attendees, search_groups, group_posts, search_jobs,
  profile, company, inbox, thread, invite, message, visit, like_posts, reply,
};

async function main() {
  const [mode, json] = process.argv.slice(2);
  const fn = MODES[mode];
  if (!fn) {
    console.error("unknown mode " + mode);
    process.exit(64);
  }
  let args = {};
  if (json) args = JSON.parse(json.startsWith("@") ? fs.readFileSync(json.slice(1), "utf8") : json);
  try {
    const out = await fn(args);
    process.stdout.write(JSON.stringify(out));
  } catch (e) {
    console.error(e.message);
    process.exit(e instanceof NoSession ? 2 : e instanceof LoggedOut ? 3 : 1);
  }
}

if (require.main === module) main();

module.exports = { parseRelativeTime, activityDate, activityUrl };
