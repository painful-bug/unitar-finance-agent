import { expect, test } from "@playwright/test";

test("uses a newly parsed and confirmed rule in a budget tool", async ({ page }) => {
  await page.goto("/settings");
  await page.getByLabel("Natural-language rules").fill("Save at least 25% of income.");
  await page.getByRole("button", { name: "Parse rules" }).click();
  await expect(page.getByRole("heading", { name: "Compiled preview" })).toBeVisible();
  await page.getByRole("button", { name: "Confirm these rules" }).click();
  await expect(page.getByText("These rules are active for every chat.")).toBeVisible();
  await page.getByRole("button", { name: "Back to chat" }).click();
  await page.getByLabel("Ask about your spending, budget, or savings").fill("Check savings target for July");
  await page.getByRole("button", { name: "Send message" }).click();
  const transcript = page.getByRole("region", { name: "Conversation" });
  await expect(transcript.getByText("Deterministic finance answer from the active ledger.")).toBeVisible();
  await transcript.getByRole("button", { name: "View trace" }).last().click();
  const trace = page.locator("#agent-trace");
  await trace.getByRole("button", { name: "Raw JSON" }).click();
  const [saved] = JSON.parse(await trace.locator("pre").innerText());
  expect(saved.result.status).toBe("ok");
  expect(saved.result.trace[0].tool).toBe("check_budget_rule");
  expect(saved.result.trace[0].result).toMatchObject({ rule_id: "savings_target", limit: "1250.00", compliant: true });
});


test("persists a configured chat across reload and renders readable tool activity", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Agent service connected")).toBeVisible();

  await page.getByRole("button", { name: "Settings" }).last().click();
  await expect(page.getByRole("heading", { name: "Make it work your way." })).toBeVisible();
  await expect(page).toHaveURL(/\/settings$/);
  await page.getByLabel("Natural-language rules").fill("Save at least 25% of income.");
  await page.getByRole("button", { name: "Parse rules" }).click();
  await expect(page.getByRole("heading", { name: "Compiled preview" })).toBeVisible();
  await page.getByRole("button", { name: "Confirm these rules" }).click();
  await expect(page.getByText("These rules are active for every chat.")).toBeVisible();
  await page.getByRole("button", { name: "Back to chat" }).click();

  await page.getByLabel("Ask about your spending, budget, or savings").fill("What is my savings rate?");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("Deterministic finance answer from the active ledger.")).toBeVisible();
  const transcript = page.getByRole("region", { name: "Conversation" });
  await expect(transcript.getByText("Calculated savings rate")).toBeVisible();
  await expect(transcript.getByText("Technical details")).toBeVisible();
  await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/);

  await page.getByRole("button", { name: "Context" }).click();
  const inspector = page.locator("#live-context");
  await expect(inspector).toBeVisible();
  await expect(inspector.getByText(/personal finance assistant/i)).toBeVisible();
  await page.getByRole("tab", { name: "Model input" }).click();
  await expect(inspector.getByText("What is my savings rate?")).toBeVisible();

  const savedUrl = page.url();
  await page.reload();
  await expect(page).toHaveURL(savedUrl);
  await expect(page.getByText("Deterministic finance answer from the active ledger.")).toBeVisible();
  await expect(page.getByRole("button", { name: "What is my savings rate?" })).toBeVisible();
});

test("creates, renames, deletes, and themes chats from the sidebar", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Agent service connected")).toBeVisible();
  await page.getByLabel("Ask about your spending, budget, or savings").fill("Review September spending");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("Deterministic finance answer from the active ledger.")).toBeVisible();

  await page.getByLabel("Actions for Review September spending").click();
  await page.getByRole("button", { name: "Rename" }).click();
  const rename = page.getByLabel("Rename Review September spending");
  await rename.fill("September plan");
  await rename.press("Enter");
  await expect(page.getByRole("button", { name: "September plan" })).toBeVisible();

  await page.getByLabel("Actions for September plan").click();
  await page.getByRole("button", { name: "Delete" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Delete chat?" });
  await expect(dialog).toContainText("September plan");
  await dialog.getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:4173/");
  await expect(page.getByRole("button", { name: "September plan" })).toHaveCount(0);

  await page.getByRole("button", { name: "Dark mode" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("keeps a failed submitted question visible without retrying it", async ({ page }) => {
  let askCalls = 0;
  await page.route("**/mcp", async (route) => {
    const request = route.request();
    if (request.method() === "POST") {
      try {
        const body = request.postDataJSON();
        if (body?.method === "tools/call" && body?.params?.name === "ask_finance_agent") {
          askCalls += 1;
          await route.abort("connectionrefused");
          return;
        }
      } catch {
        // Non-JSON MCP traffic passes through unchanged.
      }
    }
    await route.continue();
  });

  await page.goto("/");
  await expect(page.getByText("Agent service connected")).toBeVisible();
  await page.getByLabel("Ask about your spending, budget, or savings").fill("Keep this failed question");
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(page.getByRole("alert")).toContainText("MCP server unavailable");
  await expect(page.getByText("Keep this failed question")).toBeVisible();
  await expect.poll(() => askCalls).toBe(1);
});

test("uses an off-canvas conversation drawer on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const openConversations = page.getByRole("button", { name: "Open conversations" });
  await openConversations.click();
  await expect(page.getByRole("navigation", { name: "Chat history" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Close conversations" }).last()).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator(".thread-sidebar")).not.toHaveClass(/is-mobile-open/);
  await expect(openConversations).toBeFocused();

  await page.getByRole("button", { name: "Context" }).click();
  const context = page.getByRole("dialog", { name: "Conversation context" });
  await expect(context).toBeVisible();
  await expect(context.getByRole("button", { name: "Close context" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(context).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Context" })).toBeFocused();
});
