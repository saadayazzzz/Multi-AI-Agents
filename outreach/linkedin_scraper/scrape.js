// Real-time LinkedIn lead search via the user's own logged-in session.
// See outreach/linkedin_scrape.py for the full rationale/warning - this is
// a deliberate ToS-risk exception the user explicitly chose, read-only
// (search + scroll + extract text, never connects/messages/likes/comments).
//
// Two modes:
//   node scrape.js --login              open a real Chrome window, wait for
//                                        the user to log in by hand, save
//                                        the session cookies to session.json
//   node scrape.js "<query>"            headless search, sorted by Latest,
//                                        prints JSON array of posts to stdout
//
// LinkedIn's current UI ships hashed/obfuscated CSS class names (a
// different random hash per deploy) and doesn't render post permalinks as
// real <a href> at all (client-side routing only) - so this can't select
// by class or read a post URL out of the DOM. Instead it anchors on the
// one thing that IS a real, stable href - each author's profile link
// (linkedin.com/in/...) - and walks up the DOM from there to the nearest
// ancestor that also contains the post's own "Like"/"Comment" action bar,
// which is that post's card boundary. The relative time LinkedIn itself
// displays ("15m", "2h") is extracted from that same card's text - this is
// LinkedIn's own authoritative timestamp for a logged-in viewer, which is
// exactly the real-time signal a public search index can't give us.
"use strict";
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const CHROME_PATH = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const SESSION_PATH = path.join(__dirname, "session.json");

const TIME_RE = /(\d+)\s*(m|h|d|w|mo|yr)\b(?!\w)/i;
const UNIT_HOURS = { m: 1 / 60, h: 1, d: 24, w: 24 * 7, mo: 24 * 30, yr: 24 * 365 };

function parseRelativeTime(text) {
  const m = text.match(TIME_RE);
  if (!m) return { relative: null, ageDays: null };
  const qty = Number(m[1]);
  const unit = m[2].toLowerCase();
  const hours = qty * (UNIT_HOURS[unit] ?? 1);
  return { relative: m[0], ageDays: Math.round((hours / 24) * 10) / 10 };
}

async function login() {
  const browser = await chromium.launch({ executablePath: CHROME_PATH, headless: false });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  await page.goto("https://www.linkedin.com/login", { waitUntil: "domcontentloaded", timeout: 90000 });

  const deadline = Date.now() + 300000;
  let loggedIn = false;
  while (Date.now() < deadline) {
    if (page.url().includes("/feed")) {
      loggedIn = true;
      break;
    }
    await page.waitForTimeout(1500);
  }
  if (loggedIn) {
    await ctx.storageState({ path: SESSION_PATH });
    console.error("Session saved to " + SESSION_PATH);
  } else {
    console.error("Login timed out - no session saved.");
  }
  await browser.close();
  process.exit(loggedIn ? 0 : 1);
}

async function search(query, maxPosts) {
  if (!fs.existsSync(SESSION_PATH)) {
    console.error("NO_SESSION");
    process.exit(2);
  }
  const browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true });
  const ctx = await browser.newContext({
    storageState: SESSION_PATH,
    viewport: { width: 1280, height: 1400 },
  });
  const page = await ctx.newPage();
  // Images/fonts/media are dead weight for text extraction and roughly
  // halve load time on a slow connection - this project has hit
  // unreliable bandwidth more than once.
  await page.route("**/*", (route) => {
    const t = route.request().resourceType();
    if (t === "image" || t === "media" || t === "font") route.abort();
    else route.continue();
  });

  const url =
    "https://www.linkedin.com/search/results/content/?keywords=" +
    encodeURIComponent(query) +
    '&sortBy=%22date_posted%22';
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForTimeout(6000);
  for (let i = 0; i < 6; i++) {
    await page.mouse.wheel(0, 2200);
    await page.waitForTimeout(2200 + Math.floor(Math.random() * 900));
  }

  const raw = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll('a[href*="linkedin.com/in/"]'));
    const seen = new Set();
    const out = [];
    for (const link of links) {
      const href = link.href.split("?")[0];
      if (seen.has(href)) continue;
      let node = link;
      let container = null;
      for (let i = 0; i < 12 && node; i++) {
        node = node.parentElement;
        if (!node) break;
        const txt = node.innerText || "";
        if (txt.includes("Comment") && txt.includes("Like") && txt.length > 100) {
          container = node;
          break;
        }
      }
      if (!container) continue;
      const nameEl = link.querySelector("img[alt]");
      const author = nameEl ? (nameEl.getAttribute("alt") || "").replace(/^View |.s profile$/gi, "").trim() : null;
      // Bare single-word/broad queries surface non-post cards too (group,
      // event, "people also viewed" suggestions) that happen to contain a
      // profile link but aren't an actual post - no extractable author
      // name is the reliable tell, so drop those rather than pass junk to
      // the LLM.
      if (!author || /open to work|profile$/i.test(author)) continue;
      seen.add(href);
      out.push({ profileUrl: href, author, text: container.innerText.slice(0, 2500) });
    }
    return out;
  });

  const out = [];
  for (const p of raw) {
    const { relative, ageDays } = parseRelativeTime(p.text);
    out.push({
      author: p.author || null,
      profile_url: p.profileUrl,
      post_url: p.profileUrl,
      text: p.text,
      relative_time: relative,
      real_posted_at: null,
      age_days: ageDays,
    });
    if (out.length >= maxPosts) break;
  }

  await browser.close();
  console.log(JSON.stringify(out));
}

const args = process.argv.slice(2);
if (args.includes("--login")) {
  login().catch((e) => {
    console.error("FAIL " + e.message);
    process.exit(1);
  });
} else {
  const query = args[0] || "founder hiring is chaos";
  const maxPosts = Number(args[1] || 10);
  search(query, maxPosts).catch((e) => {
    console.error("FAIL " + e.message);
    process.exit(1);
  });
}
