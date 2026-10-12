const openDetails = new Set(), walletDetails = new Map(), walletLoading = new Set();
let currentPage = 'new';
let paperAccount='aggressive';
let accountControlBusy=false;
try {const saved=localStorage.getItem('nexus-paper-account');if(['original','aggressive'].includes(saved))paperAccount=saved;} catch {}
let researchMint=null, researchData=null;
let connectionData={};
let searchQuery = '';
let tokenSort = 'default';
let walletRegistry = {items:[],status:{}};
let status = {}, opportunities = [], trades = [], launches = {items:[],feed:{}}, trending = {items:[]}, watched = [];
let windowSize = '5m', selectedMint = null, details = [], loading = false, refreshError = '';
async function getData(path) {
  const response = await fetch(path, {cache:'no-store'});
  if(response.status===401){location.replace('/login');throw new Error('Please sign in again.');}
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function money(value) {
  if (value == null) return '—';
  return '$' + Number(value).toLocaleString(undefined,{maximumFractionDigits:2});
}
function stamp(value) { return value ? new Date(value*1000).toLocaleString() : '—'; }
function age(value) {
  if (value == null) return 'Unknown';
  const mins = Math.max(0,Math.floor(value));
  return mins < 60 ? mins+'m' : mins < 1440 ? Math.floor(mins/60)+'h' : Math.floor(mins/1440)+'d';
}
let accountRequest=0;
async function refreshAccountSummary() {
  const request=++accountRequest;
  try {
    const next=await getData('/api/status');
    if(request!==accountRequest)return;
    status=next;updateAccountSummary();render();
  } catch(error) {if(request===accountRequest){refreshError='Balance update failed; displayed balances may be stale.';render();}}
}
async function refreshDashboard() {
  if (loading) return;
  loading = true;
  try {
    const accountUpdate=refreshAccountSummary();
    const results = await Promise.all([getData('/api/opportunities'),
      getData('/api/trades'),getData('/api/new-pairs'), getData('/api/trending?window='+windowSize), getData('/api/watch-history'),getData('/api/wallets'),getData('/api/connections')]);
    [opportunities,trades,launches,trending,watched,walletRegistry,connectionData] = results;
    await accountUpdate;
    refreshError = '';
    updateAccountSummary();
    document.getElementById('mode').textContent = status.paper_mode ? 'PAPER':'LIVE';

    if(researchMint && currentPage==='research') researchData=await getData('/api/research/'+encodeURIComponent(researchMint));
    if (selectedMint) details = await getData('/api/watch-history?mint='+encodeURIComponent(selectedMint));
  } catch (error) { refreshError='Update failed ('+error.message+'). Displayed data may be stale.'; }
  finally { loading=false; render(); }
}
function compactMoney(value) {
  if (value == null) return '—';
  return '$'+Number(value).toLocaleString(undefined,{notation:'compact',maximumFractionDigits:1});
}
function imageUrl(value) {
  try { const u=new URL(value); return u.protocol==='https:' ? u.href : ''; } catch { return ''; }
}
function trackedWalletSection(mint, price) {
  const data=walletDetails.get(mint);
  if(!data) return '<h4>Tracked wallets holding this coin</h4><p>Open details to check current balances.</p>';
  const messages={not_configured:'No tracked wallets configured.',rpc_not_configured:'Wallet balance connection is not configured.',invalid_configuration:'Tracked-wallet configuration needs correction.',unavailable:'Wallet balances are currently unavailable.',error:'Could not load wallet balances. Try reopening details.'};
  let html='<h4>Tracked wallets holding this coin</h4>';
  if(messages[data.status]) return html+'<p>'+messages[data.status]+'</p>';
  if(data.status==='loading') return html+'<p>Checking wallet positions…</p>';
  const holders=data.holders || [];
  if(!holders.length) html+='<p>'+ (data.status==='partial' ? 'No holdings found among successfully checked wallets.':'None of your tracked wallets currently hold this coin.')+'</p>';
  else html+='<ul class="wallet-list">'+holders.map(w=>`<li><div><a href="https://solscan.io/account/${encodeURIComponent(w.address)}" target="_blank" rel="noopener noreferrer">${escapeHtml(w.label)}</a><small class="mint">${escapeHtml(w.address)}</small>${w.tags?.length ? `<small>${escapeHtml(w.tags.join(' · '))}</small>`:''}</div><div class="wallet-balance"><strong>${escapeHtml(w.balance)} tokens</strong>${price>0 ? `<small>≈ ${compactMoney(Number(w.balance)*price)}</small>`:''}</div></li>`).join('')+'</ul>';
  if(data.status==='partial') html+=`<p>${Number(data.configured_count)-Number(data.checked_count)} wallet checks unavailable. Results are incomplete.</p>`;
  html+=`<p>Checked ${Number(data.checked_count)}/${Number(data.configured_count)} wallets · ${stamp(data.checked_at)}<br>Current on-chain holdings; entry price and profit are not available.</p>`;
  return html;
}
function tokenCard(item, history=false) {
  const t=item.token || {}, entry=item.entry || {}, fast=item.fast || {};
  const score=entry.combined_score ?? fast.score;
  const reasons=[...((item.filter || {}).reasons || []),...(entry.reasons || [])];
  const symbol=String(t.symbol || '?').replace(/^\$+/, '');
  const volumeWindow=currentPage==='trending' ? windowSize:'5m';
  const volume=t[{'5m':'volume_5m_usd','1h':'volume_1h_usd','24h':'volume_24h_usd'}[volumeWindow]];
  const created=item.created_at || t.created_at;
  const elapsed=age(created ? (Date.now()/1000-created)/60 : t.age_minutes);
  const change=t.price_change_5m_pct;
  const image=imageUrl(t.image_url);
  const prettyStatus={awaiting_data:'Indexing',watch:'Watching',candidate:'Candidate',rejected:'Filtered'}[item.status] || 'Indexing';
  return `<article class="coin-card">
    <div class="coin-top"><div class="coin-heading"><div class="coin-avatar">${image ? `<img src="${escapeHtml(image)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer">`:escapeHtml(symbol.slice(0,1))}</div>
    <div class="coin-identity"><div class="coin-title"><h3>$${escapeHtml(symbol)}</h3>${t.mint ? `<button class="copy-ca" data-copy-ca="${escapeHtml(t.mint)}" aria-label="Copy contract address for ${escapeHtml(symbol)}">Copy CA</button>`:''}</div><p class="coin-name">${escapeHtml(t.name)}</p></div></div>
    <div class="metrics"><div><small>Bot score</small><strong title="Bot setup score out of 100">${score == null ? '—':Math.round(score)+'/100'}</strong></div><div><small>${t.market_cap_is_fdv ? 'FDV':'Market cap'}</small><strong title="${money(t.market_cap_usd)}">${compactMoney(t.market_cap_usd)}</strong></div><div><small>Volume · ${volumeWindow}</small><strong title="${money(volume)}">${compactMoney(volume)}</strong></div></div></div>
    <div class="coin-bottom"><span class="status-chip">${prettyStatus}${score == null ? ' · Unscored':''}${t.identity_check?.status==='ambiguous' ? ' · Lookalike warning':''}</span><button data-mint="${escapeHtml(t.mint)}">Watch history ↗</button></div>
    <details class="coin-detail" data-wallet-mint="${escapeHtml(t.mint)}" data-price="${Number(t.price_usd || 0)}" ${openDetails.has(t.mint) ? 'open':''}><summary>Coin details &amp; signals</summary>
    <p>Liquidity: ${money(t.liquidity_usd)} · ${escapeHtml(elapsed)} ${created ? 'since launch':'pair age'}</p>
    <p class="${change == null ? 'muted':Number(change)>=0 ? 'positive':'negative'}">5m change: ${change == null ? '—':(Number(change)>=0 ? '+':'')+Number(change).toFixed(1)+'%'}</p>
    <p>${escapeHtml(fast.provider==='deterministic-fallback' ? 'Rule-based scoring':fast.provider || (item.status==='rejected' ? 'Filtered before scoring':'Awaiting market data'))}</p>
    ${(fast.gemini_review || fast.openai_review) ? `<p>AI second opinion (${escapeHtml((fast.gemini_review || fast.openai_review).provider)}): ${escapeHtml((fast.gemini_review || fast.openai_review).raw?.review?.reason || 'Review recorded')} · score ${Number((fast.gemini_review || fast.openai_review).score)}/100</p>`:''}
    ${item.entry?.paper_exception?.allowed ? `<p>AI paper exception · ${escapeHtml(item.entry.paper_exception.model)} · waived: ${escapeHtml(item.entry.paper_exception.waived_reasons.join('; '))}</p>`:''}
    ${reasons.length ? `<p>${escapeHtml(reasons.join('; '))}</p>`:''}
    ${item.trending_score != null ? `<p>Trending score: ${item.trending_score} · Volume/MC: ${Number(item.volume_mc_ratio).toFixed(2)}×</p>`:''}
    ${t.buys_5m != null ? `<p>5m buys: ${Number(t.buys_5m)} · sells: ${Number(t.sells_5m)}</p>`:''}
    ${history ? `<p>First seen: ${stamp(item.first_seen)}<br>Last checked: ${stamp(item.last_seen)} · Checks: ${item.observations || 0}</p>`:''}
    ${t.timestamp ? `<p>Market data: ${stamp(t.timestamp)}</p>`:''}
    ${t.market_cap_is_fdv ? '<p>FDV shown because market cap is unavailable.</p>':''}
    <p>Setup: ${escapeHtml(t.setup_type || 'Awaiting evaluation')} · Wallet: ${escapeHtml(item.wallet?.status || t.wallet_context?.status || 'unknown')}</p>
    ${researchSummary(t.research)}<button data-research-mint="${escapeHtml(t.mint)}">Research &amp; label activity</button>
    <div class="tracked-wallets">${trackedWalletSection(t.mint,Number(t.price_usd || 0))}</div>
    ${t.identity_check?.status==='ambiguous' ? `<p class="negative">${escapeHtml(t.identity_check.message)} Branding warning only; this contract is evaluated separately.</p><p class="mint">Other matching contracts:<br>${t.identity_check.matching_contracts.map(escapeHtml).join('<br>')}</p>`:''}
    <p class="mint">${escapeHtml(t.mint)}</p></details>
  </article>`;
}
function cards(items, empty, history=false) {
  let filtered=items.filter(x=>{const t=x.token || {};return [t.name,t.symbol,t.mint].some(v=>String(v || '').toLowerCase().includes(searchQuery));});
  const field=tokenSort==='mc' ? 'market_cap_usd':{'5m':'volume_5m_usd','1h':'volume_1h_usd','24h':'volume_24h_usd'}[currentPage==='trending'?windowSize:'5m'];
  if(tokenSort!=='default' && !(currentPage==='watch' && selectedMint)) filtered=[...filtered].sort((a,b)=>Number(b.token?.[field] || 0)-Number(a.token?.[field] || 0));
  const count=`<p class="feed-count">${filtered.length} coins${searchQuery ? ' matching your search':''}</p>`;
  return count+(filtered.length ? '<div class="feed-list">'+filtered.map(x=>tokenCard(x,history)).join('')+'</div>':'<div class="empty">'+escapeHtml(searchQuery ? 'No loaded coins match your search.':empty)+'</div>');
}
function feedHeader(title, note, extra='') {
  return `<div class="feed-header"><div><h2>${title}</h2><p class="muted">${note}</p></div>${extra}</div>`;
}
function sortControl() {
  return `<label>Sort <select id="token-sort">${[['default','Feed order'],['volume','Volume'],['mc','Market cap']].map(([v,n])=>`<option value="${v}" ${tokenSort===v?'selected':''}>${n}</option>`).join('')}</select></label>`;
}
function walletRegistryView() {
  const data=walletRegistry, state=data.status || {};
  const summary=feedHeader('Tracked wallets',`Discovery: ${escapeHtml(state.discovery || 'starting')} · Learning: ${escapeHtml(state.learning || 'starting')}`);
  const note=`<p class="muted">Whale = ${compactMoney(data.whale_threshold_usd)} in one coin or ${compactMoney(data.whale_portfolio_usd)} across observed positions. Profitability requires ${Number(data.min_matched_sells || 10)} matched sells across 3+ tokens. Estimates cover observed SOL swaps, not lifetime PnL.</p>`;
  const items=(data.items || []).filter(w=>[w.address,w.label,...(w.tags || [])].some(v=>String(v).toLowerCase().includes(searchQuery)));
  return summary+note+(items.length ? items.slice(0,200).map(w=>{
    const p=w.profile || {};
    const label=w.disabled ? 'Disabled':w.manual ? 'Manual tracking':w.profitable ? 'Profitable':w.whale ? 'Whale':'Researching';
    return `<article class="card wallet-profile"><div class="coin-bottom"><strong>${escapeHtml(w.label)}</strong><span class="status-chip">${label}</span></div><p class="mint">${escapeHtml(w.address)}</p><p class="muted">${escapeHtml((w.tags || []).join(' · '))}</p><div class="metrics"><div><small>Observed PnL (SOL)</small><strong>${p.estimated_pnl_sol == null ? '—':Number(p.estimated_pnl_sol).toFixed(3)}</strong></div><div><small>Win rate</small><strong>${p.win_rate_pct == null ? '—':p.win_rate_pct+'%'}</strong></div><div><small>Largest current position</small><strong>${compactMoney(w.largest_position_usd)}</strong></div></div><p class="muted">${Number(p.matched_sells || 0)} matched sells · ${Number(p.distinct_tokens || 0)} tokens · Reputation ${Number(p.score || 0)}/100${p.data_status && p.data_status!=='ok' ? ' · '+escapeHtml(p.data_status):''}</p><p class="muted">Observed portfolio: ${compactMoney(w.observed_portfolio_usd)} (recently scanned coins only)<br>Last evaluated: ${stamp(w.evaluated_at)}</p>${w.disabled ? '<p class="muted">Add this address above to resume manual tracking.</p>':`<button data-remove-wallet="${escapeHtml(w.address)}">Stop tracking</button>`}</article>`;
  }).join(''):'<div class="empty">Wallets will appear as holders are discovered. You can add one above.</div>');
}
function selectedAccount() {
  return paperAccount==='aggressive' ? {label:'Aggressive momentum',balance:status.shadow?.balance_sol,positions:status.shadow?.positions || [],trades:status.shadow?.trades || [],metrics:status.shadow?.metrics || {}} : {label:'Original AI strategy',balance:status.balance_sol,positions:status.open_positions || [],trades,metrics:status.paper_metrics || {}};
}
function updateAccountSummary() {
  const a=selectedAccount();document.getElementById('paper-account').value=paperAccount;
  document.getElementById('balance-label').textContent=a.label+' · available';
  document.getElementById('balance').textContent=a.balance == null ? '— SOL':Number(a.balance).toFixed(4)+' SOL';
  document.getElementById('positions').textContent=a.positions.length;
  const control=status.account_controls?.[paperAccount],button=document.getElementById('account-run-toggle');
  document.getElementById('account-run-status').textContent=control ? a.label+' · '+(control.entries_enabled ? 'Entries enabled':'Stopped · exits active'):'Checking strategy…';
  button.disabled=accountControlBusy || !control;button.textContent=accountControlBusy ? 'Updating…':control?.entries_enabled ? 'Stop strategy':'Start strategy';
}
function tokenPrice(value) {
  if(value==null || !Number.isFinite(Number(value)) || Number(value)<=0)return '—';
  return '$'+Number(value).toLocaleString(undefined,{maximumSignificantDigits:8});
}
function exitFactors(d) {
  const labels={participation:'Participation',activity_quality:'Activity quality',narrative_support:'Narrative support',thesis_intact:'Entry thesis'};
  const items=Object.entries(d?.factors || {}).map(([key,v])=>`${escapeHtml(labels[key] || key)}: ${escapeHtml(v.assessment)}`).join(' · ');
  return items ? `<p class="muted">${items}<br>Separate AI judgments from supplied evidence; confidence is not a profit probability.</p>`:'';
}
function legacyExitTeam(decision) {
  if(!decision)return null;
  return {reviews:[{provider:decision.provider,status:decision.provider==='fallback' ? 'rule_fallback':'historically_recorded',action:decision.action,confidence:decision.confidence,reason:decision.reason,factors:decision.factors}],final:{contributors:decision.provider==='fallback' ? []:[decision.provider],weights:{[decision.provider]:1},reason:'Historical exit review. Other models were not recorded in this review.',policy_version:'legacy exit path'}};
}
function personalWalletStudyView() {
 const s=connectionData.personal_wallet_study;
 if(!s?.address)return '';
 const a=s.analysis || {};
 return `<div class="card learning-card"><h2>Your wallet history study</h2><p class="mint">${escapeHtml(s.address)}</p><p><b>${escapeHtml(s.status)}</b> · ${Number(s.transactions_seen || 0)} transactions checked · ${Number(s.pages || 0)} pages<br>Observed coverage: ${stamp(s.oldest_time)} to ${stamp(s.newest_time)}</p><div class="results-grid"><div><small>Completed positions</small><strong>${Number(a.completed_positions || 0)}</strong></div><div><small>Matched sales</small><strong>${Number(a.matched_sales || 0)}</strong></div><div><small>Completed SOL PnL</small><strong>${a.completed_positions ? Number(a.net_realized_sol_completed).toFixed(4)+' SOL':'—'}</strong></div></div><details class="secondary-info"><summary>Observed history and limitations</summary><p>${escapeHtml(s.scope)}</p>${(a.recent_completed || []).map(x=>`<p class="mint">${escapeHtml(x.mint)}<br>${Number(x.net_pnl_sol).toFixed(4)} SOL · ${Number(x.return_pct).toFixed(1)}% · held ${(Number(x.holding_seconds)/3600).toFixed(1)} hours · ${Number(x.buys)} buys / ${Number(x.sells)} sells<br>Final sale below highest own fill: ${Number(x.last_sale_below_highest_own_fill_pct).toFixed(1)}% (not market peak)</p>`).join('')}</details><h3>Historical chart comparisons</h3>${(s.price_history || []).map(h=>`<p class="mint">${escapeHtml(h.mint)}<br><b>${escapeHtml(h.status)}</b> · ${escapeHtml(h.case_kind)}${h.comparison?.sampled_high_usd == null ? '':'<br>Sampled high: '+tokenPrice(h.comparison.sampled_high_usd)+' · High / first sampled close: '+Number(h.comparison.high_vs_first_sampled_close_multiple).toFixed(2)+'× · Sampled close giveback: '+Number(h.comparison.close_giveback_from_high_pct).toFixed(1)+'%'}<br><span class="secondary-info">${escapeHtml(h.message || h.comparison?.scope || h.coverage || 'No verified candles yet')}</span></p>`).join('') || '<p>Waiting for recoverable token addresses and time windows.</p>'}<p>Read-only study. Not used as a copy-trading signal. Up to 10 historical pages/day; pauses preserve the cursor. Sampled chart comparisons preserve gaps; they are not executable profit or verified all-market peaks.</p></div>`;
}
function modelPerformanceView() {
  const d=status.learning?.[paperAccount==='aggressive' ? 'aggressive':'original'];
  return `<div class="card learning-card"><h2>Model reviews versus completed outcomes</h2>${(d?.provider_performance || []).map(p=>`<p><b>${escapeHtml(p.provider)}</b> · ${Number(p.completed_positions)} completed positions · ${Number(p.win_rate_pct).toFixed(1)}% won · Average return ${Number(p.average_return_pct).toFixed(1)}%</p>`).join('') || '<p>Waiting for completed trades with the new model participation records.</p>'}<p>These models may review the same trade. Results do not isolate a model’s contribution or prove predictive accuracy. Forward strategy tests remain required before changing policy.</p></div>`;
}
function teamDetails(team,audit=null) {
  const reviews=team?.reviews || [];
  const override=audit?.risk_override;
  const headline=override ? 'Risk rule overrode AI: '+audit.rule : team?.final?.reason || 'Historical model participation was not recorded; no model consensus is claimed.';
  return `<details class="secondary-info"><summary>AI decision details${override ? ' · RISK OVERRIDE':''}</summary><p><b>${escapeHtml(headline)}</b></p>${reviews.map(r=>`<p><b>${escapeHtml(r.provider)} · ${escapeHtml(r.status)}</b><br>${escapeHtml(r.role || '')}${r.actual_model ? '<br>Darwin routed model: '+escapeHtml(r.actual_model):''}<br>Recommendation: ${escapeHtml(r.action || (r.score == null ? 'unavailable':'setup score '+r.score+'/100'))} · Confidence: ${r.confidence == null ? 'not returned':(Number(r.confidence)*100).toFixed(1)+'% model certainty'}<br>${escapeHtml(r.reason || 'No valid review available.')}<br>${r.reason_source==='unavailable' ? 'Internal reasoning was not returned. ':''}${team?.final?.contributors?.includes(r.provider) ? 'Influenced final decision · weight '+(Number(team.final.weights?.[r.provider] || 0)*100).toFixed(0)+'%':r.status==='verified_response' ? 'Advisory evidence; no direct action vote':'Did not influence the decision'}${r.factors ? '<br>'+Object.entries(r.factors).map(([k,v])=>escapeHtml(k)+': '+escapeHtml(v.assessment)).join(' · '):''}${r.evidence ? '<br>Evidence snapshot: '+escapeHtml(JSON.stringify(r.evidence)):''}</p>`).join('')}<p>Confidence describes model certainty, not expected profit. Missing social evidence is unknown. ${escapeHtml(team?.final?.policy_version || 'Historical policy')}</p></details>`;
}
function tradeCards(rows,positions=false) {
  const a=selectedAccount(),m=a.metrics;
  const net=Number(m.net_pnl_sol || 0);
  const heading=`<div class="card"><h2>${positions ? 'Positions':'Trade History'} · ${escapeHtml(a.label)}</h2><div class="results-grid"><div><small>Realized net PnL</small><strong class="${net>=0 ? 'positive':'negative'}">${net.toFixed(4)} SOL</strong></div><div><small>Completed-position win rate</small><strong>${m.win_rate_pct == null ? '—':m.win_rate_pct+'%'}</strong></div><div><small>Open positions</small><strong>${a.positions.length}</strong></div></div><p class="secondary-info">${Number(m.closed_trades || 0)} closed fills · ${Number(m.position_metrics?.completed_positions || 0)} completed with costs. Balance is available simulated cash after open buys; realized PnL excludes open-position gains/losses.</p><details class="secondary-info"><summary>How AI exits work</summary><p>Configured models independently review evidence; JEV receives peer findings. Weighted recommendations choose hold, 10% increments, a legacy 25% sale, or full exit. Each sale applies to the remaining holding; repeated trims require fresh reviews. Decisions come from supplied evidence and past outcomes. JEV exit reviews are capped at ${Number(connectionData.models?.jev?.daily_exit_limit ?? 300)}/day across accounts; Gemini shares its existing quota. Rules take over when reviews are unavailable.${paperAccount==='aggressive' && !positions ? ' Showing the latest 200 positions with all their sales.':''}</p></details></div>`;
  return heading+(rows.length ? rows.map(t=>{
    const history=t.position_history;
    const pnl=history ? (history.fills.length ? Number(history.realized_net_pnl_sol):null):(t.pnl_sol == null ? null:Number(t.pnl_sol));
    const pct=history ? history.return_pct:t.pnl_pct;
    const timeline=history ? `<details class="trade-timeline" open><summary>Full trade history · ${history.fills.length} sales</summary><p><b>Buy:</b> ${Number(history.original_amount_sol).toFixed(4)} SOL · ${stamp(t.entry_time)} · ${compactMoney(t.entry_market_cap_usd)} ${t.entry_cap_is_fdv ? 'FDV':'market cap'}</p><p class="secondary-info">Buy reason: ${escapeHtml(t.entry_execution?.reason || t.entry_method || 'Historical execution rule not recorded')}${t.entry_execution?.combined_score == null ? '':' · Combined score '+Number(t.entry_execution.combined_score).toFixed(1)}</p>${teamDetails(t.entry_team)}${history.fills.map(f=>`<p><b>${escapeHtml(f.kind)} · ${Math.round(Number(f.fraction_of_remainder)*100)}% of remainder</b><br>${stamp(f.exit_time)} · ${compactMoney(f.exit_market_cap_usd)} ${f.exit_cap_is_fdv ? 'FDV':'market cap'}<br><strong class="${Number(f.pnl_sol)>=0 ? 'positive':'negative'}">${Number(f.pnl_sol).toFixed(4)} SOL · ${Number(f.pnl_pct).toFixed(1)}%</strong><br><span class="secondary-info">${escapeHtml(f.exit_reason || '—')}</span></p>${teamDetails(f.exit_decision?.team || legacyExitTeam(f.exit_decision),f.execution_audit || {risk_override:f.exit_reason==='hard stop',rule:f.exit_reason})}`).join('')}<p class="secondary-info">Remaining cost basis: ${Number(history.remaining_amount_sol).toFixed(4)} SOL. Results include estimated costs; open-price gains are excluded.</p></details>`:'';
    return `<article class="card trade-card"><div class="coin-title"><h3>$${escapeHtml(t.symbol || '?')}</h3><button class="copy-ca" data-copy-ca="${escapeHtml(t.mint)}">Copy CA</button></div><p class="trade-meta">Position #${Number(t.partial_exit?.parent_trade_id || t.id)}${t.partial_exit ? ' · Sale #'+Number(t.id):''} · ${escapeHtml(t.status)}${t.partial_exit ? ' · Partial sale':t.paper_scale_out_done ? ' · Remainder after partial sale':''} · ${Number(history?.original_amount_sol ?? t.amount_sol).toFixed(4)} SOL${history ? ' original size':''}<br>Bought ${stamp(t.entry_time)}${t.exit_time ? '<br>Closed '+stamp(t.exit_time):''}</p>${positions && t.status==='open' ? `<div class="results-grid cap-grid"><div><small>Remaining position</small><strong>${history?.remaining_pct == null ? '—':Number(history.remaining_pct).toFixed(1)+'%'}</strong><span class="secondary-info">of original holding</span></div><div><small>Tokens remaining</small><strong>${history?.remaining_token_quantity == null ? '—':Number(history.remaining_token_quantity).toLocaleString(undefined,{maximumFractionDigits:2})}</strong><span class="secondary-info">${Number(history?.remaining_amount_sol ?? t.amount_sol).toFixed(4)} SOL remaining cost basis</span></div></div>`:''}<div class="trade-pnl"><small>${history ? 'Whole-trade realized net PnL':pnl == null ? 'Realized PnL':'Realized net PnL'}</small><strong class="${pnl == null ? 'muted':pnl>=0 ? 'positive':'negative'}">${pnl == null ? 'Pending':pnl.toFixed(4)+' SOL'}</strong>${pnl == null ? '<span class="secondary-info">Open position</span>':`<span class="pnl-percent ${pnl>=0 ? 'positive':'negative'}">${pct == null ? 'Open remainder':Number(pct).toFixed(1)+'%'}</span>`}</div>${timeline}<div class="results-grid cap-grid"><div class="entry-cap"><small>Entry ${t.entry_cap_is_fdv ? 'FDV':'market cap'}:</small><strong title="${money(t.entry_market_cap_usd)}">${compactMoney(t.entry_market_cap_usd)}</strong></div>${t.status==='closed' ? `<div class="exit-cap"><small>Exit ${t.exit_cap_is_fdv ? 'FDV':'market cap'}:</small><strong title="${money(t.exit_market_cap_usd)}">${compactMoney(t.exit_market_cap_usd)}</strong></div>`:''}</div>${history ? `<div class="results-grid cap-grid average-caps"><div class="entry-cap"><small>AVG ENTRY ${history.average_entry_cap_is_fdv ? '(FDV)':''}</small><strong>${compactMoney(history.average_entry_market_cap_usd)}</strong></div><div class="exit-cap"><small>AVG EXIT ${history.average_sell_cap_is_fdv ? '(FDV)':''}</small><strong>${compactMoney(history.average_sell_market_cap_usd)}</strong></div><p class="secondary-info">Weighted by executed token amounts; missing or mixed cap/FDV data shows —. ${history.fills.length} sales.</p></div>`:''}${t.previous_entry ? `<p class="secondary-info">Separate entry after position #${Number(t.previous_entry.id)} · Earlier entry ${t.previous_entry.entry_cap_is_fdv ? 'FDV':'market cap'}: ${compactMoney(t.previous_entry.entry_market_cap_usd)} · ${stamp(t.previous_entry.entry_time)}</p>`:''}${t.exit_reason ? '<p class="exit-label"><b>Exit:</b> '+escapeHtml(t.exit_reason.split(' — ')[0])+'</p>':''}<details class="secondary-info"><summary>AI review &amp; trade details</summary><p>Each new position ID has a fixed entry snapshot. Partial sells retain the original entry. — means unavailable.</p><p>Entry price: ${tokenPrice(t.entry_price_usd)} per token${t.status==='closed' ? '<br>Exit price: '+tokenPrice(t.exit_price_usd)+' per token':''}<br>Simulated fill prices include estimated slippage.</p>${t.exit_reason ? '<p>Exit explanation: '+escapeHtml(t.exit_reason)+'</p>':''}${t.exit_reason==='hard stop' ? '<p>Hard stop is a trigger; gaps, polling delays and costs can produce a larger loss.</p>':''}${t.exit_decision ? `<p>Exit review: ${escapeHtml(t.exit_decision.provider)} · ${escapeHtml(t.exit_decision.action)} · ${stamp(t.exit_decision.checked_at)}<br>${escapeHtml(t.exit_decision.reason)}</p>${exitFactors(t.exit_decision)}${t.exit_decision.failures?.length ? '<p>'+escapeHtml(t.exit_decision.failures.join('; '))+'</p>':''}`:''}${t.status==='open' ? '<p>AI reviews every 2 minutes, subject to quotas. The −20% loss stop, security exit and maximum hold remain. Unavailable AI uses fallback rules. Outcomes inform future reviews; model weights are not retrained.</p>':''}${t.exit_review ? `<p>After-exit review · ${Number(t.exit_review.samples)} samples · ${t.exit_review.complete?'window ended':'tracking up to 1h'}<br>${t.exit_review.samples ? 'Sampled peak: '+Number(t.exit_review.peak_after_exit_pct).toFixed(1)+'% · Low: '+Number(t.exit_review.low_after_exit_pct).toFixed(1)+'%':'Awaiting fresh data'}<br>Spot-price changes after sale; not hypothetical profit.</p>`:''}</details><p class="mint">${escapeHtml(t.mint)}</p></article>`;
  }).join(''):'<div class="empty">'+(positions ? 'No open positions in this account.':'No trades in this account yet.')+'</div>');
}
document.getElementById('paper-account').addEventListener('change',event=>{
 paperAccount=event.target.value==='original' ? 'original':'aggressive';
 try {localStorage.setItem('nexus-paper-account',paperAccount);} catch {}
 updateAccountSummary();render();refreshAccountSummary();
});
function render() {
  document.getElementById('wallet-manager').hidden=currentPage!=='wallets';
  document.getElementById('research-manager').hidden=currentPage!=='research';
  document.querySelectorAll('nav button').forEach(b => { const active=b.dataset.v===currentPage; b.classList.toggle('active',active); b.setAttribute('aria-pressed',String(active)); });
  let html = refreshError ? `<p role="status">${escapeHtml(refreshError)}</p>`:'';
  updateAccountSummary();
  const trial=paperAccount==='original' ? status.risk_trial:null;
  if(paperAccount==='aggressive' && ['positions','history','agents','scan'].includes(currentPage))html+=`<div class="card"><h2>Aggressive momentum paper account</h2><p>${status.account_controls?.aggressive?.entries_enabled===false ? 'Stopped · open exits continue':status.shadow?.active ? 'Running':'Entry window ended'} · ${status.shadow?.continuous ? 'Continuous paper trading': 'Entries end '+stamp(status.shadow?.ends_at)} · Open positions continue AI exit reviews with protective limits and rule fallbacks.</p></div>`;
  if(trial?.active) html+=`<div class="card"><h2>Riskier paper trial</h2><p>Ends ${stamp(trial.ends_at)} · automatic return to normal rules</p><p>Liquidity ≥ ${money(trial.min_liquidity_usd)} · score ≥ ${Number(trial.min_combined_score)} · wallet ≥ ${Number(trial.min_wallet_score)}<br>Buy cap ${Number(trial.max_trade_sol)} SOL · ${Number(trial.max_open_positions)} positions · daily loss pause ${trial.daily_loss_limit_enabled === false ? 'disabled for paper testing':Number(trial.max_daily_loss_sol)+' SOL'}</p></div>`;
  if(paperAccount==='aggressive' && ['positions','history','agents','scan'].includes(currentPage)) {
    const pauses=status.shadow?.entry_pause_reasons || [];
    html+=`<div class="card"><h2>Entry status</h2><p>${pauses.length ? 'Paused: '+pauses.map(escapeHtml).join(' · '):'Entries enabled; waiting for eligible candidates.'}</p><p>Realized today: ${Number(status.shadow?.daily_realized_sol || 0).toFixed(4)} SOL · Daily loss pause: ${status.shadow?.daily_loss_limit_enabled === false ? 'disabled for paper testing':'0.15 SOL'} · Daily counter resets ${stamp(status.shadow?.daily_limit_resets_at)}</p><p class="muted">The 24-hour severe-loss cooldown blocks only that contract, not the whole account. Open positions continue protective exits.</p></div>`;
  }
  const scan=paperAccount==='aggressive' ? (status.shadow?.checked_at ? {...status.scan,...status.shadow,finished_at:status.shadow.checked_at}:null):status.scan;
  if(scan && ['positions','history','agents','scan'].includes(currentPage)) html+=`<div class="card"><h2>${escapeHtml(selectedAccount().label)} scanner</h2><p>Last completed: ${stamp(scan.finished_at)} · ${Number(scan.evaluated)} coins evaluated · ${Number(scan.evaluation_failures)} errors · ${Number(scan.paper_buys)} buys this scan</p><p>${Object.entries(scan.blockers || {}).map(([reason,count])=>`${Number(count)}: ${escapeHtml(reason)}`).join('<br>') || 'No rejection reasons in this scan.'}</p></div>`;
  if(['agents','watch'].includes(currentPage)) {const review=status.missed_learning || {};html+=`<div class="card"><h2>Missed opportunity learning</h2><p>${escapeHtml(review.scope || 'Collecting rejection decisions and future prices.')}</p>${(review.by_reason || []).map(x=>`<p>${escapeHtml(x.reason)} · ${Number(x.distinct_coins)} coins · ${Number(x.surged_50_pct)}% rose 50% · ${Number(x.fell_30_pct)}% fell 30% · median latest ${Number(x.median_latest_change_pct)}%</p>`).join('') || '<p>Waiting for at least five minutes of follow-up prices.</p>'}${(review.surges || []).map(x=>`<p class="mint">${escapeHtml(x.mint)} · observed peak +${Number(x.peak_gain_pct)}% · latest ${Number(x.latest_change_pct)}%</p>`).join('')}</div>`;}
  if (status.error) html+=`<p role="status">Scanner error: ${escapeHtml(status.error)}</p>`;
  if (currentPage==='scan') html += feedHeader('Opportunities','Latest scan batch · Scores reflect bot signals.',sortControl())+cards(opportunities,'Waiting for a scan.');
  else if (currentPage==='new') html += feedHeader('New Pairs',`<span class="feed-dot"></span>${escapeHtml(launches.feed.status || 'connecting')} · Pump.fun launches from the past hour`,sortControl())+cards(launches.items,'Waiting for live launches. Market data appears after indexing.');
  else if (currentPage==='trending') html += feedHeader('Trending','Volume + market cap · Recently scanned coins',`<label>Window <select id="trend-window">${['5m','1h','24h'].map(x=>`<option value="${x}" ${x===windowSize?'selected':''}>${x}</option>`).join('')}</select></label>`)+cards(trending.items,'Waiting for scanned coins with volume and market cap.')+'<p class="muted feed-count">Ranking: 70% volume + 30% market cap. Covers coins checked in the last 10 minutes.</p>';
  else if (currentPage==='watch') {
    html += feedHeader('Watch History','Every discovery, check and filter decision.');
    if (selectedMint) html += `<div class="card"><button id="back-watch">All watched coins</button><h3 class="mint">${escapeHtml(selectedMint)}</h3><p class="muted">Latest checks first</p></div>`+cards(details,'No scored checks yet; this launch is awaiting indexed market data.');
    else html += cards(watched,'No coins checked yet.',true);
  } else if (currentPage==='positions') html += tradeCards(selectedAccount().positions,true);
  else if (currentPage==='agents') html += connectionsView();
  else if (currentPage==='routes') html += '<div class="card"><h2>Execution Routes</h2><p>Pump Direct → PumpSwap → Jupiter fallback</p><p class="muted">Live trading is not enabled.</p></div>';
  else if (currentPage==='wallets') html += walletRegistryView();
  else if (currentPage==='research') html += researchView();
  else if (currentPage==='history') html += tradeCards(selectedAccount().trades);
  document.getElementById('content').innerHTML = html;
}
document.getElementById('account-run-toggle').addEventListener('click',async()=>{
 if(accountControlBusy || !status.account_controls?.[paperAccount])return;
 const account=paperAccount,enabled=!status.account_controls[account].entries_enabled;
 accountControlBusy=true;updateAccountSummary();
 try {
  const response=await fetch('/api/paper-accounts/'+account+'/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({entries_enabled:enabled})});
  if(!response.ok)throw new Error('HTTP '+response.status);
  const data=await response.json();++accountRequest;status.account_controls=data.account_controls;refreshError='';render();
 }catch(error){refreshError='Strategy control failed; state was not confirmed. Refresh and try again.';render();}
 finally{accountControlBusy=false;updateAccountSummary();}
});
document.querySelectorAll('nav button').forEach(button => button.addEventListener('click',()=>{currentPage=button.dataset.v;selectedMint=null;tokenSort='default';document.querySelector('.nav-more')?.removeAttribute('open');render();}));
document.getElementById('content').addEventListener('click',async event=>{
  const copyButton=event.target.closest('button[data-copy-ca]');
  if(copyButton) {
    const mint=copyButton.dataset.copyCa;
    try {
      await navigator.clipboard.writeText(mint);
      copyButton.textContent='Copied!';
      copyButton.setAttribute('aria-label','Contract address copied');
      setTimeout(()=>{if(copyButton.isConnected){copyButton.textContent='Copy CA';copyButton.setAttribute('aria-label','Copy contract address');}},2000);
    } catch(e) {
      window.prompt('Copy this contract address:',mint);
    }
    return;
  }
  if(event.target.id==='test-connections') {event.target.disabled=true;event.target.textContent='Testing…';try {connectionData=await walletWrite('/api/connections/check','POST');render();}catch(e) {refreshError=e.message;render();}return;}
  const researchButton=event.target.closest('button[data-research-mint]');
  if(researchButton) {researchMint=researchButton.dataset.researchMint;researchData=null;document.getElementById('research-mint').value=researchMint;currentPage='research';render();try {researchData=await getData('/api/research/'+encodeURIComponent(researchMint));render();}catch(e) {refreshError=e.message;render();}return;}
  const remove=event.target.closest('button[data-remove-wallet]');
  if(remove) {remove.disabled=true;try {await walletWrite('/api/wallets/'+encodeURIComponent(remove.dataset.removeWallet),'DELETE');walletDetails.clear();await refreshDashboard();} catch(e) {refreshError=e.message;render();} return;}
  const button=event.target.closest('button[data-mint]');
  if (button) { selectedMint=button.dataset.mint; currentPage='watch'; details=[]; render(); try { const mint=selectedMint; const result=await getData('/api/watch-history?mint='+encodeURIComponent(mint)); if(selectedMint===mint) {details=result;render();} } catch(e) { refreshError=e.message;render(); } }
  if (event.target.id==='back-watch') {selectedMint=null;render();}
});
document.getElementById('content').addEventListener('change',async event=>{
  if(event.target.id==='token-sort') {tokenSort=event.target.value;render();}
  if(event.target.id==='trend-window') { windowSize=event.target.value; try { trending=await getData('/api/trending?window='+windowSize);render(); } catch(e) {refreshError=e.message;render();} }
});
document.getElementById('content').addEventListener('toggle',async event=>{
  const detail=event.target;
  if(detail.tagName!=='DETAILS' || !detail.isConnected || !detail.dataset.walletMint) return;
  const mint=detail.dataset.walletMint;
  if(!detail.open) {openDetails.delete(mint);return;}
  openDetails.add(mint);
  const cached=walletDetails.get(mint);
  if(walletLoading.has(mint) || (cached && Date.now()-(cached.loadedAt || 0)<60000)) return;
  walletLoading.add(mint);walletDetails.set(mint,{status:'loading'});
  detail.querySelector('.tracked-wallets').innerHTML=trackedWalletSection(mint,Number(detail.dataset.price));
  try {walletDetails.set(mint,{...await getData('/api/tracked-wallets/'+encodeURIComponent(mint)),loadedAt:Date.now()});}
  catch {walletDetails.set(mint,{status:'error',loadedAt:Date.now()-60000});}
  finally {walletLoading.delete(mint);}
  if(detail.isConnected) detail.querySelector('.tracked-wallets').innerHTML=trackedWalletSection(mint,Number(detail.dataset.price));
},true);
document.getElementById('coin-search').addEventListener('input',event=>{searchQuery=event.target.value.trim().toLowerCase();render();});
document.getElementById('content').addEventListener('error',event=>{if(event.target.tagName==='IMG') event.target.parentElement.textContent='?';},true);
refreshDashboard();
setInterval(refreshDashboard,5000);

async function walletWrite(path,method,body) {
  const response=await fetch(path,{method,headers:{'Content-Type':'application/json'},body:body ? JSON.stringify(body):undefined});
  const data=await response.json();
  if(!response.ok) throw new Error(typeof data.detail==='string' ? data.detail:'Could not save wallet. Check the address.');
  return data;
}
document.getElementById('wallet-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.target.querySelector('button'),message=document.getElementById('wallet-form-message');
  button.disabled=true;message.textContent='Saving…';
  try {await walletWrite('/api/wallets','POST',{address:document.getElementById('wallet-address').value.trim(),label:document.getElementById('wallet-label').value.trim()});walletDetails.clear();message.textContent='Wallet added. Positions will appear in coin details.';event.target.reset();walletRegistry=await getData('/api/wallets');render();}
  catch(e) {message.textContent=e.message;}
  finally {button.disabled=false;}
});

function sourceSummary(data) {
  const w=data?.web_research || {},links=data?.project_links || [];
  const sources=(w.sources || []).map(x=>`<li><a href="${escapeHtml(imageUrl(x.url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(x.title || 'Source')}</a><br>${escapeHtml(x.snippet)}<br><small>Exact CA linked · endorsement unverified</small></li>`).join('');
  return `<h4>Web sources</h4><p>${escapeHtml(w.status || 'not_researched')} · Checked ${stamp(w.checked_at)}</p><ul>${sources || '<li>No indexed contract-linked sources yet. Narrative remains unknown.</li>'}</ul>${links.length ? '<p>Project-supplied links (unverified): '+links.map(x=>`<a href="${escapeHtml(imageUrl(x.url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(x.label)}</a>`).join(' · ')+'</p>':''}`;
}
function bundleSummary(data) {
  const b=data?.bundle?.launch_report || {};
  const pct=x=>x == null ? 'Unknown':Number(x).toFixed(1)+'%';
  const mintUrl=imageUrl(b.report);
  return `<p>Is It Bundled?: ${escapeHtml(b.status || 'pending')} · Launch bundled: ${pct(b.bundledPct)}${b.estimate === true ? ' (estimate)':''}<br>Creator bundle: ${pct(b.creatorBundlePct)} · Other bundles: ${pct(b.otherBundlesPct)}<br>Insiders holding: ${pct(b.insidersHoldPct)} · Flagged wallets holding: ${pct(b.flaggedHoldPct)}<br>Current report risk: ${escapeHtml(b.risk || 'unknown')} · Fetched ${stamp(b.checked_at)}${b.reportAt ? ' · Holdings report '+stamp(b.reportAt):''}${mintUrl ? `<br><a href="${escapeHtml(mintUrl)}" target="_blank" rel="noopener noreferrer">View Is It Bundled? report ↗</a>`:''}<br><span class="muted">Provider signals; not proof of fraud. Unscanned, missing or stale data is unknown. Launch bundles differ from current holdings.</span></p>`;
}
function researchSummary(data) {
  if(!data) return '<h4>Security &amp; narrative</h4><p class="muted">Research is pending.</p>';
  const security=data.security || {}, learning=data.learning || {}, features=data.features || {};
  const cohorts=features.market_cap_group ? `<p>Market cohort: ${escapeHtml(features.market_cap_group)} (${escapeHtml(features.cap_basis)}) · 5m volume: ${escapeHtml(features.volume_5m_group)}<br>Holder concentration: ${escapeHtml(features.holder_concentration)}<br>${Object.entries(data.outcomes_by_horizon || {}).map(([h,o])=>`${escapeHtml(h)}: ${Number(o.distinct_coins || 0)} coins · observed +50% peak ${o.gain_50pct_frequency == null ? '—':Number(o.gain_50pct_frequency)+'%'} · ended −50% ${o.loss_50pct_frequency == null ? '—':Number(o.loss_50pct_frequency)+'%'}`).join('<br>')}</p>`:'';
  const timing=learning.timing || {};
  const timingSummary=features.market_cap_group ? `<p class="muted">Influencer attention: ${escapeHtml(features.influencer_attention || 'unknown')}<br>1h cohort median observed time to +50%: ${timing.median_seconds_to_gain_50 == null ? '—':Number(timing.median_seconds_to_gain_50)+'s'} (${Number(timing.gain_50_observations || 0)} coins); to −30%: ${timing.median_seconds_to_loss_30 == null ? '—':Number(timing.median_seconds_to_loss_30)+'s'} (${Number(timing.loss_30_observations || 0)} coins). Sampled timing, not an exit guarantee.</p>`:'';
  return `<h4>Security &amp; narrative</h4>${data.narrative_rotation?.themes?.length ? `<p>Narrative themes: ${data.narrative_rotation.themes.map(x=>escapeHtml(x.name)).join(', ')}${data.narrative_rotation.small_cap_rotation_candidate ? ' · Small-cap rotation candidate':''}<br>Associated rising leaders: ${data.narrative_rotation.themes.flatMap(x=>x.leaders || []).map(x=>'$'+escapeHtml(x.symbol || '?')+' '+compactMoney(x.market_cap_usd)).join(', ') || 'None identified'}<br><span class="muted">Provider theme tags; not verified engagement, endorsement or a top-ten token rank.</span></p>`:''}${activitySummary(data.activity)}${bundleSummary(data)}${cohorts}${timingSummary}<p>RugCheck: ${escapeHtml(security.status || 'pending')}${security.danger ? ' · Danger detected':''} · Narrative: ${escapeHtml(features.narrative || 'unknown')}<br>Acquisition: ${escapeHtml(features.acquisition || 'unknown')}${features.large_received_transfer ? ' · Received transfer ≥5% of supply':''}<br>Bundle indicators: ${escapeHtml(data.bundle?.status || 'unknown')}</p><p class="muted">${escapeHtml(security.message || '')}<br>Learning: ${Number(learning.distinct_coins || 0)} distinct coins · 1h median change ${learning.median_return_pct == null ? '—':Number(learning.median_return_pct).toFixed(1)+'%'} · Sharp dip frequency ${learning.sharp_dip_pct == null ? '—':learning.sharp_dip_pct+'%'}</p>`;
}
function researchView() {
  const data=researchData;
  if(!researchMint) return '<div class="card"><p>Choose “Research &amp; label activity” in coin details, or paste a coin contract into the form above. Learning starts when fresh market data is observed.</p></div>';
  if(!data) return '<div class="card"><p>Loading coin research…</p></div>';
  const claims=(data.claims || []).map(c=>`<li>${escapeHtml(c.subject || c.wallet)} · Identity: ${escapeHtml(c.identity)} · Endorsement: ${escapeHtml(c.endorsement)}<br>${escapeHtml(c.wallet)}<br>${imageUrl(c.source_url) ? `<a href="${escapeHtml(imageUrl(c.source_url))}" target="_blank" rel="noopener noreferrer">Source reviewed by user</a>`:''}<br>${escapeHtml(c.note)} · ${stamp(c.recorded_at)}</li>`).join('');
  const events=(data.events || []).map(e=>`<li>${escapeHtml(e.kind)} · ${escapeHtml(e.wallet)} · ${escapeHtml(e.quantity)} tokens${e.received_supply_pct != null ? ' · ≈'+Number(e.received_supply_pct).toFixed(2)+'% supply':''}${e.amount_approximate ? ' (approximate amount)':''}<br><a href="https://solscan.io/tx/${encodeURIComponent(e.signature)}" target="_blank" rel="noopener noreferrer">Transaction</a> · ${stamp(e.timestamp)}</li>`).join('');
  const risks=(data.security?.risks || []).map(r=>`<li>${escapeHtml(r.level)}: ${escapeHtml(r.name)} — ${escapeHtml(r.description)}</li>`).join('');
  const outcomes=(data.outcomes || []).filter(o=>o.horizon).map(o=>`<li>${escapeHtml(o.horizon)} · Return ${Number(o.return_pct).toFixed(1)}% · Observed peak ${Number(o.peak_pct).toFixed(1)}% · Worst observed drawdown ${Number(o.drawdown_pct).toFixed(1)}%<br>Case started ${stamp(o.started_at)}</li>`).join('');
  return `<div class="card"><h2>Coin research</h2><p class="mint">${escapeHtml(researchMint)}</p>${researchSummary(data)}${sourceSummary(data)}<button id="search-sources">Search web sources</button><p class="muted">${escapeHtml(data.message)}<br>${escapeHtml(data.bundle?.scope)}<br>Learned risk adjustment begins after 10 distinct coins. Missing outcomes stay missing; price snapshots can miss intraperiod moves.</p><h3>Reviewed narrative sources</h3><ul>${claims || '<li>No identity or endorsement evidence recorded.</li>'}</ul><h3>Observed transfers and buys</h3><ul>${events || '<li>No parsed wallet events observed yet. This does not mean no transfers occurred.</li>'}</ul><h3>RugCheck flags</h3><ul>${risks || '<li>No flags returned, or report unavailable. Check status above.</li>'}</ul><h3>Forward outcomes</h3><ul>${outcomes || '<li>Waiting for fresh 5m / 1h / 24h price observations.</li>'}</ul></div>`;
}
document.getElementById('research-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.target.querySelector('button'),message=document.getElementById('research-message');button.disabled=true;message.textContent='Saving…';
  const mint=document.getElementById('research-mint').value.trim();
  try {await walletWrite('/api/research/'+encodeURIComponent(mint)+'/claims','POST',{wallet:document.getElementById('research-wallet').value.trim(),subject:document.getElementById('research-subject').value.trim(),identity:document.getElementById('research-identity').value,endorsement:document.getElementById('research-endorsement').value,source_url:document.getElementById('research-source').value.trim(),note:document.getElementById('research-note').value.trim()});researchMint=mint;researchData=await getData('/api/research/'+encodeURIComponent(mint));message.textContent='Saved as user-reviewed evidence. Learning uses future observations.';render();}catch(e) {message.textContent=e.message;}finally {button.disabled=false;}
});

function shadowView() {
 const s=status.shadow || {},m=s.metrics || {};
 return `<div class="card"><h2>Aggressive paper benchmark</h2><p>${status.account_controls?.aggressive?.entries_enabled===false ? 'Stopped · open exits continue':s.active ? 'Running':'Entry window ended'} · Started ${stamp(s.started_at)} · ${s.continuous ? 'Continuous paper trading':'Entries end '+stamp(s.ends_at)}</p><p>Separate balance: ${Number(s.balance_sol || 0).toFixed(4)} SOL · ${Number(m.closed_trades || 0)} closed · ${Number((s.positions || []).length)} open<br>Realized net PnL: ${Number(m.net_pnl_sol || 0).toFixed(4)} SOL · Completed-position win rate: ${m.win_rate_pct == null ? '—':m.win_rate_pct+'%'}</p><p>Entry: liquidity ≥$5,000, 5m volume ≥$2,000, 5m change ≥5%, more buys than sells, current RugCheck without danger. Wallet and AI scores are not required. Bundle warnings remain recorded. ${Number(s.min_buy_sol || .05)}–${Number(s.max_buy_sol || .1)} SOL per new buy (momentum strength), 3 open positions, ${s.daily_loss_limit_enabled === false ? 'Daily loss pause disabled for paper testing.':'0.15 SOL daily realized loss limit (UTC).'}</p><p>${escapeHtml(s.scope || '')} Open positions continue normal exits after the entry window ends. Realized PnL excludes open-position gains/losses.</p><p>Last scan: ${stamp(s.checked_at)} · ${escapeHtml(JSON.stringify(s.blockers || {}))}</p><ul>${(s.trades || []).slice(0,20).map(t=>`<li>$${escapeHtml(t.symbol)} · ${escapeHtml(t.status)} · ${stamp(t.entry_time)} · ${t.pnl_sol == null ? 'PnL pending':Number(t.pnl_sol).toFixed(4)+' SOL'}<br><span class="mint">${escapeHtml(t.mint)}</span></li>`).join('') || '<li>No benchmark trades yet.</li>'}</ul></div>`;
}
function entryLearningView(d) {
  const e=d.entry_learning || {};
  const marks=Object.entries(e.outcomes || {}).map(([action,m])=>`<tr><td>${escapeHtml(action)}</td><td>${Number(m.samples || 0)}</td><td>${Number(m.positive_pct || 0).toFixed(1)}%</td><td>${Number(m.mean_net_return_pct || 0).toFixed(1)}%</td></tr>`).join('');
  const recent=(e.recent || []).map(r=>`<li><span class="mint">${escapeHtml(r.mint)}</span> · ${stamp(r.at)}<br><strong>${escapeHtml(r.decision?.action)}</strong> · ${escapeHtml(r.decision?.reason)}${r.outcome ? '<br>One-hour costed mark: '+Number(r.outcome.net_return_pct).toFixed(1)+'%':''}<br><span class="muted">${(r.decision?.matches || []).map(m=>escapeHtml(m.group)+' · '+Number(m.distinct_coins)+' coins · '+(m.loss_rate_pct == null ? 'no loss-rate sample':Number(m.loss_rate_pct).toFixed(1)+'% losses')+' · '+Number(m.severe_losses)+' severe losses').join('<br>')}</span></li>`).join('');
  return `<h3>Entry learning · ${escapeHtml(e.version || 'starting')}</h3><p>Completed positions available as evidence: ${Number(e.completed_evidence_positions || 0)}. Paper entries now wait or avoid matching loss patterns; both accounts use the same completed-trade evidence while their strategies and balances stay separate.</p><p>A contract with a completed loss of 50% or worse gets a 24h re-entry cooldown. Similar setups are avoided only with at least 8 distinct coins, 60% losses, 2 severe losses and negative average net return. Market cap, liquidity/volume and available launch-bundle groups are evaluated from saved entry evidence. These conditions update from completed trades; unknown data does not prove a pattern. Original-strategy AI reviews also receive this evidence.</p><p>Forward entry checks: ${Number(e.recorded_screens || 0)} retained screens · ${Number(e.pending || 0)} pending · ${Number(e.missing || 0)} missing one-hour marks</p><div style="overflow-x:auto"><table><thead><tr><th>Entry decision</th><th>Observed marks</th><th>Positive marks</th><th>Mean costed 1h mark</th></tr></thead><tbody>${marks || '<tr><td colspan="4">Waiting for eligible candidates and fresh one-hour observations.</td></tr>'}</tbody></table></div><p class="muted">${escapeHtml(e.scope || 'Paper-only outcome adaptation; no automatic model-weight training.')} No improvement is assumed from this table.</p><details><summary>Recent entry decisions and evidence</summary><ul>${recent || '<li>No eligible entry screens yet.</li>'}</ul></details>`;
}
function evolutionView(e) {
  const g=e?.current || {}, reports=g.training_reports || {};
  const rows=Object.entries(g.policies || {}).map(([key,r])=>`<tr><td>${escapeHtml(r.family)} · ${escapeHtml(key)}</td><td>+${Number(r.take_profit)}% / ${Number(r.partial_fraction)*100}% sale</td><td>${Number(r.trail)}% drop, armed +${Number(r.trail_arm)}%</td><td>${Number(r.max_hold_seconds)/60}m</td><td>${Number(reports[key]?.candidate?.completed_positions || 0)}</td><td>${Number(reports[key]?.candidate?.net_pnl_sol || 0).toFixed(4)} SOL</td></tr>`).join('');
  const v=g.validation_report?.candidate || {};
  return `<h3>Strategy evolution · generation ${Number(g.generation || 1)}</h3><p>Phase: <strong>${escapeHtml(g.phase || 'starting')}</strong> · Eight exit candidates in four families. No candidate replaces the trading policy automatically.</p><p>Training requires 50 completed distinct coins shared by all candidates, across seven entry dates. Then the training winner is frozen and tested on 25 new contracts across three dates. A rejected generation breeds new bounded variations and newcomers using training results only.</p><p>Frozen candidate: ${escapeHtml(g.champion || 'None yet')} · Fresh validation: ${Number(v.completed_positions || 0)}/25 coins · ${Number(g.validation_report?.entry_days || 0)}/3 entry dates</p><div style="overflow-x:auto"><table><thead><tr><th>Family / version</th><th>Profit / size sold</th><th>Trailing rule</th><th>Maximum hold</th><th>Training coins</th><th>Training net</th></tr></thead><tbody>${rows}</tbody></table></div><details><summary>Completed generations</summary><ul>${(e?.finished || []).map(x=>`<li>Generation ${Number(x.generation)}: ${escapeHtml(x.result)} · ${Number(x.validation_report?.candidate?.net_pnl_sol || 0).toFixed(4)} SOL candidate net</li>`).join('') || '<li>No generation has completed fresh validation yet.</li>'}</ul></details><p class="muted">${escapeHtml(e?.scope || '')} Genes remain frozen for each trial. These tests optimize exits on selected entries; entry strategy and portfolio capacity are not optimized.</p>`;
}
function learningView() {
  const d=status.learning?.[paperAccount] || {},m=d.metrics || {},t=d.trials || {};
  const value=x=>x == null ? '—':Number(x).toFixed(4)+' SOL';
  const percent=x=>x == null ? '—':Number(x).toFixed(1)+'%';
  const rows=(t.policies || []).map(p=>`<tr><td>${escapeHtml(p.policy)}</td><td>${Number(p.paired_positions || 0)}</td><td>${percent(p.candidate?.win_rate_pct)}</td><td>${value(p.candidate?.net_pnl_sol)}</td><td>${value(p.same_entries_actual?.net_pnl_sol)}</td><td>${Number(p.pending || 0)} (${Number(p.awaiting_price || 0)} awaiting price)</td><td>${escapeHtml(p.status)}</td></tr>`).join('');
  return `<div class="card learning-card"><h2>Learning &amp; strategy tests · ${paperAccount==='aggressive' ? 'Aggressive momentum':'Original AI strategy'}</h2><div class="results-grid"><div><small>Completed-position net PnL</small><strong class="${Number(m.net_pnl_sol || 0)>=0 ? 'positive':'negative'}">${value(m.net_pnl_sol)}</strong></div><div><small>Win rate</small><strong>${percent(m.win_rate_pct)}</strong></div><div><small>Realized drawdown</small><strong>${value(m.realized_drawdown_sol)}</strong></div></div><p>${Number(m.completed_positions || 0)} completed positions with costs · ${Number(m.open_positions || 0)} open · ${Number(m.legacy_completed_positions || 0)} legacy excluded<br>Win rate: ${percent(m.win_rate_pct)} · Average win: ${value(m.average_win_sol)} · Average loss: ${value(m.average_loss_sol)}<br>Average net per position: ${value(m.average_net_sol)} · Profit factor: ${m.profit_factor == null ? '—':Number(m.profit_factor).toFixed(2)}<br>Completed-position realized drawdown: ${value(m.realized_drawdown_sol)}</p><p class="muted">All partial sells and the final remainder count as one position. An open remainder does not count as a win. This drawdown excludes open-position swings.</p><p>Saved records: ${Number(d.recorded_decisions?.entry || 0)} entries · ${Number(d.recorded_decisions?.exit_review || 0)} exit reviews · ${Number(d.recorded_decisions?.fill || 0)} sells<br><a href="/api/learning/decisions?account=${paperAccount}" target="_blank" rel="noopener noreferrer">Inspect recent decision evidence and outcomes</a></p>${entryLearningView(d)}${evolutionView(d.evolution)}<h3>Forward exit comparisons</h3><p>Rule reference: full profit exit at +50%, 20% trailing drop. Partial runner: sell half at +50%, keep the rest with a 30% trailing drop armed after +50%. Both retain a −20% loss trigger, security exit and 24h maximum hold. Triggers cannot guarantee execution prices.</p><div style="overflow-x:auto"><table><thead><tr><th>Candidate</th><th>Paired positions</th><th>Win rate</th><th>Candidate net</th><th>Actual net, same entries</th><th>Pending</th><th>Status</th></tr></thead><tbody>${rows || '<tr><td colspan="7">Waiting for new paper entries.</td></tr>'}</tbody></table></div><p class="muted">${escapeHtml(t.scope || 'Comparisons begin with new entries; no extra model calls or market requests.')}<br>${escapeHtml(t.promotion || '')}<br>These are test hypotheses. Models are not automatically retrained.</p></div>`;
}
function connectionsView() {
  const d=connectionData, models=d.models || {}, storage=d.storage || {}, metrics=status.paper_metrics || {};
  const modelRows=Object.entries(models).map(([name,m])=>`<li>${escapeHtml(name)}: ${m.configured ? 'Configured':m.key_present && !m.endpoint_present ? 'Key present; endpoint missing':'Missing key or endpoint'} · ${escapeHtml(m.status)}${m.actual_model ? ' · Routed model: '+escapeHtml(m.actual_model):''}${m.checked_at ? ' · '+stamp(m.checked_at):''}${name==='jev' ? ' · '+Number(m.exit_requests_today || 0)+'/'+Number(m.daily_exit_limit || 300)+' exit reviews today (UTC)':''}${['openai','gemini'].includes(name) ? ' · '+escapeHtml(m.model)+' · '+Number(m.requests_today || 0)+'/'+Number(m.daily_request_limit || 0)+' requests today (UTC)':''}</li>`).join('');
  return `${learningView()}${personalWalletStudyView()}${modelPerformanceView()}${activityComparison()}<div class="card learning-card"><h2>Connections &amp; paper results</h2><p>Narrative meta feed: ${escapeHtml(status.narrative_trends?.status || 'unknown')} · ${(status.narrative_trends?.themes || []).map(x=>escapeHtml(x.name)).join(', ') || 'No current themes'}<br>First three provider trending metas; updated every five minutes.</p><p>Configured Gemini, Laya, Darwin and OpenAI independently review supplied evidence; JEV receives their findings for action selection. Valid entry scores and exit actions are combined with recorded weights. Failed, unconfigured or quota-limited providers are explicitly excluded; advisory-only scores inform JEV but do not cast exit votes. Aggressive buys now receive team reviews alongside momentum rules. Protective stops bypass AI immediately. Entry secondary reviews are reused for 15 minutes per coin; exit reviews refresh every two minutes; tests count toward daily limits. Gemini pauses on quota errors and does not automatically switch to paid OpenAI.</p><p class="muted">OpenAI uses the bot’s supplied evidence, not your ChatGPT conversation or tools. API billing is separate from ChatGPT. The request limit is not a dollar budget; zero disables requests for that provider. Keep Google project billing disabled to use Gemini’s free tier; Google’s quota may be lower than the app limit. Free-tier inputs may be used to improve Google products.</p><ul>${modelRows}<li>Tavily: ${escapeHtml(d.web_research?.status || 'standby')} · ${d.web_research?.configured ? 'Configured':'Missing key'} · ${Number(d.web_research?.requests_today || 0)}/25 searches today · ${Number(d.web_research?.requests_month || 0)}/750 this UTC month</li><li>Wallet RPC: ${escapeHtml(d.rpc?.status || 'unknown')}</li><li>Helius history: ${escapeHtml(d.helius?.status || 'unknown')}</li><li>X social: ${escapeHtml(d.x?.x || 'unknown')}</li><li>RugCheck: ${escapeHtml(d.rugcheck?.rugcheck || 'unknown')}</li><li>Is It Bundled?: ${escapeHtml(d.isitbundled?.status || 'starting')} · Free API · No key required</li></ul><button id="test-connections">Test AI connections</button><p class="muted">Tests send one small request to each configured model endpoint and may use provider credits. Keys are never shown. A valid score tests the adapter response, not trading quality.</p><p>Web research uses basic searches only, exact contract addresses, up to four excerpts, cached for six hours (empty results retry after 30 minutes). It does not provide a complete or live X feed. Limits include failed requests and survive restarts.</p><h3>Learning storage</h3><p>${escapeHtml(storage.message)}<br>Database: <span class="mint">${escapeHtml(storage.db_path)}</span></p><h3>Paper performance</h3><p>${Number(metrics.closed_trades || 0)} closed fills · ${Number(metrics.cost_model_trades || 0)} with cost model · ${Number(metrics.legacy_trades || 0)} legacy<br>Net PnL: ${Number(metrics.net_pnl_sol || 0).toFixed(4)} SOL · Today's realized: ${Number(metrics.daily_realized_sol || 0).toFixed(4)} SOL (UTC)<br>Completed-position win rate: ${metrics.win_rate_pct == null ? '—':metrics.win_rate_pct+'%'}</p><p class="muted">Simulated fees and slippage; actual fills, liquidity impact and network costs can differ. Telegram/Discord feeds and automatic endorsement verification are not connected. Live execution remains disabled.</p></div>${shadowView()}`;
}

document.getElementById('content').addEventListener('click',async event=>{
 if(event.target.id!=='search-sources' || !researchMint)return;
 const button=event.target;button.disabled=true;button.textContent='Searching…';
 try {const r=await walletWrite('/api/research/'+encodeURIComponent(researchMint)+'/search','POST');researchData=await getData('/api/research/'+encodeURIComponent(researchMint));render();if(r.request_status)alert(r.request_status);}
 catch(e){button.textContent=e.message;button.disabled=false;}
});


function activitySummary(a) {
 if(!a)return '';
 const u=a.user_review || {};
 return `<h4>Volume &amp; engagement</h4>${(a.reviewed_examples || []).map(e=>`<details><summary>Reviewed collapse example: SUPMKT</summary><p>${escapeHtml(e.chart_observation)} ${escapeHtml(e.user_claim)}</p><p>${escapeHtml(e.lesson)}</p><p class="muted">${escapeHtml(e.limitations)}</p></details>`).join('')}<p>Volume: ${escapeHtml(a.volume_class)} · Engagement: ${escapeHtml(a.engagement_class)}</p><p>User report (unverified): ${escapeHtml(u.note || 'No review yet')}${u.recorded_at ? ' · '+stamp(u.recorded_at):''}</p>${imageUrl(u.source_url) ? `<a href="${escapeHtml(imageUrl(u.source_url))}" target="_blank" rel="noopener noreferrer">User source</a>`:''}<ul>${(a.indicators || []).map(i=>`<li>${escapeHtml(i.kind)} · ${escapeHtml(i.source)}<br>${escapeHtml(i.message)}</li>`).join('') || '<li>No activity indicators in available data; this does not verify genuine demand.</li>'}</ul><p class="muted">${escapeHtml(a.scope)} Pump comments and X reply bot analysis are not connected.</p>`;
}
function activityComparison() {
 const d=status.activity_learning || {},rows=d.groups || [];
 const paper=(d.paper_results || []).map(g=>`<li>${escapeHtml(g.account)} · ${escapeHtml(g.volume)} / ${escapeHtml(g.engagement)}<br>${Number(g.closed_trades)} closed · ${Number(g.open_trades)} open · Net ${Number(g.net_pnl_sol).toFixed(4)} SOL · Win rate ${g.win_rate_pct == null ? '—':Number(g.win_rate_pct)+'%'}</li>`).join('');
 return `<div class="card"><h2>Activity outcome comparison · ${escapeHtml(d.horizon || '1h')}</h2>${rows.length ? '<ul>'+rows.map(g=>`<li>Volume: ${escapeHtml(g.volume)} · Engagement: ${escapeHtml(g.engagement)}<br>${Number(g.distinct_coins)} coins · Median return ${Number(g.median_return_pct)}% · +50% peak ${Number(g.gain_50_pct)}% · Sharp dips ${Number(g.sharp_dip_pct)}%</li>`).join('')+'</ul>':'<p>Collecting future price outcomes for labeled and unreviewed coins.</p>'}<p class="muted">${escapeHtml(d.scope || 'Observational cohorts, not trained model weights or proof of causation.')}</p><h3>Paper results by activity at entry</h3><ul>${paper || '<li>No paper trades yet.</li>'}</ul><p class="muted">${escapeHtml(d.paper_scope || '')}</p></div>`;
}
document.getElementById('activity-form').addEventListener('submit',async event=>{
 event.preventDefault();const mint=document.getElementById('research-mint').value.trim(),button=event.target.querySelector('button'),message=document.getElementById('activity-message');
 button.disabled=true;message.textContent='Saving…';
 try {await walletWrite('/api/research/'+encodeURIComponent(mint)+'/activity','POST',{volume:document.getElementById('activity-volume').value,engagement:document.getElementById('activity-engagement').value,source_url:document.getElementById('activity-source').value.trim(),note:document.getElementById('activity-note').value.trim()});researchMint=mint;researchData=await getData('/api/research/'+encodeURIComponent(mint));message.textContent='Saved as an unverified user report. Future observations use this label.';render();}catch(e){message.textContent=e.message;}finally{button.disabled=false;}
});
