const $ = id => document.getElementById(id);
let current = null, records = [];
const reasons = {language_unsupported_or_uncertain:'请使用中文咨询',out_of_domain_or_uncertain:'业务信息不足或范围外',intent_out_of_scope:'该业务不在本版14类范围内',sensitive_request:'涉及敏感请求',sensitive_intent:'需人工专席处理',multiple_intents_possible:'包含多个诉求',instruction_like_input:'包含修改系统规则的指令',low_confidence:'分类置信度不足',ambiguous_candidates:'候选意图接近',model_unavailable:'模型不可用',knowledge_missing_or_invalid:'处理说明缺失或格式错误',knowledge_tool_failure:'知识工具失败'};
const states = {received:'接收请求',validated:'中文校验与脱敏',classified:'中文分类完成',needs_review:'等待人工复核',routed:'已分配演示队列',closed:'分流任务结束',failed:'执行失败'};
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function message(text){$('message').textContent=text;$('message').hidden=!text;}
async function api(url,options={}){const response=await fetch(url,options);const data=await response.json();if(!response.ok)throw Error(data.error||'请求失败');return data;}
function post(url,body){return api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
function tab(name){document.querySelectorAll('.tab').forEach(el=>el.hidden=el.id!=='tab-'+name);document.querySelectorAll('.nav').forEach(el=>el.classList.toggle('active',el.dataset.tab===name));$('page-name').textContent={work:'处理工单',review:'复核工作台',metrics:'实验结果'}[name];if(name==='review')renderTable();}
document.querySelectorAll('.nav').forEach(el=>el.addEventListener('click',()=>tab(el.dataset.tab)));
const samples={balance:'我想查询一下银行账户的余额',safety:'我的银行卡被偷了，请冻结我的账户',outside:'请推荐一只值得购买的股票'};
document.querySelectorAll('.sample').forEach(el=>el.addEventListener('click',()=>{$('ticket-text').value=samples[el.dataset.example];$('ticket-text').focus();}));
async function refresh(){records=(await api('/api/tickets')).tickets;$('total-count').textContent=records.length;$('auto-count').textContent=records.filter(r=>r.mode==='automatic').length;const n=records.filter(r=>r.status==='needs_review').length;$('review-count').textContent=n;$('nav-count').textContent=n;$('closed-count').textContent=records.filter(r=>r.review).length;renderTable();}
function renderTable(){const filtered=records.filter(r=>!$('filter').value||r.status===$('filter').value);$('ticket-rows').replaceChildren();$('list-empty').hidden=!!filtered.length;filtered.forEach(r=>{const tr=node('tr');[r.id,r.text_preview,r.suggested_queue||'待判断',states[r.status]||r.status].forEach(v=>tr.append(node('td',v)));const td=node('td'),button=node('button',r.status==='needs_review'?'复核 →':'查看','secondary');button.addEventListener('click',()=>{renderResult(r);tab('work');$('result-status').scrollIntoView({behavior:'smooth',block:'center'});});td.append(button);tr.append(td);$('ticket-rows').append(tr);});}
$('filter').addEventListener('change',renderTable);
function renderResult(r){
  current=r;$('empty-result').hidden=true;$('result').hidden=false;$('result-status').textContent=states[r.status]||r.status;$('result-status').className='tag'+(r.status==='needs_review'?' review':'');
  $('result-summary').replaceChildren(node('p','编号 '+r.id+' · 中文模型 '+r.model_version),node('p','建议队列：'+(r.suggested_queue||'待判断')+(r.final_queue?' · 最终队列：'+r.final_queue:'')));
  if(r.final_intent)$('result-summary').append(node('p','最终意图：'+r.final_intent));
  if(r.review)$('result-summary').append(node('p','复核理由：'+r.review.reason));
  $('candidate-list').replaceChildren();
  r.candidates.forEach(c=>{const wrapper=node('div',undefined,'candidate'),line=node('div');line.append(node('span',c.intent),node('strong',(c.probability*100).toFixed(1)+'%'));const bar=node('div',undefined,'bar'),fill=node('span');fill.style.width=(c.probability*100)+'%';bar.append(fill);wrapper.append(line,bar);$('candidate-list').append(wrapper);});
  $('result-reasons').textContent=r.review_reasons.length?'复核原因：'+r.review_reasons.map(x=>reasons[x]||x).join('；'):'符合当前自动分流策略。概率是模型估计，不保证判断正确。';
  $('knowledge').replaceChildren();if(r.knowledge){$('knowledge').append(node('p',r.knowledge.instructions),node('p',r.knowledge.id+' · '+r.knowledge.version),node('p',r.knowledge.disclaimer));}else $('knowledge').textContent='未取得可用说明，请人工接管。';
  $('explanation').textContent='中文字符特征的正向贡献：'+(r.explanation.map(x=>x.feature+' ('+x.contribution.toFixed(3)+')').join('、')||'暂无')+'。仅解释分类器的线性贡献，不是业务事实。';
  $('trace').replaceChildren();r.trace.forEach(s=>$('trace').append(node('li',(states[s.state]||s.state)+' · '+new Date(s.at).toLocaleTimeString())));
  $('review-form').hidden=r.status!=='needs_review';$('review-intent').value=r.suggested_intent||$('review-intent').options[0]?.value;$('review-reason').value='';
}
$('submit').addEventListener('click',async()=>{message('');$('submit').disabled=true;try{const body={text:$('ticket-text').value};if($('ticket-id').value.trim())body.ticket_id=$('ticket-id').value.trim();const r=await post('/api/tickets',body);renderResult(r);await refresh();if(r.reused)message('该编号与内容已存在，展示原记录，没有重复创建。');}catch(e){message(e.message);}finally{$('submit').disabled=false;}});
$('confirm-review').addEventListener('click',async()=>{if(!current)return;$('confirm-review').disabled=true;message('');try{renderResult(await post('/api/tickets/'+encodeURIComponent(current.id)+'/review',{intent:$('review-intent').value,reason:$('review-reason').value}));await refresh();}catch(e){message(e.message);}finally{$('confirm-review').disabled=false;}});
$('upload').addEventListener('click',async()=>{const file=$('csv-file').files[0];if(!file){message('请选择UTF-8 CSV文件。');return;}const form=new FormData();form.append('file',file);$('upload').disabled=true;message('');try{const r=await api('/api/batch',{method:'POST',body:form});$('batch-result').hidden=false;$('batch-result').textContent='共 '+r.total+' 条，成功 '+r.results.length+' 条，错误 '+r.errors.length+' 条。\n'+r.errors.map(e=>'第 '+e.line+' 行：'+e.error).join('\n');await refresh();}catch(e){message(e.message);}finally{$('upload').disabled=false;}});
function percent(n){return n==null?'不适用':(n*100).toFixed(1)+'%';}
async function metrics(){
  const m=await api('/api/metrics');if(m.status==='not_evaluated'){$('metric-note').textContent='尚未运行中文评估，请先执行 python -m triage.evaluate。';return;}
  const cards=[['中文保留测试样本',String(m.test_count)],['宏平均F1',percent(m.models['中文校准模型'].macro_f1)],['自动分流覆盖率',percent(m.routing.coverage)],['自动队列正确率',percent(m.routing.queue_precision)],['自动意图正确率',percent(m.routing.intent_precision)],['单请求P95耗时',m.performance.p95_ms.toFixed(1)+' 毫秒']];
  cards.forEach(([label,value])=>{const card=node('div',undefined,'metric-card');card.append(node('span',label),node('strong',value));$('metric-cards').append(card);});
  Object.entries(m.models).forEach(([key,value])=>{const tr=node('tr');[key,percent(value.accuracy),percent(value.macro_f1)].forEach(x=>tr.append(node('td',x)));$('metric-rows').append(tr);});
  $('metric-note').textContent='中文子集自建保留测试集，样本较少且表达集中，不代表生产效果。'+m.boundary.passed+'/'+m.boundary.total+' 条构造边界通过；未开展访谈或人工耗时实验。';
}
(async()=>{try{const [health,labels]=await Promise.all([api('/api/health'),api('/api/labels')]);$('model-state').textContent='中文模型就绪 · '+health.model.version;labels.labels.forEach(x=>{const option=node('option',x.intent+' · '+x.queue);option.value=x.intent;$('review-intent').append(option);});await refresh();await metrics();}catch(e){$('model-state').textContent='连接失败';message(e.message);}})();
