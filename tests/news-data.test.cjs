const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const ACS = require("../assets/news-data.js");
const Reader = require("../assets/reader-tools.js");
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

async function renderContext(rows, policyData = {sources: []}) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {innerHTML: "", textContent: "", value: "",
      addEventListener() {}, setAttribute() {}, removeAttribute() {}, before() {},
      querySelectorAll() { return []; }});
    return elements.get(id);
  };
  const context = vm.createContext({
    console, URL, URLSearchParams, Date, AbortController, setTimeout, clearTimeout, setInterval() {}, ACSReader: Reader,
    fetch: async () => ({ok: true, json: async () => policyData}),
    matchMedia: () => ({matches: true}),
    location: {hash: "#home", origin: "https://www.africacapitalsource.com", pathname: "/"},
    document: {querySelector: element, querySelectorAll: () => [],
      getElementById: id => element("#" + id), createElement: () => element("new"),
      addEventListener() {}, hidden: false},
    window: {addEventListener() {}, scrollTo() {}, ACS_CONFIG: {}},
    ACSData: {safeURL: ACS.safeURL, article: ACS.article, load: async () => ({articles: ACS.articles(rows), rates: [], fx: null, status: null, fallback: false})},
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
  assert.match(page.html(), /18 stories/);
  vm.runInContext('location.hash="#a-feed-0";route()', page.context);
  assert.match(page.html(), /Read on Test publisher/);
  assert.doesNotMatch(page.html(), /AI-assisted editorial system/);
  assert.match(page.html(), /not an independently verified ACS report/);
  vm.runInContext('location.hash="#month-"+new Date().toISOString().slice(0,7);route()', page.context);
  assert.match(page.html(), /18 stories/);
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

test("official policy rates show source dates and flag saved records after failure", async () => {
  const source = {id:"za", country:"South Africa", bank:"South African Reserve Bank",
    instrument:"SARB Policy Rate", sourceUrl:"https://www.resbank.co.za/", dateLabel:"Observation date",
    value:7.25, date:new Date().toISOString().slice(0,10), lastSuccess:new Date().toISOString(), status:"ok"};
  const page = await renderContext([], {sources:[source]});
  let panel = vm.runInContext('ratesTable(true)', page.context);
  assert.match(panel, /7.25%/);
  assert.match(panel, /Observation date/);
  assert.match(panel, /Last verified/);
  assert.doesNotMatch(panel, /Update delayed/);
  vm.runInContext('POLICY_FAILED=true', page.context);
  panel = vm.runInContext('ratesTable(true)', page.context);
  assert.match(panel, /7.25%/);
  assert.match(panel, /Update delayed/);
});

test("missing policy rates are never displayed as zero", async () => {
  const page = await renderContext([], {sources:[{id:"ke", country:"Kenya", bank:"Central Bank of Kenya",
    sourceUrl:"https://www.centralbank.go.ke/", status:"unavailable", value:null}]});
  const panel = vm.runInContext('ratesBox()', page.context);
  assert.match(panel, /Rate unavailable/);
  assert.doesNotMatch(panel, /0.00%/);
});

test("story images resolve legacy and numbered paths and reject missing image keys", async () => {
  const page = await renderContext([story()]);
  assert.equal(vm.runInContext('storyImageURL("johannesburg")', page.context), "/img/johannesburg.jpg");
  assert.equal(vm.runInContext('storyImageURL("port-1")', page.context), "/ph/port-1.jpg");
  for (const key of ["johannesburg-2", "gold-1", "../../secret", "missing-image"]) {
    assert.match(vm.runInContext(`storyImageURL(${JSON.stringify(key)})`, page.context), /^data:image\/svg\+xml/);
  }
  const markup = vm.runInContext('storyHero({id:"test",image:"missing-image",category:"tech"})', page.context);
  assert.match(markup, /data-story-image/);
  assert.doesNotMatch(markup, /missing-image\.jpg/);
});

test("a failed story image gets one inline fallback and an accurate caption", async () => {
  const page = await renderContext([]);
  const caption = {textContent: "Illustrative photo via Pexels"};
  let attempts = 0;
  const image = {dataset: {}, hidden: false, removeAttribute() {},
    closest: () => ({querySelector: () => caption}),
    set src(value) { assert.match(value, /^data:image\/svg\+xml/); attempts++; }};
  page.context.failedImage = image;
  vm.runInContext('recoverStoryImage(failedImage)', page.context);
  assert.equal(attempts, 1);
  assert.equal(caption.textContent, "Illustrative placeholder");
  assert.equal(image.hidden, false);
  vm.runInContext('recoverStoryImage(failedImage)', page.context);
  assert.equal(attempts, 1);
  assert.equal(image.hidden, true);
});

test("every image candidate refers to a shipped asset", {
  skip: !fs.existsSync(require("node:path").join(__dirname, "../ph")) && "Photo assets are available in the repository CI checkout"
}, async () => {
  const page = await renderContext([]);
  const urls = vm.runInContext('[...Object.entries(PH).flatMap(([key,values])=>values.map(n=>storyImageURL(`${key}-${n}`))),...Array.from(LEGACY_IMAGES,storyImageURL)]', page.context);
  for (const url of urls) assert.ok(fs.existsSync(require("node:path").join(__dirname, "..", url)), `Missing image: ${url}`);
});

const report = (id, headline, publisher='Publisher A', date='2026-11-25T09:00:00Z') =>
  ({...story(),id,headline,publishedAt:date,sources:[{name:publisher,url:'https://example.com/'+id}],country:'Nigeria'});

test('topic rules agree with collector configuration and correct broad feed labels',()=>{
  assert.deepEqual(Reader.rules,JSON.parse(fs.readFileSync('config/topic-rules.json')));
  assert.equal(Reader.category({...report('a','First generic HIV drug shipments arrive in Africa'),category:'markets'}),'economy');
  assert.equal(Reader.category(report('a','South African central bank says financial system resilient')),'economy');
  assert.equal(Reader.category(report('a','NGX sheds N1.1 trillion as investors dump banking stocks')),'markets');
  assert.equal(Reader.category(report('a','Tanzania launches ETF with gold exposure')),'etfs');
  assert.equal(Reader.category(report('a','Safaricom expands Family Share Internet Service')),'tech');
  assert.equal(Reader.category(report('a','Creating an intelligent identity infrastructure layer')),'tech');
  assert.equal(Reader.category({...report('a','An editorial view'),kind:'editorial',category:'opinion'}),'opinion');
});
test('related funding reports group without deleting source records',()=>{
  const list=[report('a','Aeon Raises $2 Million to Build Africa’s Cyber Defence Infrastructure'),report('b','Nigerian cybersecurity startup Aeon extends pre-seed round to $2 million','Publisher B')];
  const groups=Reader.group(list);
  assert.equal(groups.groups.length,1);assert.equal(groups.byId.get('a').length,2);
  assert.equal(Reader.unique(list,groups).length,1);assert.equal(list.length,2);
  assert.equal(Reader.related(report('a','Buyback backlash: Gold miners stand firm'),report('b','Buyback backlash: Gold miners stand firm')),true);
});
test('different amounts, companies, currencies, time periods and proposed deals stay separate',()=>{
  const a=report('a','Aeon raises $2 million');
  for(const b of [report('b','Aeon raises $3 million','B'),report('b','Kora raises $2 million','B'),report('b','Aeon raises R2 million','B'),report('b','Aeon raises $2 million','B','2026-11-10T09:00:00Z'),report('b','Aeon plans to raise $2 million','B')])assert.equal(Reader.related(a,b),false,b.headline);
  assert.equal(Reader.related(report('a','Nigeria startup Kora raises $2 million'),report('b','Nigeria startup Zola raises $2 million','B')),false);
});
test('homepage selection diversifies sources and countries while preserving freshness',()=>{
  const list=[report('a','Company Alpha results'),report('b','Company Beta results'),{...report('c','Company Gamma results','B'),country:'Kenya'},{...report('d','Company Delta results','C','2026-09-01'),country:'Egypt'}];
  assert.deepEqual(Reader.balanced(list,3).map(a=>a.id),['a','c','b']);
  assert.equal(Reader.balanced([report('a','Nigeria kidnapping incidents rise')],1).length,0);
});
test('country, topic, publisher, date and query filters combine using South African dates',()=>{
  const a={...report('a','Bank Alpha launches payments','B','2026-11-22T23:00:00Z'),category:'banking',country:'South Africa'};
  const b={...a,id:'b',publishedAt:'2026-11-22T21:00:00Z'};
  const f={country:'South Africa',topic:'banking',publisher:'B',date:'week',query:'alpha'};
  assert.deepEqual(Reader.filter([a,b],f,new Date('2026-11-23T06:00:00Z')).map(x=>x.id),['a']);
  assert.equal(Reader.filter([a],{...f,publisher:'Wrong'},new Date('2026-11-23T06:00:00Z')).length,0);
});
test('saved snapshots persist across visits and remove cleanly',()=>{
  const data=new Map(), storage={getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)};
  const saved=Reader.savedStore(storage,ACS.article);assert.equal(saved.toggle(story()).saved,true);
  const revisit=Reader.savedStore(storage,ACS.article);assert.equal(revisit.has(story().id),true);
  assert.equal(revisit.toggle(story()).saved,false);assert.equal(Reader.savedStore(storage,ACS.article).list().length,0);
});
test('blocked storage keeps session saves and explains the limitation',()=>{
  const saved=Reader.savedStore(null,ACS.article),result=saved.toggle(story());
  assert.equal(result.persistent,false);assert.equal(saved.has(story().id),true);
  assert.match(result.message,/only while this page is open/);
});
test('invalid saved snapshots cannot inject links',()=>{
  const storage={getItem:()=>JSON.stringify([{...story(),sources:[{url:'javascript:alert(1)'}]}])};
  assert.equal(Reader.savedStore(storage,ACS.article).list().length,0);
});
test('headlines can render before a slow status request completes',async()=>{
  const old=global.fetch;let release, delivered=false;
  global.fetch=async url=>({ok:true,json:()=>url==='status'?new Promise(r=>release=r):Promise.resolve(url==='remote'?[story()]:[])});
  try{
    const pending=ACS.load({articlesUrl:'remote',fallbackArticlesUrl:'local',ratesUrl:'rates',statusUrl:'status'},rows=>{delivered=rows.length===1;});
    await new Promise(r=>setImmediate(r));assert.equal(delivered,true);release({});await pending;
  }finally{global.fetch=old;}
});
test('combined filters render clear empty state and source links remain explicit',async()=>{
  const page=await renderContext([story()]);
  vm.runInContext('location.hash="#cat-latest?country=South+Africa&topic=banking";route()',page.context);
  assert.match(page.html(),/No stories match these filters/);assert.match(page.html(),/value="South Africa" selected/);
  vm.runInContext('location.hash="#a-feed-test";route()',page.context);
  assert.match(page.html(),/Read on Test publisher/);assert.match(page.html(),/data-save-story="feed-test"/);
});
test('saved page retains a story snapshot after it leaves the active news feed',async()=>{
  const page=await renderContext([story()]);
  vm.runInContext('SAVED.toggle(ARTICLES[0]);setNews([]);location.hash="#saved";route()',page.context);
  assert.match(page.html(),/Test headline/);assert.match(page.html(),/Saved in this browser/);
});
