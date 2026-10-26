'use strict';
const $ = id => document.getElementById(id);
const categories = {system:'システム',power:'電源',storage:'ストレージ',snapshot:'スナップショット',backup:'バックアップ',security:'セキュリティ',update:'更新',application:'アプリケーション',other:'その他'};
const states = {ok:'正常',empty:'対応済み・該当タスクなし',partial:'部分的に取得',unsupported:'未対応',permission_denied:'アクセス権限不足',unavailable:'取得不可',parse_error:'解析エラー'};
let data, revision=0;
const isoDate = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
$('date').value=isoDate(new Date());
for (const [value,label] of Object.entries(categories)) $('category').add(new Option(label,value));
const el = (tag, text, cls) => { const e=document.createElement(tag); if(text!==undefined)e.textContent=text; if(cls)e.className=cls; return e; };
function params(){return new URLSearchParams({q:$('search').value,category:$('category').value,provider:$('provider').value,enabled:$('enabled').value});}
function fmt(at){return at ? new Intl.DateTimeFormat('ja-JP',{timeZone:data.timezone,dateStyle:'short',timeStyle:'short'}).format(new Date(at)) : '算出不可';}
function showTasks(tasks){
  if (!tasks.length) return;
  $('detail-title').textContent=tasks.length===1?tasks[0].name:`同時刻の ${tasks.length} 件`;
  $('detail-body').textContent=tasks.map(t=>[
    t.name,`カテゴリ: ${categories[t.category]||t.category}`,`提供元: ${t.provider}`,
    `有効状態: ${t.enabled===null?'不明':t.enabled?'有効':'無効'}`,
    `条件: ${t.schedule.description}`,`cron: ${t.schedule.expression}`,`タイムゾーン: ${t.schedule.timezone}`,
    `次回: ${t.next_runs.map(fmt).join(' / ')||'算出不可'}`,
    `取得元: ${t.source.location}`,`設定場所: ${t.configuration_location}`,`コマンド: ${t.command}`,
    `取得状態: ${states[t.collection_status]||t.collection_status}`,...t.warnings
  ].join('\n')).join('\n\n────────\n\n');
  $('detail').showModal();
}
$('close').onclick=()=>$('detail').close();
$('detail').addEventListener('click',e=>{if(e.target===$('detail'))$('detail').close();});
function rows(){
  $('rows').replaceChildren();
  $('count').textContent=`${data.tasks.length} 件（次回実行予定順）`;
  for(const t of data.tasks){
    const tr=el('tr'); const first=el('td'); const b=el('button',t.name);b.onclick=()=>showTasks([t]);first.append(b,el('small',categories[t.category]||t.category));tr.append(first);
    const values=[`${t.provider} / ${t.enabled===null?'不明':t.enabled?'有効':'無効'}`,t.schedule.description,fmt(t.next_runs[0]),`${t.configuration_location}\n${t.source.location}`,states[t.collection_status]||t.collection_status];
    for(const value of values)tr.append(el('td',value));$('rows').append(tr);
  }
  $('collections').replaceChildren();
  for(const c of data.collections){
    const card=el('article',undefined,'card');card.append(el('strong',`${c.collector} · ${states[c.status]}`),el('p',c.message),el('p',`最終試行: ${fmt(c.attempted_at)} / 最終正常取得: ${c.last_success_at?fmt(c.last_success_at):'未取得'}`),el('p',`前回: ${states[c.previous_status]||'未取得'}${c.stale?' / 古い情報を表示中':''}`));$('collections').append(card);
  }
  const cron=data.collections.find(c=>c.collector==='cron');
  $('notice').textContent=`${data.timezone} · 最終収集 ${cron?fmt(cron.attempted_at):'未取得'} · ${cron?states[cron.status]:''}${cron?.stale?' · 注意: 前回の古い情報を表示中':''} · cron 以外は実機調査待ち`;
}
async function timeline(ticket){
  let start=new Date($('date').value+'T12:00:00');
  if(Number.isNaN(start.getTime()))return;
  if($('mode').value==='calendar')start.setDate(start.getDate()-(start.getDay()+6)%7);
  const key=isoDate(start), p=params();p.set('start',key);
  const result=await fetch('/api/timeline?'+p);if(!result.ok)throw new Error('タイムライン取得失敗');
  const timeline=await result.json();if(ticket!==revision)return;
  const grid=$('timeline');grid.replaceChildren(el('div','時刻','dayhead'));
  for(let i=0;i<7;i++){const d=new Date(start);d.setDate(d.getDate()+i);grid.append(el('div',d.toLocaleDateString('ja-JP',{month:'numeric',day:'numeric',weekday:'short'}),'dayhead'));}
  const hours=el('div',undefined,'hours');for(let i=0;i<24;i++){const h=el('span',`${i}:00`,'hour');h.style.top=`${i*48}px`;hours.append(h);}grid.append(hours);
  const days=Array.from({length:7},()=>el('div',undefined,'day'));grid.append(...days);
  const grouped=new Map();for(const event of timeline.events){const key=event.at.slice(0,16);if(!grouped.has(key))grouped.set(key,[]);grouped.get(key).push(event);}
  const byId=new Map(data.tasks.map(t=>[t.id,t]));
  for(const [key,events]of grouped){
    const d=new Date(key.slice(0,10)+'T12:00:00');const index=Math.round((d-start)/86400000);if(index<0||index>6)continue;
    const hour=Number(key.slice(11,13)),minute=Number(key.slice(14,16));
    const button=el('button',`${key.slice(11,16)} ${events.length>1?`［${events.length}件］`:events[0].name}`,'event');
    button.style.top=`${(hour*60+minute)*0.8}px`;
    button.dataset.category=events[0].category;
    button.title=events.map(e=>e.name).join('\n');
    button.onclick=()=>showTasks([...new Set(events.map(e=>e.task_id))].map(id=>byId.get(id)).filter(Boolean));days[index].append(button);
  }
  $('range').textContent=`${key} から 7日間 · ${timeline.timezone}`;
  $('timeline-note').textContent=timeline.truncated?'表示上限（20,000件）に達しました。検索・フィルタで絞り込んでください。':timeline.events.length?`${timeline.events.length} 件の予定。近接するマーカーは一覧でも確認できます。`:'この期間に計算可能な予定はありません。収集状況も確認してください。';
}
async function load(){
  const ticket=++revision;
  try{
    const response=await fetch('/api/schedules?'+params());if(!response.ok)throw new Error('取得失敗');
    const incoming=await response.json();if(ticket!==revision)return;
    if(!data){const parts=new Intl.DateTimeFormat('en-CA',{timeZone:incoming.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());const v=Object.fromEntries(parts.map(p=>[p.type,p.value]));$('date').value=`${v.year}-${v.month}-${v.day}`;}
    data=incoming;
    const selection=$('provider').value;const all=new Set([...Array.from($('provider').options).map(o=>o.value),...data.tasks.map(t=>t.provider)]);
    $('provider').replaceChildren(new Option('すべての提供元',''));for(const value of all)if(value)$('provider').add(new Option(value,value));$('provider').value=selection;
    $('export').href='/api/export.csv?'+params();rows();await timeline(ticket);
  }catch(e){if(ticket===revision)$('notice').textContent='取得に失敗しました。接続を確認してください。表示済みの情報は古い可能性があります。';}
}
for(const id of ['category','provider','enabled','date','mode'])$(id).onchange=load;
let timer;$('search').oninput=()=>{clearTimeout(timer);timer=setTimeout(load,250);};
for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>{for(const v of ['week','list','status'])$(v).hidden=v!==b.dataset.view;for(const other of document.querySelectorAll('[data-view]'))other.setAttribute('aria-pressed',String(other===b));};
for(const [id,delta]of [['prev',-7],['next',7]])$(id).onclick=()=>{const d=new Date($('date').value+'T12:00:00');d.setDate(d.getDate()+delta);$('date').value=isoDate(d);load();};
$('today').onclick=()=>{$('date').value=isoDate(new Date(new Date().toLocaleString('en-US',{timeZone:data?.timezone||'Asia/Tokyo'})));load();};
$('refresh').onclick=async()=>{const b=$('refresh');b.disabled=true;try{const r=await fetch('/api/refresh',{method:'POST'});if(!r.ok)throw new Error();await load();}catch{ $('notice').textContent='再取得に失敗しました';}finally{b.disabled=false;}};
load();setInterval(load,60000);
