/* The browser presents a simulation. All proof checking and execution are server-side. */
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icons = {
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  code: '<path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-13-2 16"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
  book: '<path d="M12 5v16M3 4h5a4 4 0 0 1 4 2 4 4 0 0 1 4-2h5v15h-5a4 4 0 0 0-4 2 4 4 0 0 0-4-2H3Z"/>',
  reset: '<path d="M4 10a8 8 0 1 1 1 7M4 4v6h6"/>',
  play: '<path d="m8 5 11 7-11 7V5Z"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
};
function icon(name) { return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.activity}</svg>`; }
$$('[data-icon]').forEach(el => el.innerHTML = icon(el.dataset.icon));

const baseState = { final:false, authorised:false, current:false, susceptible:false, exception:false, family:false, access:false, overdue:false };
const events = [
  {time:'DAY 01', title:'Admitted with confusion', description:'Urine culture collected. Treatment begins.', setting:'Hospital', badge:'Admission', origin:'Published case · alias and culture ID added', heading:'A culture is still pending.', narrative:'David’s family brings him to hospital with worsening confusion. The care loop tracks the pending result.', state:{}, version:1},
  {time:'DAY 03', title:'Home, with a result still pending', description:'Discharged on TMP-SMX.', setting:'Discharged home', badge:'Handoff', origin:'Published case · alias and culture ID added', heading:'Discharge is a handoff.', narrative:'David has improved. The pending culture remains an open responsibility after he leaves hospital.', state:{}, version:1},
  {time:'DAY 05', title:'The culture changes the picture', description:'The organism is resistant to TMP-SMX.', setting:'Discharged home', badge:'Action needed', origin:'Published case · agent response simulated', heading:'A result needs a response.', narrative:'C17 is final. The discharge treatment conflicts with the reported susceptibility. A current clinical decision is required.', state:{final:true}, version:1},
  {time:'DEMO +4H', title:'No response. Escalate the review.', description:'The configured review deadline is reached.', setting:'Discharged home', badge:'Escalation', origin:'Simulated event · 4-hour deadline is a demo setting', heading:'Waiting has a limit.', narrative:'The review is overdue. On this timer event, the workflow must escalate to the designated clinical reviewer.', state:{final:true,overdue:true}, version:1},
  {time:'DEMO', title:'A clinician approves a current plan', description:'Treatment decision references C17, version 1.', setting:'Discharged home', badge:'Reviewed', origin:'Simulated clinician action · no medication is prescribed', heading:'A plan is only the beginning.', narrative:'A simulated clinician approves a plan consistent with the current culture. The family still needs to receive the instructions.', state:{final:true,authorised:true,current:true,susceptible:true,overdue:true}, version:1},
  {time:'DEMO', title:'The family confirms the instructions', description:'Acknowledgement is linked to the current plan.', setting:'Discharged home', badge:'Confirmed', origin:'Simulated acknowledgement · no message is sent', heading:'Instructions have reached the family.', narrative:'Receipt is confirmed for this plan. The workflow must still confirm that the patient can access the treatment.', state:{final:true,authorised:true,current:true,susceptible:true,family:true,overdue:true}, version:1},
  {time:'DEMO', title:'Treatment access is confirmed', description:'Every required closure condition is now met.', setting:'Discharged home', badge:'Loop closed', origin:'Simulated resolution · not a predicted clinical outcome', heading:'The loop can now close.', narrative:'Current clinical approval, treatment consistency, family instructions and treatment access are all recorded. Resolution is now permitted.', state:{final:true,authorised:true,current:true,susceptible:true,family:true,access:true,overdue:true}, version:1},
  {time:'WHAT IF?', title:'A corrected result reopens the loop', description:'C17 version 2 invalidates the earlier decision.', setting:'Discharged home', badge:'Reopened', origin:'Synthetic stress test · corrected result, new review clock', heading:'New evidence changes the obligation.', narrative:'The old approval refers to version 1. A corrected result requires a new review; yesterday’s proof of a plan cannot stand in for current evidence.', state:{final:true,authorised:true,current:false,susceptible:false,family:false,access:false,overdue:false}, version:2},
];
const actionInfo = {
  await_culture:['Await final culture', 'The pending result stays tracked. No treatment resolution is recorded.'],
  request_review:['Request clinical review', 'Route the culture and current treatment to the responsible clinician.'],
  escalate_review:['Escalate clinical review', 'The review deadline has passed. Notify the designated escalation owner.'],
  contact_family:['Confirm family instructions', 'Ask the care coordinator to confirm that the family received this plan.'],
  confirm_access:['Confirm treatment access', 'Ask the care coordinator to document access to the clinician-approved treatment.'],
  resolved:['Resolve this follow-up', 'Every required condition is met for the current evidence and plan.'],
};
let catalog = null;
let verification = null;
let verifiedSource = null;
let eventIndex = 2;
let playing = false;
let playTimer = null;
let requestEpoch = 0;
let eventEpoch = 0;
let modalPreviousFocus = null;
let generating = false;

async function api(path, payload) {
  const response = await fetch(path, payload === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}
function toast(message) { const el=$('#toast'); el.textContent=message; el.hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>el.hidden=true,4000); }
function showView(view) {
  if (!['workspace','proof','requirements'].includes(view)) return;
  $$('.view').forEach(el=>el.classList.toggle('active',el.id===`view-${view}`));
  $$('[data-view]').forEach(el=>{el.classList.toggle('active',el.dataset.view===view); if(el.closest('nav')) el.setAttribute('aria-current',el.dataset.view===view?'page':'false');});
  history.replaceState(null,'',`#${view}`);
  window.scrollTo({top:0,behavior:'instant'});
}
$$('[data-view]').forEach(button=>button.addEventListener('click',()=>showView(button.dataset.view)));
$('.brand').addEventListener('click',()=>showView('workspace'));
window.addEventListener('hashchange',()=>showView(location.hash.slice(1)));

function renderTimeline() {
  $('#timeline-list').innerHTML=events.map((e,index)=>`<button class="timeline-event ${index<eventIndex?'complete':''} ${index===eventIndex?'current':''}" data-event="${index}" aria-label="${escapeHTML(e.time+': '+e.title)}" ${index===eventIndex?'aria-current="step"':''}><span class="event-node">${index<eventIndex?icon('check'):String(index+1).padStart(2,'0')}</span><span class="event-content"><span class="event-time">${e.time}</span><strong class="event-title">${e.title}</strong><span class="event-description">${e.description}</span></span>${index===eventIndex?`<span class="event-badge">${e.badge}</span>`:''}</button>`).join('');
  $$('[data-event]').forEach(button=>button.addEventListener('click',()=>{stopPlayback();selectEvent(Number(button.dataset.event));}));
  $('#timeline-count').textContent=`${String(eventIndex+1).padStart(2,'0')} / ${String(events.length).padStart(2,'0')}`;
  $('#next-button').innerHTML=eventIndex===events.length-1?`Replay from start ${icon('reset')}`:`Next event ${icon('arrow')}`;
}
function evidenceRow(label, state) { return `<div class="evidence-row"><span class="evidence-mark ${state?'pass':'pending'}">${state?icon('check'):'–'}</span><span>${label}</span><span class="evidence-value">${state?'Confirmed':'Pending'}</span></div>`; }
async function selectEvent(index) {
  eventIndex=index;
  const epoch=++eventEpoch;
  const event=events[index], state={...baseState,...event.state};
  renderTimeline();
  $('#event-origin').textContent=event.origin;
  $('#setting').textContent=event.setting;
  $('#result-version').textContent=`C17 · v${event.version}`;
  $('#decision-title').textContent=event.heading;
  $('#decision-copy').textContent=event.description;
  $('#event-narrative').textContent=event.narrative;
  const ready=state.final&&state.authorised&&state.current&&(state.susceptible||state.exception)&&state.family&&state.access;
  $('#patient-status').textContent=ready?'Follow-up resolved':state.final?'Follow-up required':'Culture pending';
  $('#patient-status').className=`tag ${ready?'green':'warning'}`;
  $('#evidence-list').innerHTML=[evidenceRow('Final culture available',state.final),evidenceRow('Authorised, current clinical plan',state.authorised&&state.current),evidenceRow('Susceptibility or authorised exception',state.susceptible||state.exception),evidenceRow('Family instructions confirmed',state.family),evidenceRow('Treatment access confirmed',state.access)].join('');
  if(!verification?.valid || verifiedSource!==$('#code-editor').value) {
    $('#action-name').textContent='Execution blocked';
    $('#action-detail').textContent=verification?.valid?'The code changed. Verify it again before running.':'A valid proof is required before this candidate may run.';
    $('#action-box').classList.add('blocked');
    return;
  }
  $('#action-name').textContent='Evaluating verified protocol…';
  $('#action-box').classList.remove('blocked');
  try {
    const result=await api('/api/evaluate',{source:verifiedSource,state});
    if(epoch!==eventEpoch) return;
    const [name,detail]=actionInfo[result.action]||[result.action,''];
    $('#action-name').textContent=name;
    $('#action-detail').textContent=detail;
    $('#action-box').classList.toggle('resolved',result.action==='resolved');
  } catch(error) {
    if(epoch!==eventEpoch) return;
    $('#action-name').textContent='Execution blocked';
    $('#action-detail').textContent=error.message;
    $('#action-box').classList.add('blocked');
  }
}
function stopPlayback() {
  playing=false;clearTimeout(playTimer);
  $('#play-button').innerHTML=`${icon('play')} Play patient story`;
}
async function tick() {
  if(!playing) return;
  await selectEvent(eventIndex+1);
  if(!playing) return;
  if(eventIndex===events.length-1) { stopPlayback();return; }
  playTimer=setTimeout(tick,3300);
}
$('#play-button').addEventListener('click',async()=>{
  if(playing) {stopPlayback();return;}
  if(!verification?.valid||verifiedSource!==$('#code-editor').value) {showView('proof');toast('Verify the current protocol before playing the story.');return;}
  playing=true;$('#play-button').innerHTML=`${icon('pause')} Pause story`;
  await selectEvent(0); if(playing) playTimer=setTimeout(tick,3300);
});
$('#next-button').addEventListener('click',()=>{stopPlayback();selectEvent((eventIndex+1)%events.length);});
$('#reset-button').addEventListener('click',()=>{stopPlayback();selectEvent(0);toast('Patient story reset. Your code is unchanged.');});

function renderGate() {
  const valid=verification?.valid&&verifiedSource===$('#code-editor').value;
  $('#verification-card').classList.toggle('rejected',!valid);
  $('#gate-title').textContent=valid?'The protocol is verified.':'This protocol cannot run.';
  $('#gate-copy').textContent=valid?`The independent checker accepted the proof across all ${verification.domain_size||256} states in the model.`:'The candidate has not satisfied the fixed requirements. Inspect the result in the proof workspace.';
  $('#gate-hash').textContent=valid?`SHA-256 · ${verification.code_hash?.slice(0,16)||'checked'}`:'PROOF REQUIRED · EXECUTION BLOCKED';
  $('#code-state').textContent=valid?'Verified':'Unverified';
  $('#code-state').className=`tag ${valid?'green':'warning'}`;
}
function renderProof(result) {
  const valid=Boolean(result.valid);
  $('#proof-status').className=`proof-status ${valid?'accepted':'rejected'}`;
  $('#proof-status').innerHTML=`<div class="verification-icon">${icon(valid?'shield':'code')}</div><div><h3>${valid?'Proof accepted':'Candidate rejected'}</h3><p>${valid?'The exact program satisfies the fixed specification.':escapeHTML(result.error||'This program does not meet the independent requirements.')}</p></div>`;
  $('#proof-metrics').innerHTML=[['States checked',result.states_checked??0],['Proof steps',valid?(result.proof_steps??result.theorem_count??'—'):'—'],['Check time',`${Math.round(result.elapsed_ms||0)} ms`]].map(([label,value])=>`<div class="metric"><span class="metric-value">${typeof value==='number'?value.toLocaleString():value}</span><span class="metric-label">${label}</span></div>`).join('');
  const traces=result.trace||[];
  $('#proof-steps').innerHTML=traces.slice(0,6).map((step,i)=>{const title=typeof step==='string'?step:(step.title||step.rule||step.label||step.message||'Proof step');const detail=typeof step==='object'?(step.detail||step.description||''):'';return `<div class="proof-step"><span class="step-number">${String(i+1).padStart(2,'0')}</span><div class="step-copy"><strong>${escapeHTML(title)}</strong>${detail?`<p>${escapeHTML(detail)}</p>`:''}</div></div>`;}).join('');
  const ce=result.counterexample;
  $('#counterexample').hidden=!ce;
  if(ce) {
    const failures=(ce.violations||result.violations||[]).map(v=>typeof v==='string'?v:v.message||v.title||v.description||v.id||JSON.stringify(v));
    $('#counterexample').innerHTML=`<div class="eyebrow">A CONCRETE COUNTEREXAMPLE</div><h3>This code would ${escapeHTML(actionInfo[ce.action]?.[0]?.toLowerCase()||ce.action)}.</h3><p>${escapeHTML(failures.join(' · '))}</p><div class="counterexample-grid">${Object.entries(ce.state||{}).map(([key,value])=>`<span><code>${escapeHTML(key)}</code><strong class="${value?'green-text':''}">${value?'True':'False'}</strong></span>`).join('')}</div><p class="counterexample-note">A failing input is enough to reject the entire candidate.</p>`;
  }
  $('#download-proof').disabled=!valid||!result.certificate;
}
async function verifyCurrent() {
  stopPlayback();
  const source=$('#code-editor').value;
  const epoch=++requestEpoch;
  verifiedSource=null;verification=null;
  $('#verify-button').disabled=true;
  $('#verify-button').innerHTML='<span class="spinner"></span> Checking proof…';
  $('#code-state').textContent='Checking';
  $('#proof-status').innerHTML='<div class="spinner"></div><div><h3>Building and checking the certificate…</h3><p>Every state is checked against the independent specification.</p></div>';
  $('#download-proof').disabled=true;
  renderGate();selectEvent(eventIndex);
  try {
    const result=await api('/api/verify',{source});
    if(epoch!==requestEpoch||source!==$('#code-editor').value) return;
    verification=result;verifiedSource=result.valid?source:null;
    renderProof(result);renderGate();await selectEvent(eventIndex);
    $('#connection-error').hidden=true;
  } catch(error) {
    if(epoch!==requestEpoch)return;
    verification={valid:false,error:error.message};renderProof(verification);renderGate();
    $('#connection-error').textContent=`Could not verify: ${error.message}`;$('#connection-error').hidden=false;
  } finally {
    if(epoch===requestEpoch){$('#verify-button').disabled=false;$('#verify-button').innerHTML=`${icon('shield')} Verify protocol`;}
  }
}
function invalidateCode() {
  ++requestEpoch;++eventEpoch;stopPlayback();verifiedSource=null;verification=null;
  $('#verify-button').disabled=false;$('#verify-button').innerHTML=`${icon('shield')} Verify protocol`;
  $('#download-proof').disabled=true;
  $('#proof-status').innerHTML=`<div class="verification-icon">${icon('code')}</div><div><h3>Code changed. Proof required.</h3><p>The previous certificate no longer authorises execution.</p></div>`;
  $('#proof-metrics').innerHTML='';$('#proof-steps').innerHTML='';$('#counterexample').hidden=true;
  renderGate();selectEvent(eventIndex);
}
$('#code-editor').addEventListener('input',invalidateCode);
$('#code-editor').addEventListener('keydown',event=>{if(event.key==='Tab'){event.preventDefault();const el=event.target,start=el.selectionStart;el.setRangeText('    ',start,el.selectionEnd,'end');invalidateCode();}});
$('#candidate-select').addEventListener('change',()=>{const candidate=catalog.variants.find(v=>v.id===$('#candidate-select').value);if(candidate){$('#code-editor').value=candidate.source;$('#candidate-origin').textContent='Prepared candidate · editable code';invalidateCode();toast(candidate.description||'Candidate loaded. Verify it against the same specification.');}});
$('#verify-button').addEventListener('click',verifyCurrent);
$('#generate-button').addEventListener('click',async()=>{
  if(generating)return;
  generating=true;stopPlayback();
  $('#generate-button').disabled=true;$('#generate-button').innerHTML='<span class="spinner"></span> Drafting with AI…';
  $('#candidate-select').disabled=true;$('#code-editor').readOnly=true;$('#verify-button').disabled=true;
  try {
    const result=await api('/api/generate',{prompt:$('#generation-prompt').value});
    $('#code-editor').value=result.source;$('#candidate-select').value='';
    $('#candidate-origin').textContent=`Live AI draft · ${result.model}`;
    invalidateCode();
    $('#generate-button').innerHTML='<span class="spinner"></span> Verifying AI draft…';
    await verifyCurrent();
    toast(verification?.valid?'Live AI draft accepted by the independent checker.':'AI draft rejected. Inspect the counterexample or edit the code.');
  } catch(error) {
    $('#generation-description').textContent=`Live drafting unavailable: ${error.message} Prepared examples and manual editing still work.`;
    toast(`AI drafting failed: ${error.message}`);
  } finally {
    generating=false;$('#candidate-select').disabled=false;$('#code-editor').readOnly=false;
    $('#verify-button').disabled=false;$('#generate-button').disabled=false;
    $('#generate-button').innerHTML=`${icon('code')} Generate & verify`;
  }
});
$('#download-proof').addEventListener('click',()=>{
  if(!verification?.valid||!verification.certificate)return;
  const url=URL.createObjectURL(new Blob([verification.certificate],{type:'text/plain'}));
  const a=document.createElement('a');a.href=url;a.download=`david-c17-${verification.code_hash.slice(0,12)}.mm`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});

function showModal(title,html) {modalPreviousFocus=document.activeElement;$('#modal-title').textContent=title;$('#modal-body').innerHTML=html;$('#modal-overlay').hidden=false;document.body.style.overflow='hidden';$('#close-modal').focus();}
function closeModal() {$('#modal-overlay').hidden=true;document.body.style.overflow='';modalPreviousFocus?.focus();}
$('#close-modal').addEventListener('click',closeModal);
$('#modal-overlay').addEventListener('click',event=>{if(event.target===$('#modal-overlay'))closeModal();});
document.addEventListener('keydown',event=>{
  if($('#modal-overlay').hidden)return;
  if(event.key==='Escape')closeModal();
  if(event.key==='Tab'){const focusable=$$('.modal button,.modal a,.modal textarea');const first=focusable[0],last=focusable.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}
});
const scopeHTML=`<p><strong>The guarantee:</strong> every assignment of the eight Boolean inputs in this model produces an action allowed by the separate, fixed specification. The same parsed program is interpreted for the patient replay.</p><p>The proof is a real substitution-based derivation checked by a Metamath-style kernel. The trusted theory, parser, specification encoding, record-to-Boolean mapping and interpreter remain part of the trusted implementation.</p><p><strong>The boundary:</strong> this does not establish that medical requirements are clinically correct, records are accurate, notifications are delivered, or a patient will recover. Deadline behavior is checked when a timer event is supplied.</p><p>Approvals, evidence freshness and acknowledgements are simulated Boolean inputs here. A production adapter must establish those facts from authenticated, versioned records. The demo is not connected to an EHR and takes no clinical action.</p>`;
$('#scope-button').addEventListener('click',()=>showModal('What the proof guarantees',scopeHTML));
$('#about-button').addEventListener('click',()=>showModal('Verified Clinical Care Loop',`<p class="modal-lead">AI can propose a protocol.<br>A proof determines whether it may run.</p><p>This prototype demonstrates live AI drafting when configured, a separate specification and an independent proof checker inspired by Metamath. Prepared examples let you reproduce specific failures.</p><h3>The story</h3><p>Inspired by the published <a href="https://psnet.ahrq.gov/web-mm/treatment-challenges-after-discharge" target="_blank" rel="noopener">AHRQ PSNet case</a>. David, C17 and all simulated interventions are demo constructs. This is not a Stanford patient record.</p><h3>The proof</h3>${scopeHTML}`));
$('#kernel-button').addEventListener('click',async()=>{
  try {const result=await api('/api/kernel');showModal('The independent proof checker',`<p>The checking core uses typed substitution, exact premise matching and a final goal check. It follows the companion proof-carrying-code implementation.</p><p><strong>${result.verify_lines} physical lines in verify().</strong> Parsing, the trusted theory and the application are separate. We do not claim the complete trusted system is ten lines.</p><pre class="kernel-code">${escapeHTML(result.source)}</pre>`);}catch(error){toast(error.message);}
});

async function init() {
  try {
    catalog=await api('/api/catalog');
    $('#generation-prompt').value=catalog.generation_prompt||'Generate David’s post-discharge culture follow-up workflow, satisfying every fixed requirement.';
    $('#generate-button').disabled=!catalog.generator?.available;
    $('#generator-model').textContent=catalog.generator?.model||'Not configured';
    $('#generation-description').textContent=catalog.generator?.available?'Live AI writes the code. The independent checker decides whether it can run.':'Set OPENAI_API_KEY on the server to enable live drafting. Prepared candidates work without a key.';
    $('#candidate-select').innerHTML=catalog.variants.map(v=>`<option value="${escapeHTML(v.id)}">${escapeHTML(v.name)}</option>`).join('');
    $('#code-editor').value=catalog.default_source||catalog.variants[0].source;
    $('#spec-grid').innerHTML=(catalog.requirements||[]).map((req,i)=>`<article class="card spec-card"><span class="spec-number">${String(i+1).padStart(2,'0')}</span><h2 class="spec-title">${escapeHTML(req.title||req.name)}</h2><p class="spec-description">${escapeHTML(req.description)}</p>${req.expression?`<pre class="spec-expression">${escapeHTML(req.expression)}</pre>`:''}</article>`).join('');
    $('#spec-source').textContent=catalog.spec_source||catalog.specification||'See the separate requirements above.';
    $('#spec-hash').textContent=catalog.spec_hash?`SHA-256 · ${catalog.spec_hash.slice(0,12)}`:'';
    const view=location.hash.slice(1);if(view)showView(view);
    await verifyCurrent();
  } catch(error) {
    $('#connection-error').textContent=`The local proof server is unavailable: ${error.message}. Start it with python3 server.py and reload.`;$('#connection-error').hidden=false;
    $('#gate-title').textContent='Proof server unavailable';$('#gate-copy').textContent='Start the local server to verify and run this simulation.';
    renderTimeline();
  }
}
init();
