export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health" && request.method === "GET") {
      return Response.json({ service: "msasoup-telegram", status: "configured" });
    }
    if (url.pathname !== "/telegram" || request.method !== "POST") return new Response("Not found", { status: 404 });
    const provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token") || "";
    if (!env.TELEGRAM_WEBHOOK_SECRET || !env.TELEGRAM_BOT_TOKEN || !constantTimeEqual(provided, env.TELEGRAM_WEBHOOK_SECRET))
      return new Response("Unauthorized", { status: 401 });
    if (Number(request.headers.get("content-length") || 0) > 65536) return new Response("Too large", { status: 413 });
    let update;
    try { update = await request.json(); } catch { return new Response("Bad JSON", { status: 400 }); }
    if (!Number.isSafeInteger(update?.update_id)) return new Response("Bad update", { status: 400 });
    const message = update.message;
    if (!message?.chat?.id || typeof message.text !== "string") return new Response("OK");
    const command = message.text.split(/\s+/)[0].split("@")[0].toLowerCase();
    const replies = {
      "/start": "Welcome to MSASoup 📚\nUse /menu for commands.",
      "/menu": "📚 MSASoup\n/start — Welcome\n/help — Help\n/status — Worker status\n/search — Search information",
      "/help": "Use /menu to see commands. The research engine is not yet connected to this Worker.",
      "/status": "MSASoup webhook receiver is online. Research and delivery status are separate.",
      "/search": "Search is not yet connected to the Cloudflare Worker. No search has been started."
    };
    const text = replies[command];
    if (!text) return new Response("OK");
    const response = await fetch("https://api.telegram.org/bot" + env.TELEGRAM_BOT_TOKEN + "/sendMessage", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: message.chat.id, text })
    });
    if (!response.ok) return new Response("Telegram unavailable", { status: 503 });
    const result = await response.json();
    return new Response(result.ok ? "OK" : "Telegram rejected message", { status: result.ok ? 200 : 503 });
  }
};
function constantTimeEqual(a,b) {
  const x=new TextEncoder().encode(a), y=new TextEncoder().encode(b);
  let diff=x.length ^ y.length;
  for(let i=0;i<Math.max(x.length,y.length);i++) diff|=(x[i]||0)^(y[i]||0);
  return diff===0;
}
