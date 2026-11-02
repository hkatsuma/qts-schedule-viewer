'use strict';
const $ = id => document.getElementById(id);
const categories = {system:'システム',power:'電源',storage:'ストレージ',snapshot:'スナップショット',backup:'バックアップ',security:'セキュリティ',update:'更新',application:'アプリケーション',other:'その他'};
const states = {ok:'正常',empty:'対応済み・該当タスクなし',partial:'部分的に取得',unsupported:'未対応',permission_denied:'アクセス権限不足',unavailable:'取得不可',parse_error:'解析エラー'};
const views = ['week','month','list','status'];
let data, revision = 0, activeView = 'week';
const isoDate = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
function nasToday() {
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone:data?.timezone || 'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
  const values = Object.fromEntries(parts.map(p => [p.type,p.value]));
  return `${values.year}-${values.month}-${values.day}`;
}
$('date').value = isoDate(new Date());
$('month-date').value = $('date').value.slice(0,7);
try {
  const saved = localStorage.getItem('qsv-frequency');
  if (['all','nonfrequent','frequent'].includes(saved)) $('frequency').value = saved;
} catch {}
for (const [value,label] of Object.entries(categories)) $('category').add(new Option(label,value));
const el = (tag,text,cls) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (cls) element.className = cls;
  return element;
};
function params() {
  return new URLSearchParams({q:$('search').value,category:$('category').value,provider:$('provider').value,enabled:$('enabled').value,frequency:$('frequency').value});
}
function fmt(at) {
  return at ? new Intl.DateTimeFormat('ja-JP',{timeZone:data.timezone,dateStyle:'short',timeStyle:'short'}).format(new Date(at)) : '算出不可';
}
function showTasks(tasks,title,context) {
  if (!tasks.length) return;
  $('detail-title').textContent = title || (tasks.length === 1 ? tasks[0].name : `${tasks.length} 件のタスク`);
  const descriptions = tasks.map(t => [
    t.name,`カテゴリ: ${categories[t.category] || t.category}`,`提供元: ${t.provider}`,
    `有効状態: ${t.enabled === null ? '不明' : t.enabled ? '有効' : '無効'}`,
    `条件: ${t.schedule.description}`,`cron: ${t.schedule.expression}`,`タイムゾーン: ${t.schedule.timezone}`,
    `実行対象日の回数（通常日）: ${t.runs_per_active_day ?? '算出不可'}`,
    `次回: ${t.next_runs.map(fmt).join(' / ') || '算出不可'}`,
    `取得元: ${t.source.location}`,`設定場所: ${t.configuration_location}`,`コマンド: ${t.command}`,
    `取得状態: ${states[t.collection_status] || t.collection_status}`,...t.warnings
  ].join('\n'));
  $('detail-body').textContent = [context,...descriptions].filter(Boolean).join('\n\n────────\n\n');
  $('detail').showModal();
}
$('close').onclick = () => $('detail').close();
$('detail').addEventListener('click', e => {if (e.target === $('detail')) $('detail').close();});
function rows() {
  $('rows').replaceChildren();
  $('count').textContent = `${data.tasks.length} 件（次回実行予定順）`;
  const hidden = data.hidden_by_frequency || 0;
  $('filter-note').textContent = `実行頻度フィルタで ${hidden} 件を非表示。高頻度は、実行対象日の通常の24時間で1日24回以上（分・時フィールドで計算）です。算出不可は「高頻度を除外」に残ります。`;
  for (const t of data.tasks) {
    const tr = el('tr'), first = el('td'), button = el('button',t.name);
    button.onclick = () => showTasks([t]);
    first.append(button,el('small',categories[t.category] || t.category));
    tr.append(first);
    const values = [`${t.provider} / ${t.enabled === null ? '不明' : t.enabled ? '有効' : '無効'}`,`${t.schedule.description}\n${t.schedule.expression}`,fmt(t.next_runs[0]),`${t.configuration_location}\n${t.source.location}`,states[t.collection_status] || t.collection_status];
    for (const value of values) tr.append(el('td',value));
    $('rows').append(tr);
  }
  $('collections').replaceChildren();
  for (const c of data.collections) {
    const card = el('article',undefined,'card');
    card.append(el('strong',`${c.collector} · ${states[c.status]}`),el('p',c.message),el('p',`最終試行: ${fmt(c.attempted_at)} / 最終正常取得: ${c.last_success_at ? fmt(c.last_success_at) : '未取得'}`),el('p',`前回: ${states[c.previous_status] || '未取得'}${c.stale ? ' / 古い情報を表示中' : ''}`));
    $('collections').append(card);
  }
  const cron = data.collections.find(c => c.collector === 'cron');
  $('notice').textContent = `${data.timezone} · 最終収集 ${cron ? fmt(cron.attempted_at) : '未取得'} · ${cron ? states[cron.status] : ''}${cron?.stale ? ' · 注意: 前回の古い情報を表示中' : ''} · cron 以外は実機調査待ち`;
}
async function timeline(ticket) {
  const start = new Date($('date').value+'T12:00:00');
  if (Number.isNaN(start.getTime())) return;
  if ($('mode').value === 'calendar') start.setDate(start.getDate()-(start.getDay()+6)%7);
  const key = isoDate(start), query = params();
  query.set('start',key);
  const response = await fetch('/api/timeline?'+query);
  if (!response.ok) throw new Error('タイムライン取得失敗');
  const timeline = await response.json();
  if (ticket !== revision) return;
  const grid = $('timeline');
  grid.replaceChildren(el('div','時刻','dayhead'));
  for (let i=0;i<7;i++) {
    const d = new Date(start); d.setDate(d.getDate()+i);
    grid.append(el('div',d.toLocaleDateString('ja-JP',{month:'numeric',day:'numeric',weekday:'short'}),'dayhead'));
  }
  const hours = el('div',undefined,'hours');
  for (let i=0;i<24;i++) {const h=el('span',`${i}:00`,'hour'); h.style.top=`${i*48}px`; hours.append(h);}
  grid.append(hours);
  const days = Array.from({length:7},() => el('div',undefined,'day'));
  grid.append(...days);
  const grouped = new Map();
  for (const event of timeline.events) {
    const key = event.at.slice(0,16);
    if (!grouped.has(key)) grouped.set(key,[]);
    grouped.get(key).push(event);
  }
  const byId = new Map(data.tasks.map(t => [t.id,t]));
  for (const [key,events] of grouped) {
    const d = new Date(key.slice(0,10)+'T12:00:00'), index = Math.round((d-start)/86400000);
    if (index<0 || index>6) continue;
    const hour=Number(key.slice(11,13)), minute=Number(key.slice(14,16));
    const button=el('button',`${key.slice(11,16)} ${events.length>1 ? `［${events.length}件］` : events[0].name}`,'event');
    button.style.top=`${(hour*60+minute)*0.8}px`;
    button.dataset.category=events[0].category;
    button.title=events.map(e => e.name).join('\n');
    button.onclick=() => showTasks([...new Set(events.map(e => e.task_id))].map(id => byId.get(id)).filter(Boolean),undefined,`${key.replace('T',' ')} の予定`);
    days[index].append(button);
  }
  $('range').textContent=`${key} から 7日間 · ${timeline.timezone}`;
  $('timeline-note').textContent=timeline.truncated ? '表示上限（20,000件）に達しました。実行頻度・検索・カテゴリで絞り込んでください。' : timeline.events.length ? `${timeline.events.length} 件の予定。近接するマーカーは一覧でも確認できます。` : 'この期間に計算可能な予定はありません。フィルタと収集状況も確認してください。';
}
async function monthCalendar(ticket) {
  const selected=$('month-date').value;
  if (!selected) return;
  const query=params(); query.set('month',selected+'-01');
  const response=await fetch('/api/month?'+query);
  if (!response.ok) throw new Error('月間予定取得失敗');
  const calendar=await response.json();
  if (ticket!==revision) return;
  const grid=$('month-grid'); grid.replaceChildren();
  for (const label of ['月','火','水','木','金','土','日']) grid.append(el('div',label,'month-weekday'));
  const first=new Date(selected+'-01T12:00:00'), year=first.getFullYear(), month=first.getMonth();
  const total=new Date(year,month+1,0).getDate(), padding=(first.getDay()+6)%7;
  const grouped=new Map(), byId=new Map(data.tasks.map(t => [t.id,t]));
  for (const row of calendar.days) {
    if (!grouped.has(row.day)) grouped.set(row.day,[]);
    grouped.get(row.day).push(row);
  }
  for (let i=0;i<padding;i++) grid.append(el('div',undefined,'month-cell empty'));
  for (let day=1;day<=total;day++) {
    const key=`${selected}-${String(day).padStart(2,'0')}`, cell=el('div',undefined,'month-cell');
    const header=el('button',`${day}日`,'month-day'); header.dataset.day=key;
    header.onclick=() => {$('date').value=key; setView('week');};
    const summaries=(grouped.get(key)||[]).sort((a,b) => a.first_run.localeCompare(b.first_run));
    const count=summaries.reduce((total,row) => total+row.count,0);
    cell.append(header,el('small',`${summaries.length}タスク / ${count}回`,'month-count'));
    const appendRow=row => {
      const button=el('button',`${row.first_run.slice(11,16)} ${row.name}${row.count>1 ? ` · ${row.count}回` : ''}`,'month-task');
      button.dataset.category=row.category;
      button.title=`${row.name} · 最初の予定 ${row.first_run.slice(11,16)} · ${row.count}回`;
      button.onclick=() => {const task=byId.get(row.task_id); if (task) showTasks([task],undefined,`${key} の予定: 最初 ${fmt(row.first_run)} / ${row.count}回`);};
      cell.append(button);
    };
    summaries.slice(0,6).forEach(appendRow);
    if (summaries.length>6) {
      const more=el('button',`ほか ${summaries.length-6} タスクを表示`,'month-more');
      more.onclick=() => {more.remove(); summaries.slice(6).forEach(appendRow);};
      cell.append(more);
    }
    grid.append(cell);
  }
  for (let i=(padding+total)%7;i>0 && i<7;i++) grid.append(el('div',undefined,'month-cell empty'));
  $('month-range').textContent=`${year}年${month+1}月 · ${calendar.timezone}`;
  $('month-note').textContent=calendar.days.length ? '同じ日の繰り返し実行はタスクごとに集計しています。詳しい時刻は日付を選んで週間表示で確認できます。' : 'この月に計算可能な予定はありません。フィルタと収集状況も確認してください。';
}
async function load() {
  const ticket=++revision;
  try {
    const response=await fetch('/api/schedules?'+params());
    if (!response.ok) throw new Error('取得失敗');
    const incoming=await response.json();
    if (ticket!==revision) return;
    const initial=!data; data=incoming;
    if (initial) {$('date').value=nasToday(); $('month-date').value=$('date').value.slice(0,7);}
    const selection=$('provider').value;
    const all=new Set([...Array.from($('provider').options).map(o => o.value),...data.tasks.map(t => t.provider)]);
    $('provider').replaceChildren(new Option('すべての提供元',''));
    for (const value of all) if (value) $('provider').add(new Option(value,value));
    $('provider').value=selection;
    $('export').href='/api/export.csv?'+params(); rows();
    if (activeView==='week') await timeline(ticket);
    if (activeView==='month') await monthCalendar(ticket);
  } catch {
    if (ticket===revision) $('notice').textContent='取得に失敗しました。接続を確認してください。表示済みの情報は古い可能性があります。';
  }
}
function setView(view) {
  activeView=view;
  for (const value of views) $(value).hidden=value!==view;
  for (const button of document.querySelectorAll('[data-view]')) button.setAttribute('aria-pressed',String(button.dataset.view===view));
  load();
}
for (const button of document.querySelectorAll('[data-view]')) button.onclick=() => setView(button.dataset.view);
for (const id of ['category','provider','enabled','date','mode','month-date']) $(id).onchange=load;
$('frequency').onchange=() => {try {localStorage.setItem('qsv-frequency',$('frequency').value);} catch {} load();};
let timer; $('search').oninput=() => {clearTimeout(timer); timer=setTimeout(load,250);};
for (const [id,delta] of [['prev',-7],['next',7]]) $(id).onclick=() => {const d=new Date($('date').value+'T12:00:00'); d.setDate(d.getDate()+delta); $('date').value=isoDate(d); load();};
for (const [id,delta] of [['month-prev',-1],['month-next',1]]) $(id).onclick=() => {const d=new Date($('month-date').value+'-01T12:00:00'); d.setMonth(d.getMonth()+delta); $('month-date').value=isoDate(d).slice(0,7); load();};
$('today').onclick=() => {$('date').value=nasToday(); load();};
$('month-today').onclick=() => {$('month-date').value=nasToday().slice(0,7); load();};
$('refresh').onclick=async() => {
  const button=$('refresh'); button.disabled=true;
  try {const response=await fetch('/api/refresh',{method:'POST'}); if (!response.ok) throw new Error(); await load();}
  catch {$('notice').textContent='再取得に失敗しました';}
  finally {button.disabled=false;}
};
load(); setInterval(load,60000);
