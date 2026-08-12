const DATA_URL = 'data/jobs.json';
let jobs = [];

const esc = (v) => String(v ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const money = (job) => {
  const c = job.salaryCurrency === 'INR' ? '₹' : '$';
  const fmt = n => job.salaryCurrency === 'INR' ? new Intl.NumberFormat('en-IN').format(n) : new Intl.NumberFormat('en-US').format(n);
  return `${c}${fmt(job.salaryMin)}–${fmt(job.salaryMax)}${job.salaryCurrency === 'INR' ? '' : ' / year'}`;
};
const location = j => [j.city,j.state,j.country].filter(Boolean).join(', ');
const slug = j => `${j.title}-${j.company}-${j.city}`.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
const card = j => `<article class="job-card">
  <div class="card-top"><span class="pill">${esc(j.department)}</span>${j.remote ? '<span class="remote">REMOTE</span>' : ''}</div>
  <h3><a href="job.html?job=${encodeURIComponent(j.id)}">${esc(j.title)}</a></h3>
  <p class="company">${esc(j.company)}</p>
  <div class="card-meta"><span>${esc(location(j))}</span><span>${esc(j.experience)}</span></div>
  <div class="card-meta"><span>${esc(j.employment)}</span><strong>${esc(money(j))}</strong></div>
  <div class="chips">${j.skills.slice(0,4).map(s=>`<span>${esc(s)}</span>`).join('')}</div>
  <a class="card-link" href="job.html?job=${encodeURIComponent(j.id)}">View opportunity →</a>
</article>`;

async function loadJobs(){
  try { const r = await fetch(DATA_URL); if(!r.ok) throw new Error('jobs.json not found'); jobs = await r.json(); }
  catch(e){ console.error(e); return; }
  const page = location.pathname.split('/').pop() || 'index.html';
  if(page === 'jobs.html') initListing();
  else if(page === 'job.html') initDetail();
  else initHome();
}

function unique(key){ return [...new Set(jobs.map(j=>j[key]).filter(Boolean))].sort((a,b)=>String(a).localeCompare(String(b))); }
function fillSelect(id,key,first){ const el=document.getElementById(id); if(!el) return; unique(key).forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;el.appendChild(o);}); }
function params(){ return new URLSearchParams(window.location.search); }

function initHome(){
  const target=document.getElementById('latestJobs'); if(!target) return;
  [...jobs].sort((a,b)=>b.posted.localeCompare(a.posted)).slice(0,6).forEach(j=>target.insertAdjacentHTML('beforeend',card(j)));
}

function initListing(){
  ['department','company','experience','country','state','city','employment'].forEach(id=>{const map={department:'department',company:'company',experience:'experience',country:'country',state:'state',city:'city',employment:'employment'}; fillSelect(id,map[id]);});
  const p=params();
  for(const id of ['q','department','company','experience','country','state','city','employment','salary']) if(p.has(id)) document.getElementById(id).value=p.get(id);
  if(p.get('remote')==='true') document.getElementById('remote').checked=true;
  if(p.get('visa')==='true') document.getElementById('visa').checked=true;
  const controls=['q','department','company','experience','country','state','city','employment','salary','remote','visa','sort'];
  controls.forEach(id=>document.getElementById(id)?.addEventListener('input',renderListing));
  document.getElementById('clearFilters')?.addEventListener('click',()=>{document.querySelectorAll('.filters input').forEach(x=>{if(x.type==='checkbox')x.checked=false;else x.value='';});document.querySelectorAll('.filters select').forEach(x=>x.value='');renderListing();});
  renderListing();
}
function renderListing(){
  const v=id=>document.getElementById(id)?.value||'';
  const q=v('q').toLowerCase(), remote=document.getElementById('remote')?.checked, visa=document.getElementById('visa')?.checked, salary=v('salary');
  let filtered=jobs.filter(j=>{
    const hay=[j.title,j.company,j.department,j.country,j.state,j.city,j.description,...j.skills].join(' ').toLowerCase();
    let salaryOK=true;if(salary){const [min,max]=salary.split('-').map(Number);salaryOK=j.salaryMax>=min&&j.salaryMin<=max;}
    return (!q||hay.includes(q))&&(!v('department')||j.department===v('department'))&&(!v('company')||j.company===v('company'))&&(!v('experience')||j.experience===v('experience'))&&(!v('country')||j.country===v('country'))&&(!v('state')||j.state===v('state'))&&(!v('city')||j.city===v('city'))&&(!v('employment')||j.employment===v('employment'))&&(!remote||j.remote)&&(!visa||j.visa)&&salaryOK;
  });
  const sort=v('sort'); if(sort==='salary')filtered.sort((a,b)=>b.salaryMax-a.salaryMax);else if(sort==='title')filtered.sort((a,b)=>a.title.localeCompare(b.title));else filtered.sort((a,b)=>b.posted.localeCompare(a.posted));
  document.getElementById('resultCount').textContent=filtered.length;const grid=document.getElementById('jobGrid');grid.innerHTML=filtered.map(card).join('');document.getElementById('empty').hidden=filtered.length>0;
}

function initDetail(){
  const id=params().get('job'), j=jobs.find(x=>x.id===id), target=document.getElementById('jobDetail');
  if(!j){target.innerHTML='<section class="empty"><h1>Opportunity not found</h1><a href="jobs.html">Back to opportunities</a></section>';return;}
  document.title=`${j.title} — ${j.company} | Road Beyond Roles`;
  target.innerHTML=`<a class="back" href="jobs.html">← Back to opportunities</a><section class="detail-hero"><div><span class="pill">${esc(j.department)}</span><h1>${esc(j.title)}</h1><p class="company">${esc(j.company)}</p></div><a class="apply" href="${esc(j.apply)}" target="_blank" rel="noopener">Apply on official site →</a></section>
  <div class="detail-layout"><article class="detail-main">
    <section><h2>About the role</h2><p>${esc(j.description)}</p></section>
    <section><h2>Responsibilities</h2><ul>${j.responsibilities.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></section>
    <section><h2>Requirements</h2><ul>${j.requirements.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></section>
    <section><h2>Benefits</h2><ul>${j.benefits.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></section>
    <section><h2>Skills</h2><div class="chips">${j.skills.map(x=>`<span>${esc(x)}</span>`).join('')}</div></section>
  </article><aside class="facts"><div><small>Company</small><strong>${esc(j.company)}</strong></div><div><small>Location</small><strong>${esc(location(j))}</strong></div><div><small>Experience</small><strong>${esc(j.experience)}</strong></div><div><small>Salary</small><strong>${esc(money(j))}</strong></div><div><small>Employment</small><strong>${esc(j.employment)}</strong></div><div><small>Remote</small><strong>${j.remote?'Yes':'No'}</strong></div><div><small>Visa sponsorship</small><strong>${j.visa?'Yes':'No'}</strong></div></aside></div>`;
}
loadJobs();
