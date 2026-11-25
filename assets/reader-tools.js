/* Deterministic reader tools: no AI, tracking or account required. */
(function(root) {
  'use strict';
  const DAY = 86400000;
  const RULES = [
    ['etfs', /\b(etfs?|exchange.traded funds?|unit trusts?)\b/i],
    ['economy', /\b(central bank|reserve bank|monetary policy|policy rate|repo rate|inflation|gdp|treasury|fiscal|tariffs?|budget|companies law|regulations?|economic)\b/i],
    ['personal-finance', /\b(personal finance|retirement|pensions?|household savings|income tax|cost of living)\b/i],
    ['markets', /\b(stock markets?|stocks?|shares?|bourse|bond yields?|forex|currenc(?:y|ies)|exchange rate|jse|ngx|buyback)\b/i],
    ['crypto', /\b(bitcoin|crypto|blockchain|ethereum|stablecoins?|tokenisation)\b/i],
    ['startups', /\b(startups?|start-ups?|venture capital|pre.seed|seed funding|series [a-f]|funding round)\b/i],
    ['banking', /\b(banks?|banking|fintech|payments?|mobile money|remittances?|lenders?|loans?|financing)\b/i],
    ['infrastructure', /\b(rail|railway|ports?|infrastructure|logistics|solar|electricity|power grid|suez|lng)\b/i],
    ['tech', /\b(technology|software|artificial intelligence|telecoms?|data cent(?:re|er)s?|cyber\w*|broadband|ai|cloud|internet)\b/i],
    ['economy', /\b(health|hiv|drugs?|vaccines?|hospitals?|disease|healthcare|medical)\b/i],
    ['companies', /\b(companies|company|corporate|ceo|profits?|earnings|revenue|merger|acqui\w*|mining|miners?)\b/i]
  ];
  function category(a) {
    if(a.kind !== 'syndicated') return a.category;
    const hit = RULES.find(([,re]) => re.test(a.headline || ''));
    // Broad publisher feeds are not evidence that every story belongs to Markets.
    return hit ? hit[0] : a.category === 'markets' ? 'companies' : a.category;
  }
  const stamp = a => Date.parse(a.publishedAt || a.collectedAt || a.acsDate) || 0;
  const publisher = a => a.sources?.[0]?.name || 'ACS';
  const newest = list => [...list].sort((a,b) => stamp(b)-stamp(a) || a.id.localeCompare(b.id));
  const stop = new Set('the a an and or for of to in on as at by with from its into after over across africa african south north east west million billion raises raise raised funding round seed pre extends extend new firm company companies startup startups stake buys buy acquisition deal says said will plans targets confirms secures secures reports report'.split(' '));
  const tokens = h => new Set((h.toLowerCase().match(/[a-z0-9]+/g)||[]).filter(t=>t.length>2&&!stop.has(t)));
  const geography = new Set('nigeria nigerian kenya kenyan canada canadian angola angolan ghana ghanaian tanzania tanzanian egypt egyptian zambia zambian ethiopia ethiopian uganda ugandan rwanda rwandan morocco moroccan namibia namibian botswana zimbabwe mozambique london lagos cairo nairobi johannesburg cape town india indian china chinese global'.split(' '));
  const entities = h => new Set((h.match(/\b[A-Z][a-zA-Z0-9]{3,}\b/g)||[]).map(t=>t.toLowerCase()).filter(t=>!stop.has(t)&&!geography.has(t)));
  function relevant(a) {
    const h=a.headline||'';
    // Keep these stories in search/archive, but don't elevate general-interest items.
    return !/\b(birthday|at 80|at 70|kidnapp\w*|obituary|celebrity|football|premier league|presidential candidate|Iran mediation)\b/i.test(h);
  }
  function amount(h) {
    const m=h.match(/(US\$|\$|USD|ZAR|R|NGN|KES|EUR|€|GBP|£)\s*([\d,.]+)\s*(trillion|billion|million|trn|bn|m)\b/i);
    if(!m)return '';
    const currency=/^(us\$|\$|usd)$/i.test(m[1])?'USD':/^(r|zar)$/i.test(m[1])?'ZAR':m[1].toUpperCase();
    const scale=/^(tr)/i.test(m[3])?1e12:/^(b)/i.test(m[3])?1e9:1e6;
    return currency+':'+Number(m[2].replace(/,/g,''))*scale;
  }
  function event(h) {
    if(/\b(plan|plans|planned|may|could|seeks|seeking|target|targets|rumou?r|denies|cancel\w*)\b/i.test(h)) return '';
    if(/\b(raises?|raised|funding|pre.seed|seed|series [a-f])\b/i.test(h))return 'funding';
    if(/\b(stake|buys?|acquir\w*|takeover|merger)\b/i.test(h))return 'ownership';
    if(/\b(financing|loan|credit line)\b/i.test(h))return 'finance';
    return '';
  }
  function related(a,b) {
    if(a.kind!=='syndicated'||b.kind!=='syndicated'||publisher(a)===publisher(b)||!stamp(a)||!stamp(b)||Math.abs(stamp(a)-stamp(b))>3*DAY)return false;
    const ah=a.headline||'', bh=b.headline||'';
    if(ah.toLowerCase()===bh.toLowerCase())return true;
    const aa=amount(ah), ba=amount(bh);
    if(aa&&ba&&aa!==ba)return false;
    const ae=event(ah), be=event(bh), named=[...entities(ah)].some(t=>entities(bh).has(t));
    if(aa&&aa===ba&&ae&&ae===be&&named)return true;
    const x=tokens(ah), y=tokens(bh), common=[...x].filter(t=>y.has(t)).length;
    return named&&common>=4&&common/(x.size+y.size-common)>=0.72;
  }
  function group(list) {
    const groups=[], buckets=new Map(), byId=new Map();
    for(const a of newest(list)) {
      const keys=[...tokens(a.headline||'')], candidates=new Set(keys.flatMap(k=>buckets.get(k)||[]));
      let g=[...candidates].find(g=>g.every(b=>related(a,b)));
      if(!g){g=[];groups.push(g);for(const k of keys){if(!buckets.has(k))buckets.set(k,[]);buckets.get(k).push(g);}}
      g.push(a);byId.set(a.id,g);
    }
    return {groups,byId};
  }
  function unique(list,index) {
    const seen=new Set();return list.filter(a=>{const key=index.byId.get(a.id)||a; if(seen.has(key))return false;seen.add(key);return true;});
  }
  function balanced(list,n,seed=[]) {
    const pool=newest(list.filter(relevant)), result=[], sources=new Map(), countries=new Map();
    const record=a=>{sources.set(publisher(a),(sources.get(publisher(a))||0)+1);if(a.country&&a.country!=='Pan-African')countries.set(a.country,(countries.get(a.country)||0)+1);};
    seed.forEach(record);
    // Prefer variety within a 72-hour freshness window; never promote months-old news.
    while(pool.length&&result.length<n) {
      const latest=stamp(pool[0]);let best=0, bestScore=Infinity;
      pool.forEach((a,i)=>{const age=(latest-stamp(a))/DAY;if(age>3)return;
        const score=age*0.6+(sources.get(publisher(a))||0)*3+(countries.get(a.country)||0)*1.5;
        if(score<bestScore){bestScore=score;best=i;}});
      const a=pool.splice(best,1)[0];result.push(a);record(a);
    }
    return result;
  }
  const dayKey = now => new Intl.DateTimeFormat('en-CA',{timeZone:'Africa/Johannesburg',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
  function filter(list,f={},now=new Date()) {
    const today=dayKey(now), start=Date.parse(today+'T00:00:00+02:00');
    const weekday=new Date(start+2*3600000).getUTCDay();
    const since=f.date==='today'?start:f.date==='week'?start-((weekday+6)%7)*DAY:f.date==='month'?Date.parse(today.slice(0,7)+'-01T00:00:00+02:00'):0;
    const q=(f.query||'').trim().toLowerCase();
    return list.filter(a=>(!f.country||a.country===f.country)&&(!f.topic||a.category===f.topic||(a.also||[]).includes(f.topic))&&
      (!f.publisher||(a.sources||[]).some(s=>s.name===f.publisher))&&(!since||(stamp(a)>=since&&stamp(a)<=now.getTime()))&&
      (!q||[a.headline,a.standfirst,a.country,...(a.companies||[]),...(a.sources||[]).map(s=>s.name)].join(' ').toLowerCase().includes(q)));
  }
  function savedStore(storage,clean) {
    const key='acs.saved-stories.v1';let items=[], persistent=true;
    function read(){try{const raw=JSON.parse(storage.getItem(key)||'[]');items=Array.isArray(raw)?raw.map(clean).filter(Boolean).slice(0,200):[];}catch{persistent=false;}return items;}
    read();
    return {read, list:()=>items, has:id=>items.some(a=>a.id===id), toggle(a){
      const had=items.some(x=>x.id===a.id);if(!had&&items.length>=200)return {ok:false,message:'You have 200 saved stories. Remove one before saving another.'};
      const valid=clean(a);if(!had&&!valid)return {ok:false,message:'This story could not be saved.'};
      items=had?items.filter(x=>x.id!==a.id):[valid,...items];
      try{storage.setItem(key,JSON.stringify(items));persistent=true;}catch{persistent=false;}
      return {ok:true,saved:!had,persistent,message:persistent?(had?'Story removed from saved stories.':'Story saved on this device.'):'Browser storage is unavailable. This change will last only while this page is open.'};
    }};
  }
  const api={category,related,group,unique,balanced,filter,newest,amount,savedStore,relevant,rules:RULES.map(([category,re])=>({category,pattern:re.source}))};
  if(typeof module!=='undefined')module.exports=api;else root.ACSReader=api;
})(typeof window!=='undefined'?window:globalThis);
