const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const ACS = require("../assets/news-data.js");
const story = () => ({
  id: "feed-test", status: "published", kind: "syndicated", headline: "<script>Test headline</script>",
  category: "tech", acsDate: "2026-11-25", eventDate: "", country: "Pan-African",
  collectedAt: "2026-11-25T09:00:00Z", publishedAt: "2026-11-25T07:00:00Z",
  sources: [{name: "Test publisher", title: "Test headline", url: "https://example.com/story"}],
});
test("only published, valid stories are returned", () => {
  assert.equal(ACS.articles([story(), {...story(), status: "draft"}, null]).length, 1);
  assert.equal(ACS.article({...story(), id: '"><svg/onload=alert(1)>'}), null);
});
test("unsafe source links are discarded", () => {
  assert.equal(ACS.article({...story(), sources: [{url: "javascript:alert(1)"}]}), null);
  assert.equal(ACS.safeURL("data:text/html,bad"), "");
});
test("image traversal and malformed array fields are removed", () => {
  const a = ACS.article({...story(), image: "../secret", body: "not an array", companies: null});
  assert.equal(a.image, undefined);
  assert.deepEqual(a.body, []);
});
test("missing date remains missing", () => {
  assert.equal(ACS.article({...story(), publishedAt: null}).publishedAt, null);
});
test("invalid rates and zero denominators are excluded", () => {
  assert.deepEqual(ACS.rates([{country: "Test", value: "12", prev: 10}]), []);
  assert.equal(ACS.fx([{kind: "fx", pairs: [{value: 2, prev: 0}]}]).pairs.length, 0);
});
test("remote data failure falls back to local archive", async () => {
  const old = global.fetch;
  global.fetch = async url => {
    if (url === "remote") throw new Error("offline");
    return {ok: true, json: async () => url === "local" ? [story()] : []};
  };
  try {
    const result = await ACS.load({articlesUrl: "remote", fallbackArticlesUrl: "local", ratesUrl: "rates", statusUrl: "status"});
    assert.equal(result.fallback, true);
    assert.equal(result.articles.length, 1);
  } finally { global.fetch = old; }
});
test("local editorial archive and remote collected stories are merged", async () => {
  const old = global.fetch;
  global.fetch = async url => ({ok: true, json: async () =>
    url === "remote" ? [story()] : url === "local" ? [{...story(), id: "manual-test", kind: "editorial"}] : []});
  try {
    const result = await ACS.load({articlesUrl: "remote", fallbackArticlesUrl: "local", ratesUrl: "rates", statusUrl: "status"});
    assert.equal(result.articles.length, 2);
    assert.equal(result.fallback, false);
  } finally { global.fetch = old; }
});
test("all inline website JavaScript compiles", () => {
  const html = fs.readFileSync("index.html", "utf8");
  for (const match of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new vm.Script(match[1]);
  assert.ok(!html.includes("window.claude"));
  assert.ok(html.includes("assets/news-data.js"));
});

async function renderContext(rows) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {innerHTML: "", textContent: "", value: "",
      addEventListener() {}, setAttribute() {}, removeAttribute() {}, before() {},
      querySelectorAll() { return []; }});
    return elements.get(id);
  };
  const context = vm.createContext({
    console, URL, Date, setTimeout, clearTimeout, setInterval() {},
    matchMedia: () => ({matches: true}),
    location: {hash: "#home", origin: "https://www.africacapitalsource.com", pathname: "/"},
    document: {querySelector: element, querySelectorAll: () => [],
      getElementById: id => element("#" + id), createElement: () => element("new"),
      addEventListener() {}, hidden: false},
    window: {addEventListener() {}, scrollTo() {}, ACS_CONFIG: {}},
    ACSData: {load: async () => ({articles: ACS.articles(rows), rates: [], fx: null, status: null, fallback: false})},
  });
  const script = [...fs.readFileSync("index.html", "utf8").matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1];
  vm.runInContext(script, context);
  await new Promise(resolve => setImmediate(resolve));
  return {context, html: () => element("#main").innerHTML};
}

test("homepage, category, source-story and archive templates render with real adapter output", async () => {
  const today = new Date().toISOString();
  const rows = Array.from({length: 18}, (_, i) => ({...story(), id: "feed-" + i,
    headline: "Test technology story " + i, publishedAt: today, collectedAt: today,
    acsDate: today.slice(0, 10)}));
  const page = await renderContext(rows);
  assert.match(page.html(), /Top stories/);
  assert.match(page.html(), /Test technology story/);
  vm.runInContext('location.hash="#cat-tech";route()', page.context);
  assert.match(page.html(), /18 articles/);
  vm.runInContext('location.hash="#a-feed-0";route()', page.context);
  assert.match(page.html(), /Read the story at Test publisher/);
  assert.doesNotMatch(page.html(), /AI-assisted editorial system/);
  assert.match(page.html(), /not an independently verified ACS report/);
  vm.runInContext('location.hash="#month-"+new Date().toISOString().slice(0,7);route()', page.context);
  assert.match(page.html(), /18 articles/);
});

test("source story headline HTML is escaped in the article template", async () => {
  const page = await renderContext([story()]);
  vm.runInContext('location.hash="#a-feed-test";route()', page.context);
  assert.match(page.html(), /&lt;script&gt;Test headline&lt;\/script&gt;/);
  assert.doesNotMatch(page.html(), /<script>Test headline/);
});

test("empty and future-only archives do not crash the homepage", async () => {
  const empty = await renderContext([]);
  assert.match(empty.html(), /News updates are being prepared/);
  const future = await renderContext([{...story(), publishedAt: "2099-01-01T12:00:00Z"}]);
  assert.match(future.html(), /No stories match/);
});
