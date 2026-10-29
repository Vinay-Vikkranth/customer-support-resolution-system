/* Isolated headless end-to-end test. Does not touch your everyday browser profile. */
const { chromium } = require("playwright");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, "..");
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "resolvedesk-e2e-"));
const port = 18177;
const python = process.env.PYTHON || "python";
const proc = spawn(
  python,
  [
    "-m",
    "uvicorn",
    "app.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    String(port),
  ],
  {
    cwd: root,
    env: {
      ...process.env,
      PYTHONPATH: path.join(root, ".deps"),
      OPENAI_API_KEY: "",
      RESOLVEDESK_DB: path.join(temporary, "app.db"),
      RESOLVEDESK_TOKEN: "ui-operator",
      RESOLVEDESK_REVIEW_TOKEN: "ui-reviewer",
    },
    stdio: "ignore",
    windowsHide: true,
  },
);
(async () => {
  let browser;
  try {
    let ready = false;
    for (let i = 0; i < 60; i++) {
      try {
        if ((await fetch(`http://127.0.0.1:${port}/health`)).ok) {
          ready = true;
          break;
        }
      } catch {}
      await new Promise((r) => setTimeout(r, 250));
    }
    assert(ready, "Server failed to start");
    browser = await chromium.launch({
      headless: true,
      ...(process.env.CHROME_CHANNEL
        ? { channel: process.env.CHROME_CHANNEL }
        : {}),
    });
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${port}`);
    await page.getByText("Use a local development token").click();
    await page.locator("#token").fill("ui-operator");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page.getByRole("button", { name: /Reporting disappeared/ }).click();
    await page
      .getByRole("button", { name: "✦ Investigate case", exact: true })
      .click();
    await page
      .getByText("A reviewer must approve or reject this proposal.")
      .waitFor();
    assert.equal(
      await page
        .getByRole("button", { name: "Approve proposed action", exact: true })
        .count(),
      0,
    );
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await page.locator("#token").fill("ui-reviewer");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page.getByRole("button", { name: /Reporting disappeared/ }).click();
    await page
      .getByRole("button", { name: "Approve proposed action", exact: true })
      .waitFor();
    await page.getByText("Investigation trace · evidence and checks").click();
    await page.locator("#message").evaluate((e) => (e.hidden = true));
    await page.screenshot({
      path: path.join(root, "docs-dashboard.png"),
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Approve proposed action", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Approve and execute", exact: true })
      .click();
    await page.getByText("Decision saved: resolved", { exact: true }).waitFor();
    await page
      .getByText("Verified resolution reply", { exact: true })
      .waitFor();
    assert(
      !(await page.locator(".draft").innerText()).includes(
        "We have not changed your access",
      ),
    );
    await page.getByText("Case notes · 0").click();
    await page
      .locator('textarea[name="note"]')
      .fill("Verified access with the sandbox member.");
    await page.getByRole("button", { name: "Save note", exact: true }).click();
    await page.getByText("Case notes · 1").waitFor();
    await page.locator("#search").fill("not-present");
    await page.getByText("No cases match your filters.").waitFor();
    await page.locator("#search").fill("");
    await page.getByRole("button", { name: /Please enable reports/ }).click();
    await page
      .getByRole("button", { name: "✦ Investigate case", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Approve proposed action", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Approve and execute", exact: true })
      .click();
    await page
      .getByText("Decision saved: escalated", { exact: true })
      .waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator("#message").evaluate((e) => (e.hidden = true));
    await page.screenshot({
      path: path.join(root, "docs", "mobile.png"),
      fullPage: true,
    });
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
      "Mobile horizontal overflow",
    );
    assert.equal(
      await page.locator("#guide h2").innerText(),
      "What does ResolveDesk actually do?",
    );
    assert.deepEqual(errors, []);
    console.log(
      "PASS: operator investigation, reviewer confirmation, verified resolution, notes, search, escalation, desktop/mobile layout, no JavaScript errors.",
    );
  } finally {
    if (browser) await browser.close();
    proc.kill();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
