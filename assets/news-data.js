/* Public news data adapter; no credentials, tracking, or AI calls. */
(function (root) {
  "use strict";
  const categories = new Set(["companies", "markets", "startups", "banking", "economy",
    "crypto", "etfs", "learn", "protection", "tech", "infrastructure", "personal-finance", "opinion"]);
  const text = (v, n = 50000) => typeof v === "string" ? v.slice(0, n) : "";
  const strings = v => Array.isArray(v) ? v.filter(x => typeof x === "string").slice(0, 100) : [];
  const date = v => /^\d{4}-\d{2}-\d{2}$/.test(v || "") && Number.isFinite(Date.parse(v)) ? v : "";
  function safeURL(v) {
    try {
      const u = new URL(v);
      return ["https:", "http:"].includes(u.protocol) && !u.username && !u.password ? u.href : "";
    } catch { return ""; }
  }
  function article(v) {
    if (!v || typeof v !== "object" || typeof v.id !== "string" ||
        !/^[a-zA-Z0-9_-]{1,160}$/.test(v.id) || typeof v.headline !== "string" ||
        v.status !== "published") return null;
    const a = {id: v.id, status: v.status};
    for (const key of ["headline", "standfirst", "summary", "explanation", "whyItMatters",
      "investorRelevance", "risks", "watchNext", "currencyNote", "country", "region", "type"]) {
      a[key] = text(v[key]);
    }
    a.country ||= "Pan-African";
    a.region ||= "Pan-African";
    a.category = categories.has(v.category) ? v.category : "companies";
    a.kind = v.kind === "syndicated" ? "syndicated" : "editorial";
    a.historical = v.historical === true;
    a.opinion = v.opinion === true;
    for (const key of ["acsDate", "eventDate", "updated"]) a[key] = date(v[key]);
    for (const key of ["body", "companies", "also"]) a[key] = strings(v[key]);
    a.sources = (Array.isArray(v.sources) ? v.sources : []).slice(0, 30).filter(s => s && safeURL(s.url))
      .map(s => ({url: safeURL(s.url), name: text(s.name, 200), title: text(s.title, 500),
        journalist: text(s.journalist, 200), date: date(s.date), checked: date(s.checked),
        primary: s.primary === "primary" ? "primary" : ""}));
    if (a.kind === "syndicated" && !a.sources.length) return null;
    if (/^[a-zA-Z0-9_-]+$/.test(v.image || "")) a.image = v.image;
    if (v.quote && typeof v.quote === "object") {
      a.quote = Object.fromEntries(["text", "speaker", "title", "context"].map(k => [k, text(v.quote[k])]));
    }
    a.publishedAt = Number.isFinite(Date.parse(v.publishedAt)) ? v.publishedAt : null;
    a.collectedAt = Number.isFinite(Date.parse(v.collectedAt)) ? v.collectedAt : null;
    return a;
  }
  function articles(value) {
    if (!Array.isArray(value)) throw new Error("Invalid article data");
    const seen = new Set();
    return value.map(article).filter(a => a && !seen.has(a.id) && seen.add(a.id));
  }
  function rates(value) {
    if (!Array.isArray(value)) return [];
    return value.filter(v => v && v.kind !== "fx" &&
      typeof v.country === "string" && Number.isFinite(v.value) && Number.isFinite(v.prev))
      .map(v => ({country: v.country, value: v.value, prev: v.prev, date: date(v.date),
        article: text(v.article, 160), bank: text(v.bank, 200), instrument: text(v.instrument, 200)}));
  }
  function fx(value) {
    const row = Array.isArray(value) ? value.find(v => v && v.kind === "fx") : null;
    if (!row) return null;
    const numberRows = items => (Array.isArray(items) ? items : [])
      .filter(p => p && Number.isFinite(p.value) && Number.isFinite(p.prev) && p.prev > 0)
      .map(p => ({...p, date: date(p.date), unit: text(p.unit, 30), name: text(p.name, 100),
        code: text(p.code, 20), source: text(p.source, 150)}));
    return {...row, pairs: numberRows(row.pairs), markets: numberRows(row.markets)};
  }
  async function json(url) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(url, {signal: controller.signal, cache: "no-cache"});
      if (!response.ok) throw new Error("HTTP " + response.status);
      return await response.json();
    } finally { clearTimeout(timeout); }
  }
  const cacheKey = config => 'acs.news.v1:' + config.articlesUrl;
  function cached(config) {
    try {
      const value = JSON.parse(root.localStorage.getItem(cacheKey(config)) || 'null');
      if (!value || Date.now() - value.savedAt > 7 * 86400000) return [];
      return articles(value.articles);
    } catch { return []; }
  }
  async function load(config, onArticles) {
    // Start independent requests together. Render headlines before secondary data finishes.
    const local = config.fallbackArticlesUrl ? json(config.fallbackArticlesUrl).catch(() => []) : Promise.resolve([]);
    const secondary = Promise.all([
      json(config.ratesUrl).catch(() => []), json(config.statusUrl).catch(() => null)
    ]);
    let fallback = false, raw;
    try {
      raw = await json(config.articlesUrl);
      if (!Array.isArray(raw)) throw new Error("Invalid article data");
    } catch (error) {
      if (!config.fallbackArticlesUrl || config.fallbackArticlesUrl === config.articlesUrl) throw error;
      raw = await local;
      fallback = true;
    }
    let rows = articles(raw);
    if(fallback) rows = articles([...rows, ...cached(config)]);
    if(onArticles) onArticles(rows, fallback);
    const [rateRows, status] = await secondary;
    const localArchive = await local;
    rows = articles([...(Array.isArray(localArchive) ? localArchive : []), ...rows]);
    if(!fallback)try{root.localStorage.setItem(cacheKey(config),JSON.stringify({savedAt:Date.now(),articles:rows}));}catch{}
    return {articles: rows,
      rates: rates(rateRows), fx: fx(rateRows), status, fallback};
  }
  const api = {article, articles, rates, fx, safeURL, load, cached};
  if (typeof module !== "undefined") module.exports = api;
  else root.ACSData = api;
})(typeof window !== "undefined" ? window : globalThis);
