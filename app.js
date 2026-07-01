"use strict";
const esc = s => (s==null?"":String(s)).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const fdate = s => { if(!s) return ""; const d=new Date(s); return isNaN(d)?"":d.toISOString().slice(0,10); };
// Descriptions are attacker-controlled HTML (from job advertisers). Sanitize
// with DOMPurify before inserting into the DOM to prevent stored XSS.
const clean = html => html ? DOMPurify.sanitize(html, {ALLOW_DATA_ATTR:false}) : "<em>no description</em>";
let DATA=null, sortK="posted_date", sortDir=-1, kwFilter="";

const $ = id => document.getElementById(id);

async function loadManifest(){
  try{
    const m = await (await fetch("data/manifest.json",{cache:"no-store"})).json();
    const sel = $("dateSel");
    sel.innerHTML = '<option value="data/latest.json">latest</option>' +
      (m.dates||[]).filter(d=>d!==m.latest_date)
        .map(d=>`<option value="data/${encodeURIComponent(d)}.json">${esc(d)}</option>`).join("");
    sel.onchange = () => load(sel.value);
  }catch(e){ /* manifest optional */ }
}

async function load(url="data/latest.json"){
  try{
    DATA = await (await fetch(url,{cache:"no-store"})).json();
  }catch(e){
    $("wrap").innerHTML = `<div class="err">Could not load ${esc(url)} — run the scraper first.</div>`;
    return;
  }
  render();
}

function render(){
  const d = DATA;
  $("meta").textContent = `${d.region} · ${d.date} · ${d.total_jobs} jobs`;

  // cards
  const cos = new Set(d.jobs.map(j=>j.business_name).filter(Boolean)).size;
  const withPay = d.jobs.filter(j=>j.pay_range).length;
  $("cards").innerHTML = [["Jobs",d.total_jobs],["Employers",cos],
    ["Keywords",d.keywords.length],["With pay label",withPay]]
    .map(([l,n])=>`<div class="card"><div class="n">${esc(n)}</div><div class="l">${esc(l)}</div></div>`).join("");

  // keyword bars (top 25)
  const top = d.keywords.slice(0,25);
  const max = top.length ? top[0].count : 1;
  $("kw").innerHTML = top.map(k=>
    `<div class="bar"><div class="t" data-w="${esc(k.term)}" title="${esc(k.term)}">${esc(k.term)}</div>`+
    `<div class="track"><div class="fill" style="width:${Number(k.count)/max*100}%"></div></div>`+
    `<div class="v">${esc(k.count)}</div></div>`).join("");
  $("kw").querySelectorAll(".t").forEach(el=>el.onclick=()=>{kwFilter=el.dataset.w;$("q").value="";renderTable();});

  // work type filter
  const wts = [...new Set(d.jobs.map(j=>j.work_type).filter(Boolean))].sort();
  $("fwt").innerHTML = '<option value="">All work types</option>' +
    wts.map(w=>`<option value="${esc(w)}">${esc(w)}</option>`).join("");

  renderTable();
}

function renderTable(){
  const term = $("q").value.toLowerCase();
  const wt = $("fwt").value;
  let rows = DATA.jobs.filter(j=>{
    if(kwFilter && !(j.keywords||[]).includes(kwFilter)) return false;
    if(wt && j.work_type!==wt) return false;
    if(term){
      const hay = (j.job_title+" "+j.business_name+" "+j.area+" "+(j.suburb||"")+" "+(j.keywords||[]).join(" ")).toLowerCase();
      if(!hay.includes(term)) return false;
    }
    return true;
  });
  rows.sort((a,b)=>{let x=a[sortK]||"",y=b[sortK]||"";return x<y?-sortDir:x>y?sortDir:0;});

  $("count").textContent = rows.length + " shown" + (kwFilter?` · keyword: "${kwFilter}"`:"");
  const tb = $("tb");
  tb.innerHTML = rows.map((j,i)=>
    `<tr class="trow" data-i="${i}">
       <td>${esc(j.job_title)}<div class="chips">${(j.keywords||[]).slice(0,8).map(k=>`<span class="chip" data-w="${esc(k)}">${esc(k)}</span>`).join("")}</div></td>
       <td>${esc(j.business_name)}</td><td>${esc(j.work_type)}</td>
       <td>${esc(j.area)}</td><td>${esc(fdate(j.posted_date))}</td>
       <td><a href="${esc(j.url)}" target="_blank" rel="noopener noreferrer">Seek ↗</a></td>
     </tr>
     <tr id="d${i}" style="display:none"><td colspan="6"><div class="desc">${clean(j.job_description)}</div></td></tr>`
  ).join("");

  tb.querySelectorAll(".trow").forEach(tr=>tr.onclick=e=>{
    if(e.target.classList.contains("chip")){kwFilter=e.target.dataset.w;$("q").value="";renderTable();return;}
    if(e.target.tagName==="A")return;
    const dd=$("d"+tr.dataset.i); dd.style.display = dd.style.display==="none"?"":"none";
  });
}

document.querySelectorAll("th[data-k]").forEach(th=>th.onclick=()=>{
  const k=th.dataset.k; sortDir=(sortK===k)?-sortDir:1; sortK=k; renderTable();
});
$("q").oninput = ()=>{kwFilter="";renderTable();};
$("fwt").onchange = renderTable;
$("clear").onclick = ()=>{kwFilter="";$("q").value="";$("fwt").value="";renderTable();};

loadManifest();
load();
