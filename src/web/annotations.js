'use strict';
const selectedTags = new Set();
let editingTask = null;
async function writeAnnotation(url,method,body) {
  const response=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json().catch(() => null);
  if (!response.ok) {
    const error=new Error(typeof result?.detail==='string' ? result.detail : '操作に失敗しました。入力内容と接続を確認してください。');
    error.status=response.status; throw error;
  }
  return result;
}
function tagLabel(tag,checked,onchange) {
  const label=el('label',undefined,'tag-choice'), input=el('input');
  input.type='checkbox'; input.value=String(tag.id); input.checked=checked; input.onchange=() => onchange(input.checked);
  label.append(input,el('span',tag.name)); return label;
}
function renderTagFilters(tags) {
  const existing=new Set(tags.map(t => t.id)); let changed=false;
  for (const id of selectedTags) if (!existing.has(id)) {selectedTags.delete(id); changed=true;}
  $('tag-options').replaceChildren(...tags.map(tag => tagLabel(tag,selectedTags.has(tag.id),checked => {
    checked ? selectedTags.add(tag.id) : selectedTags.delete(tag.id); load();
  })));
  if (!tags.length) $('tag-options').append(el('span','タグは未作成です。'));
  return changed;
}
function annotationEditButton(task) {
  const button=el('button','表示名・タグを編集','annotation-edit');
  const collection=data.collections.find(c => c.collector===task.source.collector);
  button.disabled=!task.definition_id || !task.annotation_version || collection?.stale;
  button.onclick=() => openAnnotationEditor(task);
  return button;
}
function openAnnotationEditor(task) {
  hideCommands(); editingTask=task;
  $('annotation-title').textContent=task.name;
  $('display-name').value=task.display_name;
  $('display-name').placeholder=task.original_name;
  $('annotation-scope').textContent=task.duplicate_count>1 ? `同じコマンドの ${task.duplicate_count} 行に共通で反映します。` : '';
  const assigned=new Set(task.tags.map(t => t.id));
  $('annotation-tags').replaceChildren(...data.tags.map(tag => tagLabel(tag,assigned.has(tag.id),() => {})));
  if (!data.tags.length) $('annotation-tags').append(el('p','「タグ・表示名」画面でタグを作成できます。'));
  $('annotation-message').textContent=''; $('annotation-reload').hidden=true;
  if (!$('annotation-editor').open) $('annotation-editor').showModal();
}
function closeAnnotationEditor() {$('annotation-editor').close(); editingTask=null;}
async function saveAnnotation(event) {
  event.preventDefault(); const task=editingTask, button=$('annotation-save'); button.disabled=true;
  try {
    const ids=Array.from($('annotation-tags').querySelectorAll('input:checked')).map(input => Number(input.value));
    await writeAnnotation('/api/annotations/'+encodeURIComponent(task.definition_id),'PUT',{
      version:task.annotation_version, display_name:$('display-name').value,tag_ids:ids
    });
    closeAnnotationEditor(); if ($('detail').open) closeDetail(); await load();
  } catch (error) {
    $('annotation-message').textContent=error.message; $('annotation-reload').hidden=error.status!==409;
  } finally {button.disabled=false;}
}
async function reloadAnnotationEditor() {
  const key=editingTask?.definition_id; await load();
  const current=data.collections.flatMap(c => c.tasks).find(t => t.definition_id===key);
  if (current) openAnnotationEditor(current);
  else $('annotation-message').textContent='定義が見つかりません。再取得して確認してください。';
}
function annotationTargetLabel(task) {
  return `${task.name}${task.display_name ? ` / ${task.original_name}` : ''} · ${task.schedule.expression}${task.duplicate_count>1 ? `（${task.duplicate_count}行）` : ''}`;
}
async function renderAnnotationManager(ticket) {
  const [response, schedules]=await Promise.all([fetch('/api/annotations'),fetch('/api/schedules?frequency=all')]);
  if (!response.ok || !schedules.ok) throw new Error('表示名とタグの取得に失敗しました');
  const annotations=await response.json(), all=await schedules.json();
  if (ticket!==revision) return;
  const tagRows=all.tags.map(tag => {
    const form=el('form',undefined,'tag-management-row'), input=el('input'), save=el('button','名前を変更'), remove=el('button','削除');
    input.value=tag.name; input.maxLength=40; input.required=true; input.setAttribute('aria-label',`タグ名: ${tag.name}`);
    save.type='submit'; remove.type='button';
    form.onsubmit=async event => {
      event.preventDefault(); save.disabled=true;
      try {await writeAnnotation('/api/tags/'+tag.id,'PUT',{name:input.value,version:tag.version}); await load();}
      catch(error) {$('tag-message').textContent=error.message;} finally {save.disabled=false;}
    };
    remove.onclick=async() => {
      if (!confirm(`タグ「${tag.name}」をすべてのジョブから外して削除しますか？`)) return;
      remove.disabled=true;
      try {await writeAnnotation('/api/tags/'+tag.id,'DELETE',{version:tag.version}); await load();}
      catch(error) {$('tag-message').textContent=error.message;} finally {remove.disabled=false;}
    };
    form.append(input,save,remove); return form;
  });
  $('tag-management').replaceChildren(...tagRows);
  const current=new Map(all.tasks.map(task => [task.definition_id,task]));
  const byDefinition=new Map(annotations.map(annotation => [annotation.definition_id,annotation]));
  const records=annotations.filter(a => a.display_name || a.tags.length).map(annotation => {
    const task=current.get(annotation.definition_id), card=el('article',undefined,'card annotation-record');
    card.append(el('h3',annotation.display_name || task?.name || '表示名なし'),
      el('p',`タグ: ${annotation.tags.map(t => t.name).join(' / ') || 'なし'}`),
      el('p',`${{present:'現在のジョブ',absent:'現在は見つからないジョブ',unknown:'現在の有無は未確認'}[annotation.presence]} · 最終取得 ${fmt(annotation.last_seen_at)}`));
    if (!task) card.append(el('small',annotation.definition_id));
    if (task) card.append(annotationEditButton(task));
    const form=el('form',undefined,'annotation-copy'), select=el('select'), overwrite=el('input'), overwriteLabel=el('label'), copy=el('button','表示名とタグをコピー'), remove=el('button','表示名とタグをリセット'), message=el('p');
    select.setAttribute('aria-label','コピー先のジョブ'); select.required=true; select.add(new Option('コピー先のジョブを選択',''));
    const targets=new Map();
    for (const [key,value] of current) {
      const record=byDefinition.get(key);
      if (key===annotation.definition_id || record?.presence!=='present') continue;
      targets.set(key,value); select.add(new Option(annotationTargetLabel(value),key));
    }
    overwrite.type='checkbox'; overwriteLabel.append(overwrite,el('span','コピー先の表示名とタグを置き換える'));
    remove.type='button'; message.setAttribute('role','status');
    form.onsubmit=async event => {
      event.preventDefault(); const target=targets.get(select.value); if (!target) return;
      if (!confirm(`「${annotation.display_name || task?.name || '表示名なし'}」の表示名とタグを「${annotationTargetLabel(target)}」の ${target.duplicate_count} 行にコピーしますか？`)) return;
      copy.disabled=true;
      try {
        await writeAnnotation('/api/annotations/copy','POST',{source_id:annotation.definition_id,target_id:target.definition_id,
          source_version:annotation.version,target_version:target.annotation_version,overwrite:overwrite.checked});
        await load();
      } catch(error) {message.textContent=error.message;} finally {copy.disabled=false;}
    };
    remove.onclick=async() => {
      if (!confirm('このジョブの表示名を元に戻し、タグをすべて外しますか？')) return;
      remove.disabled=true;
      try {await writeAnnotation('/api/annotations/'+encodeURIComponent(annotation.definition_id),'DELETE',{version:annotation.version}); await load();}
      catch(error) {message.textContent=error.message;} finally {remove.disabled=false;}
    };
    form.append(select,overwriteLabel,copy,remove,message); card.append(form); return card;
  });
  $('annotation-records').replaceChildren(...records);
  if (!records.length) $('annotation-records').append(el('p','保存された表示名・タグはありません。ジョブの詳細画面から編集できます。'));
}
function initAnnotations() {
  $('tag-match').onchange=load;
  $('clear-tags').onclick=() => {selectedTags.clear(); load();};
  $('annotation-form').onsubmit=saveAnnotation;
  $('annotation-cancel').onclick=closeAnnotationEditor;
  $('annotation-reload').onclick=reloadAnnotationEditor;
  $('annotation-editor').addEventListener('close',() => {editingTask=null;});
  $('tag-create').onsubmit=async event => {
    event.preventDefault(); const button=$('tag-create-button'); button.disabled=true;
    try {await writeAnnotation('/api/tags','POST',{name:$('new-tag').value}); $('new-tag').value=''; $('tag-message').textContent=''; await load();}
    catch(error) {$('tag-message').textContent=error.message;} finally {button.disabled=false;}
  };
}
