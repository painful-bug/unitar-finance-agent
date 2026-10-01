import { expect, test } from "@playwright/test";

test("compacts completed turns once and persists the exact model input", async ({ page }) => {
  await page.goto("/settings");
  await page.getByLabel("Strategy", { exact: true }).selectOption("summary");
  await page.getByLabel("Compact after turns").fill("5");
  await page.getByLabel("Compact after turns").blur();
  await expect(page.getByText("All changes saved")).toBeVisible();
  await page.getByRole("button", { name: "Back to chat" }).click();
  const transcript = page.getByRole("region", { name: "Conversation" });
  for (let turn = 1; turn <= 5; turn++) {
    await page.getByLabel("Ask about your spending, budget, or savings").fill(`Compaction regression request ${turn}`);
    await page.getByRole("button", { name: "Send message" }).click();
    await expect(transcript.locator(".assistant-message")).toHaveCount(turn);
  }
  await transcript.getByRole("button", { name: "View trace" }).last().click();
  const trace = page.locator("#agent-trace");
  await trace.getByRole("button", { name: "Raw JSON" }).click();
  const [saved] = JSON.parse(await trace.locator("pre").innerText());
  expect(saved.result.context.strategy).toBe("summary");
  expect(saved.execution_trace.filter((event: { operation_id: string; state: string }) => event.operation_id.endsWith("-summary-model") && event.state === "started")).toHaveLength(1);
  const modelInput = saved.result.context.after_messages;
  expect(modelInput[1].role).toBe("assistant");
  expect(modelInput.some((message: { content: string }) => message.content === "Compaction regression request 5")).toBe(true);
  expect(modelInput.at(-1).role).toBe("tool");
  await page.getByRole("button", { name: "Close trace" }).click();
  await page.getByRole("button", { name: "Context", exact: true }).click();
  await expect(page.locator("#live-context").getByRole("heading", { name: "Summary compaction" })).toBeVisible();
  await page.getByRole("tab", { name: "Model input" }).click();
  await expect(page.locator("#live-context .is-summary")).toBeVisible();
  await page.screenshot({ path: "/tmp/finance-compaction-fixed.png", fullPage: true });
  await page.reload();
  await transcript.getByRole("button", { name: "View trace" }).last().click();
  await trace.getByRole("button", { name: "Raw JSON" }).click();
  expect(JSON.parse(await trace.locator("pre").innerText())[0].result.context.after_messages).toEqual(modelInput);
  await page.goto("/settings");
  await page.getByLabel("Strategy", { exact: true }).selectOption("auto");
  await page.getByLabel("Compact after turns").fill("15");
  await page.getByLabel("Compact after turns").blur();
  await expect(page.getByText("All changes saved")).toBeVisible();
});
