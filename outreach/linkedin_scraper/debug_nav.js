const { chromium } = require("playwright-core");
const path = require("path");
const fs = require("fs");

const CHROME_PATH = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true });
  const ctx = await browser.newContext({
    storageState: path.join(__dirname, "session.json"),
    viewport: { width: 1400, height: 1400 },
  });
  const page = await ctx.newPage();
  await page.route("**/*", (route) => {
    const t = route.request().resourceType();
    if (t === "image" || t === "media" || t === "font") route.abort();
    else route.continue();
  });

  await page.goto("https://www.linkedin.com/sales/search/people", {
    waitUntil: "domcontentloaded",
    timeout: 90000,
  });
  await page.waitForTimeout(6000);
  await page.screenshot({ path: "nav_debug.png", fullPage: false });
  console.log("URL:", page.url());
  console.log("title:", await page.title());
  const html = await page.content();
  fs.writeFileSync("nav_debug.html", html);
  console.log("html length:", html.length);
  await browser.close();
})().catch((e) => {
  console.error("FAIL", e.message);
  process.exit(1);
});
