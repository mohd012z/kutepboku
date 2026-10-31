import test from "node:test";
import assert from "node:assert/strict";
import worker, { verifyWebhookSecret } from "../src/index.js";
test("secret comparison rejects absent and mismatched secrets", () => {
  assert.equal(verifyWebhookSecret("", ""), false);
  assert.equal(verifyWebhookSecret("abc", "abcd"), false);
  assert.equal(verifyWebhookSecret("abc", "abc"), true);
});
test("health is staging-only", async () => {
  const response = await worker.fetch(new Request("https://example.test/health"), {});
  assert.equal(response.status, 200);
  assert.equal((await response.json()).telegram, "disabled");
});
test("webhook denies unauthorized and refuses to acknowledge undurable updates", async () => {
  const url = "https://example.test/telegram/webhook";
  const env = { TELEGRAM_WEBHOOK_SECRET: "secret" };
  assert.equal((await worker.fetch(new Request(url, { method: "POST" }), env)).status, 401);
  assert.equal((await worker.fetch(new Request(url, { method: "POST", headers: { "X-Telegram-Bot-Api-Secret-Token": "secret" } }), env)).status, 503);
});
