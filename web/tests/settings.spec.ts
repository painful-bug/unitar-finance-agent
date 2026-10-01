import { expect, test } from "@playwright/test";

test("acknowledges confirmation of existing default rules and restores them after reload", async ({ page }) => {
  await page.goto("/settings");
  await page.getByRole("button", { name: "Use defaults" }).click();
  await expect(page.getByText("All changes saved")).toBeVisible();
  const text = await page.getByLabel("Natural-language rules").inputValue();
  await page.getByRole("button", { name: "Parse rules" }).click();
  await expect(page.getByRole("heading", { name: "Compiled preview" })).toBeVisible();
  await page.getByRole("button", { name: "Confirm these rules" }).click();
  await expect(page.getByText("Rules confirmed and saved for every chat.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Compiled preview" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Confirm these rules" })).toHaveCount(0);
  await page.reload();
  await expect(page.getByLabel("Natural-language rules")).toHaveValue(text);
  await expect(page.locator(".active-rules .rule-list article")).toHaveCount(3);
});

const ledger = (name: string, amount: number, date = "2026-08-30") => ({ name, mimeType: "text/csv", buffer: Buffer.from(`date,kind,category,amount\n${date},income,salary,${amount}\n2026-08-01,expense,dining,200\n`) });

test("uploads, replaces, and resets ledgers without losing visible history", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Agent service connected")).toBeVisible();
  await expect(page.getByRole("button", { name: "Choose CSV" })).toBeVisible();
  await page.screenshot({ path: "/tmp/finance-agent-revamp-chat-light.png" });
  await page.getByLabel("Ledger CSV").setInputFiles(ledger("first.csv", 1000));
  await expect(page.getByRole("heading", { name: "first.csv" })).toBeVisible();
  await page.getByLabel("Ask about your spending, budget, or savings").fill("Check this uploaded ledger");
  await page.getByRole("button", { name: "Send message" }).click();
  const transcript = page.getByRole("region", { name: "Conversation" });
  await expect(transcript.locator(".assistant-message")).toHaveCount(1);
  await expect(transcript.getByText("RM 1000.00")).toBeVisible();
  const savedUrl = page.url();

  await page.getByLabel("Ledger CSV").setInputFiles({ name: "bad.csv", mimeType: "text/csv", buffer: Buffer.from("bad,data") });
  await expect(page.getByRole("alert")).toContainText("CSV missing required columns");
  await expect(page.getByRole("heading", { name: "first.csv" })).toBeVisible();
  await page.getByLabel("Ledger CSV").setInputFiles(ledger("second.csv", 2500));
  await expect(page.getByRole("heading", { name: "second.csv" })).toBeVisible();
  await expect(transcript.locator(".assistant-message")).toHaveCount(1);
  await expect(transcript.getByText(/Ledger changed to second.csv/)).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(savedUrl);
  await expect(page.getByRole("heading", { name: "second.csv" })).toBeVisible();
  await expect(transcript.getByText(/Ledger changed to second.csv/)).toBeVisible();
  await page.getByLabel("Ask about your spending, budget, or savings").fill("Check the replacement ledger");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(transcript.locator(".assistant-message")).toHaveCount(2);
  await expect(transcript.getByText("RM 2500.00")).toBeVisible();
  await page.getByRole("button", { name: "Context", exact: true }).click();
  await page.getByRole("tab", { name: "Model input" }).click();
  await expect(page.locator("#live-context")).not.toContainText("Check this uploaded ledger");
  await page.getByRole("button", { name: "Close context" }).click();
  await page.getByRole("button", { name: "Use bundled data" }).click();
  await expect(page.getByRole("heading", { name: "Bundled demo ledger" })).toBeVisible();
  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.getByRole("heading", { name: "Bundled demo ledger" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Choose CSV" })).toBeVisible();
});

test("uses full-page settings shared across chats and browser contexts", async ({ page, browser }) => {
  await page.goto("/");
  await expect(page.getByText("Agent service connected")).toBeVisible();
  await page.getByLabel("Ask about your spending, budget, or savings").fill("An unsent draft");
  await page.getByRole("button", { name: "Settings", exact: true }).first().click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole("navigation", { name: "Chat history" })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Chat settings" })).toHaveCount(0);
  await page.getByLabel("Compact after turns").fill("25");
  await page.getByLabel("Compact after turns").blur();
  await page.getByLabel("Max agent steps").fill("30");
  await page.getByLabel("Max agent steps").blur();
  await expect(page.getByText("All changes saved")).toBeVisible();
  await page.screenshot({ path: "/tmp/finance-agent-revamp-settings-light.png", fullPage: true });
  await page.getByRole("button", { name: "Dark mode" }).click();
  await page.screenshot({ path: "/tmp/finance-agent-revamp-settings-dark.png", fullPage: true });
  await page.reload();
  await expect(page.getByLabel("Compact after turns")).toHaveValue("25");
  await expect(page.getByLabel("Max agent steps")).toHaveValue("30");

  const otherContext = await browser.newContext();
  try {
    const other = await otherContext.newPage();
    await other.goto("http://127.0.0.1:4173/settings");
    await expect(other.getByLabel("Max agent steps")).toHaveValue("30");
    await expect(other.getByLabel("Compact after turns")).toHaveValue("25");
  } finally { await otherContext.close(); }
  await page.getByRole("button", { name: "Back to chat" }).click();
  await page.getByRole("button", { name: "New chat" }).click();
  await page.getByRole("button", { name: "Settings", exact: true }).first().click();
  await expect(page.getByLabel("Max agent steps")).toHaveValue("30");
  await page.getByLabel("Compact after turns").fill("15");
  await page.getByLabel("Compact after turns").blur();
  await page.getByLabel("Max agent steps").fill("15");
  await page.getByLabel("Max agent steps").blur();
  await expect(page.getByText("All changes saved")).toBeVisible();
});

test("allows settings edits during streaming and applies them to the next answer", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Agent service connected")).toBeVisible();
  await page.getByLabel("Ask about your spending, budget, or savings").fill("Trace slowly with settings open");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page).toHaveURL(/\/chat\//);
  await page.getByRole("button", { name: "Settings", exact: true }).first().click();
  await page.getByLabel("Max agent steps").fill("1");
  await page.getByLabel("Max agent steps").blur();
  await expect(page.getByText("All changes saved")).toBeVisible();
  await page.getByRole("button", { name: "Back to chat" }).click();
  const transcript = page.getByRole("region", { name: "Conversation" });
  await expect(transcript.getByText("Deterministic finance answer from the active ledger.")).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("Ask about your spending, budget, or savings").fill("One step only");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(transcript.getByText("Reached the maximum of 1 agent steps without a final answer.")).toBeVisible();
  await page.getByRole("button", { name: "Settings", exact: true }).first().click();
  await page.getByLabel("Max agent steps").fill("15");
  await page.getByLabel("Max agent steps").blur();
  await expect(page.getByText("All changes saved")).toBeVisible();
});

test("keeps full-page settings and uploads usable on mobile in both themes", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Choose CSV" })).toBeVisible();
  await page.screenshot({ path: "/tmp/finance-agent-revamp-chat-mobile.png" });
  await page.getByRole("button", { name: "Settings", exact: true }).last().click();
  await expect(page.getByLabel("Natural-language rules")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: "/tmp/finance-agent-revamp-settings-mobile-light.png", fullPage: true });
  await page.getByRole("button", { name: "Open conversations" }).click();
  await page.getByRole("button", { name: "Dark mode" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Open conversations" })).toBeFocused();
  await page.screenshot({ path: "/tmp/finance-agent-revamp-settings-mobile-dark.png", fullPage: true });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});
