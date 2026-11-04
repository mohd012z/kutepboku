// AI research agent — global, key-free, parallel, fail-open.
//
// Gathers open ebooks (Internet Archive CC facet + Project Gutenberg) AND a
// global tool/source scan (GitHub, GitLab, npm, crates.io, Docker Hub) for a
// subject, then synthesizes one LLM digest. Every source is independent: a
// dead / rate-limited source is dropped and the rest still deliver (allSettled).
// The LLM is fail-open (null on any error) — the raw verified sources remain.
//
// Designed for Cloudflare Worker CPU limits: sources run in parallel with short
// AbortSignal timeouts; no per-item license re-fetch (IA is pre-filtered to the
// strict CC-BY facet in the query, a lighter gate than the poller's licensed()).

const USER_AGENT =
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36";

function head(extra = {}) {
  return { "user-agent": USER_AGENT, ...extra };
}

function withParams(url, params) {
  const kept = Object.entries(params || {}).filter(([, v]) => v != null && v !== "");
  if (!kept.length) return url;
  const q = kept.map(([k, v]) => encodeURIComponent(k) + "=" + encodeURIComponent(v)).join("&");
  return url + (url.includes("?") ? "&" : "?") + q;
}

async function getJson(url, { headers, timeout = 8000, params } = {}) {
  const r = await fetch(withParams(url, params), {
    headers: head(headers),
    signal: AbortSignal.timeout(timeout),
  });
  if (!r.ok) throw new Error("HTTP " + r.status + " " + url);
  return r.json();
}

async function getText(url, { headers, timeout = 8000, params } = {}) {
  const r = await fetch(withParams(url, params), {
    headers: head(headers),
    signal: AbortSignal.timeout(timeout),
  });
  if (!r.ok) throw new Error("HTTP " + r.status + " " + url);
  return r.text();
}

// ---- global sources (tools / packages / repos) ----------------------------

async function searchGithub(query, limit) {
  const res = await getJson("https://api.github.com/search/repositories", {
    params: { q: query, sort: "stars", order: "desc", per_page: String(limit) },
    headers: { accept: "application/vnd.github+json" },
  });
  return (res.items || [])
    .filter((it) => it.full_name && it.full_name.split("/").length === 2)
    .map((it) => ({ id: it.full_name, url: "https://github.com/" + it.full_name,
      desc: (it.description || "").trim(), count: it.stargazers_count || 0 }));
}

async function searchGitlab(query, limit) {
  const res = await getJson("https://gitlab.com/api/v4/projects", {
    params: { search: query, per_page: String(limit), order_by: "star_count", sort: "desc" },
  });
  return (res || [])
    .filter((p) => p.path_with_namespace && (p.star_count || 0) >= 1 &&
      !/deletion/i.test(p.path_with_namespace))
    .map((p) => ({ id: p.path_with_namespace,
      url: p.web_url || "https://gitlab.com/" + p.path_with_namespace,
      desc: (p.description || "").trim(), count: p.star_count || 0 }));
}

async function searchNpm(query, limit) {
  const res = await getJson("https://registry.npmjs.org/-/v1/search", {
    params: { text: query, size: String(limit), sort: "downloads" },
    headers: { accept: "application/vnd.npm.install-v1+json" },
  });
  return (res.objects || [])
    .map((o) => { const p = o.package || {};
      return p.name ? { id: p.name, url: "https://www.npmjs.com/package/" + p.name,
        desc: (p.description || "").trim(), count: (o.downloads || {}).monthly || 0 } : null; })
    .filter(Boolean);
}

async function searchCrates(query, limit) {
  const res = await getJson("https://crates.io/api/v1/crates", {
    params: { q: query, per_page: String(limit) },
  });
  return (res.crates || [])
    .map((c) => c.name && (c.downloads || 0) >= 1000
      ? { id: c.name, url: c.repository_url || c.homepage || "https://crates.io/crates/" + c.name,
        desc: (c.description || "").trim(), count: c.downloads || 0 }
      : null)
    .filter(Boolean);
}

async function searchDocker(query, limit) {
  const res = await getJson("https://hub.docker.com/v2/search/repositories/", {
    params: { query, page_size: String(limit) },
  });
  return (res.results || [])
    .map((r) => r.repo_name
      ? { id: r.repo_name, url: "https://hub.docker.com/r/" + r.repo_name,
        desc: (r.short_description || "").trim(), count: r.pull_count || 0 }
      : null)
    .filter(Boolean);
}

const GLOBAL_SOURCES = [
  ["github", searchGithub],
  ["gitlab", searchGitlab],
  ["npm", searchNpm],
  ["crates", searchCrates],
  ["docker", searchDocker],
];

// Returns {sourceKey: [item,...]} for the non-empty sources. Fail-open: any
// rejected/failed source is simply absent from the result.
export async function gatherGlobal(query, limit = 4) {
  if (!query || !query.trim()) return {};
  const q = query.trim().slice(0, 80);
  const out = {};
  const settled = await Promise.allSettled(
    GLOBAL_SOURCES.map(([key, fn]) => fn(q, limit)));
  settled.forEach((r, i) => {
    if (r.status === "fulfilled" && Array.isArray(r.value) && r.value.length) {
      out[GLOBAL_SOURCES[i][0]] = r.value.slice(0, limit);
    }
  });
  return out;
}

// ---- open ebooks (IA strict-CC facet + Gutenberg public domain) -----------

function parseGutenberg(xml, limit) {
  const out = [];
  const entries = xml.split(/<entry[\s>]/).slice(1);
  for (const e of entries) {
    const title = (e.match(/<title[^>]*>([^<]*)<\/title>/) || [])[1];
    const idm = e.match(/ebooks\/(\d+)\.opds/);
    if (!idm) continue;
    out.push({ id: "gutenberg-" + idm[1],
      url: "https://www.gutenberg.org/ebooks/" + idm[1],
      desc: (title || "").trim(), count: 0, source: "Gutenberg" });
    if (out.length >= limit) break;
  }
  return out;
}

async function searchEbooks(query, limit = 6) {
  if (!query || !query.trim()) return [];
  const q = query.trim().slice(0, 80);
  const out = [];
  const ia = (async () => {
    try {
      const res = await getJson("https://archive.org/advancedsearch.php", {
        params: { output: "json", rows: String(limit),
          fl: "identifier,title,author_name,year",
          q: "(" + q + " license:cc-by-4.0 format:(epub OR pdf)" },
      });
      for (const doc of res.response?.docs || []) {
        if (!doc.identifier) continue;
        out.push({ id: "ia-" + doc.identifier,
          url: "https://archive.org/details/" + doc.identifier,
          desc: (doc.title || "") + (doc.author_name ? " — " +
            (Array.isArray(doc.author_name) ? doc.author_name.join(", ") : String(doc.author_name)) : ""),
          count: 0, source: "IA (CC-BY)" });
        if (out.length >= limit * 2) break;
      }
    } catch { /* fail-open */ }
  })();
  const gutenberg = (async () => {
    try {
      const xml = await getText("https://m.gutenberg.org/ebooks/search.opds/", {
        params: { query: q },
        headers: { accept: "application/atom+xml" },
      });
      return parseGutenberg(xml, limit);
    } catch { return []; }
  })();
  const [iaList, gList] = await Promise.all([ia, gutenberg]);
  (gList || []).forEach((g) => { if (out.length < limit * 2) out.push(g); });
  return out.slice(0, limit * 2);
}

// Deterministic field summary — the worker is the agent, so this works with
// ZERO external AI services (no Minda). Overview from verified source stats,
// key resources = top-count sources with their registry descriptions.
export function deterministicDigest(topic, sources) {
  const all = [];
  for (const [key, items] of Object.entries(sources || {})) {
    for (const it of items) all.push({ key, id: it.id, desc: it.desc || "", count: it.count || 0 });
  }
  const n = all.length;
  if (!n) {
    return "OVERVIEW: No sources were found in the public registries just now.\n" +
      "NOTES: The subject may be too narrow, or a registry was rate-limited.";
  }
  const keys = [...new Set(all.map((a) => a.key))];
  const top = [...all].sort((a, b) => b.count - a.count).slice(0, 5);
  const lines = ["OVERVIEW:"];
  lines.push("- Verified sources: " + n + " across " + keys.length +
    " registries (" + keys.join(", ") + ").");
  const best = top[0];
  if (best.count) {
    lines.push("- Most-used in the field: " + best.id + " (" + best.key + ", " +
      best.count + " popularity).");
  }
  lines.push("- Descriptions below are the registries' own; verify before adopting.");
  lines.push("");
  lines.push("KEY RESOURCES:");
  for (const t of top) lines.push("- " + t.id + " [" + t.key + "] — " +
    (t.desc || "no description").slice(0, 90));
  lines.push("");
  lines.push("NOTES: Deterministic Worker digest (no external AI service); " +
    "counts are registry popularity, not endorsements.");
  return lines.join("\n").slice(0, 1200);
}

// One LLM digest pass. Used ONLY when env.MINDA_BASE_URL + MINDA_API_KEY are
// set — otherwise research falls back to deterministicDigest. Fail-open null.
export async function researchDigest(topic, sources, { base, apiKey, model, timeout = 20000 } = {}) {
  if (!base || !apiKey) return null;
  const lines = [];
  for (const [key, items] of Object.entries(sources || {})) {
    for (const it of items) lines.push("[" + key + "] " + it.id + " — " + (it.desc || ""));
  }
  if (!lines.length) return null;
  const prompt =
    "You are a research assistant compiling a field digest for Telegram. Using ONLY the " +
    "numbered source list (real packages/repos/images), write a concise digest.\n" +
    "Format, plain text (no markdown headings):\n" +
    "OVERVIEW: 3-4 short bullets on what the topic is and where the field is now.\n" +
    "KEY RESOURCES: up to 5 from the list, each 'name - why it matters' (one line).\n" +
    "NOTES: one line - a caveat, gap, or what is missing.\n" +
    "Keep it under 900 characters total.\n\nTOPIC: " +
    String(topic).slice(0, 120) + "\nSOURCES:\n" +
    lines.slice(0, 40).map((l, i) => (i + 1) + ". " + l.slice(0, 120)).join("\n");
  const r = await fetch(base.replace(/\/$/, "") + "/chat/completions", {
    method: "POST",
    headers: { "content-type": "application/json", authorization: "Bearer " + apiKey },
    body: JSON.stringify({ model, temperature: 0.4, max_tokens: 700,
      chat_template_kwargs: { enable_thinking: false },
      messages: [{ role: "user", content: prompt }] }),
    signal: AbortSignal.timeout(timeout),
  });
  if (!r.ok) throw new Error("LLM HTTP " + r.status);
  const data = await r.json();
  let text = (data?.choices?.[0]?.message?.content || "").trim();
  text = text.replace(/^```(?:text|md)?\s*|\s*```$/g, "").trim();
  return text || null;
}

// ---- the 12 research subjects (matches the bot's category grid) -----------

export const RESEARCH_SUBJECTS = [
  ["ml", "🤖 Machine Learning", "machine learning"],
  ["ai", "🧠 Artificial Intelligence", "artificial intelligence"],
  ["cs", "💻 Computer Science", "computer science"],
  ["math", "📐 Mathematics", "mathematics"],
  ["phys", "⚛️ Physics", "physics"],
  ["chem", "🧪 Chemistry", "chemistry"],
  ["bio", "🧬 Biology", "biology"],
  ["phil", "📜 Philosophy", "philosophy"],
  ["hist", "🏛️ History", "history"],
  ["econ", "📈 Economics", "economics"],
  ["psych", "🧩 Psychology", "psychology"],
  ["med", "🩺 Medicine", "medicine"],
];

export function subjectTopic(key) {
  const hit = RESEARCH_SUBJECTS.find((s) => s[0] === key);
  return hit ? hit[2] : null;
}

// Research a subject: parallel ebooks + global sources, then one LLM digest.
export async function research(subject, env = {}) {
  const sources = await gatherGlobal(subject, 4);
  const ebooks = await searchEbooks(subject, 4);
  // The Worker IS the agent: deterministic digest always, LLM digest only
  // when MINDA_* secrets are configured (optional enhancement).
  let digest = null;
  if (env.MINDA_BASE_URL && env.MINDA_API_KEY) {
    try {
      digest = await researchDigest(subject, sources, {
        base: env.MINDA_BASE_URL, apiKey: env.MINDA_API_KEY,
        model: env.MINDA_MODEL || "llm_model_fp8",
      });
    } catch { digest = null; }
  }
  const llm = !!digest;
  if (!digest) digest = deterministicDigest(subject, sources);
  const nGlobal = Object.values(sources).reduce((n, v) => n + v.length, 0);
  return { subject, sources, ebooks, digest, llm, nGlobal, nEbooks: ebooks.length };
}

export function researchReport(r) {
  const lines = ["🔬 Research report — " + r.subject, ""];
  lines.push("📚 Open ebooks: " + r.nEbooks);
  lines.push("🌐 Global sources (GitHub/GitLab/npm/crates/Docker): " + r.nGlobal);
  lines.push("");
  if (r.digest) {
    lines.push("🧠 " + (r.llm ? "AI digest (LLM)" : "AI digest (Worker agent)"));
    lines.push(r.digest);
  } else {
    lines.push("🧠 AI digest unavailable just now (LLM off/timeout) — the " +
      "verified sources below are still the findings.");
  }
  // Top verified sources, inlined as plain links (retry-safe, no markup).
  const top = [];
  for (const [key, items] of Object.entries(r.sources)) {
    for (const it of items.slice(0, 2)) top.push("[" + key + "] " + it.id + " — " + it.url);
    if (top.length >= 10) break;
  }
  if (top.length) { lines.push(""); lines.push("Top sources:"); lines.push(...top); }
  if (r.ebooks.length) {
    lines.push(""); lines.push("Open ebooks:");
    lines.push(...r.ebooks.slice(0, 6).map((b) => "• " + (b.desc || b.id) + " — " + b.url));
  }
  if (!r.nGlobal && !r.nEbooks) {
    lines.push(""); lines.push("· No open-licensed ebooks and no registry hits " +
      "matched — try a broader subject.");
  }
  return lines.join("\n").slice(0, 4000);
}

// Inline keyboard for the research subject menu (12 grid + home).
export function researchMenuMarkup() {
  const rows = [];
  for (let i = 0; i < RESEARCH_SUBJECTS.length; i += 2) {
    const row = [];
    for (const s of RESEARCH_SUBJECTS.slice(i, i + 2)) {
      row.push({ text: s[1], callback_data: "res:" + s[0] });
    }
    rows.push(row);
  }
  rows.push([{ text: "🏠 Home", callback_data: "m:menu" }]);
  return { inline_keyboard: rows };
}
