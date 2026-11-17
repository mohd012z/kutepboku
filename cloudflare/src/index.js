export function verifyWebhookSecret(received, expected) {
  if (typeof received !== "string" || typeof expected !== "string" || !expected) return false;
  const a = new TextEncoder().encode(received);
  const b = new TextEncoder().encode(expected);
  let diff = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) diff |= (a[i] ?? 0) ^ (b[i] ?? 0);
  return diff === 0;
}
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health" && request.method === "GET") {
      return Response.json({ status: "staging", telegram: "disabled" });
    }
    if (url.pathname !== "/telegram/webhook" || request.method !== "POST") return new Response("Not found", { status: 404 });
    if (!verifyWebhookSecret(request.headers.get("X-Telegram-Bot-Api-Secret-Token"), env.TELEGRAM_WEBHOOK_SECRET)) {
      return new Response("Unauthorized", { status: 401 });
    }
    return new Response("Staging webhook disabled until D1 inbox is integrated", { status: 503 });
  }
};
