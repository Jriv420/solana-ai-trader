const openDetails = new Set(), walletDetails = new Map(), walletLoading = new Set();
let currentPage = 'new';
let researchMint=null, researchData=null;
let connectionData={};
let searchQuery = '';
let tokenSort = 'default';
let walletRegistry = {items:[],status:{}};
let status = {}, opportunities = [], trades = [], launches = {items:[],feed:{}}, trending = {items:[]}, watched = [];
let windowSize = '5m', selectedMint = null, details = [], loading = false, refreshError = '';
async function getData(path) {
  const response = await fetch(path, {cache:'no-store'});
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
async function refreshDashboard() {
  if (loading) return;
  loading = true;
  try {
    const results = await Promise.all([getData('/api/status'), getData('/api/opportunities'),
      getData('/api/trades'),getData('/api/new-pairs'), getData('/api/trending?window='+windowSize), getData('/api/watch-history'),getData('/api/wallets'),getData('/api/connections')]);
    [status,opportunities,trades,launches,trending,watched,walletRegistry,connectionData] = results;
    refreshError = '';
    document.getElementById('balance').textContent = Number(status.balance_sol).toFixed(3)+' SOL';
    document.getElementById('mode').textContent = status.paper_mode ? 'PAPER':'LIVE';
    document.getElementById('positions').textContent = (status.open_positions || []).length;
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
    ${reasons.length ? `<p>${escapeHtml(reasons.join('; '))}</p>`:''}
    ${item.trending_score != null ? `<p>Trending score: ${item.trending_score} · Volume/MC: ${Number(item.volume_mc_ratio).toFixed(2)}×</p>`:''}
    ${t.buys_5m != null ? `<p>5m buys: ${Number(t.buys_5m)} · sells: ${Number(t.sells_5m)}</p>`:''}
    ${history ? `<p>First seen: ${stamp(item.first_seen)}<br>Last checked: ${stamp(item.last_seen)} · Checks: ${item.observations || 0}</p>`:''}
    ${t.timestamp ? `<p>Market data: ${stamp(t.timestamp)}</p>`:''}
    ${t.market_cap_is_fdv ? '<p>FDV shown because market cap is unavailable.</p>':''}
    <p>Setup: ${escapeHtml(t.setup_type || 'Awaiting evaluation')} · Wallet: ${escapeHtml(item.wallet?.status || t.wallet_context?.status || 'unknown')}</p>
    ${researchSummary(t.research)}<button data-research-mint="${escapeHtml(t.mint)}">Research &amp; label narrative</button>
    <div class="tracked-wallets">${trackedWalletSection(t.mint,Number(t.price_usd || 0))}</div>
    ${t.identity_check?.status==='ambiguous' ? `<p class="negative">${escapeHtml(t.identity_check.message)} Paper entry blocked for ambiguous branding.</p><p class="mint">Other matching contracts:<br>${t.identity_check.matching_contracts.map(escapeHtml).join('<br>')}</p>`:''}
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
function render() {
  document.getElementById('wallet-manager').hidden=currentPage!=='wallets';
  document.getElementById('research-manager').hidden=currentPage!=='research';
  document.querySelectorAll('nav button').forEach(b => { const active=b.dataset.v===currentPage; b.classList.toggle('active',active); b.setAttribute('aria-pressed',String(active)); });
  let html = refreshError ? `<p role="status">${escapeHtml(refreshError)}</p>`:'';
  if (status.error) html+=`<p role="status">Scanner error: ${escapeHtml(status.error)}</p>`;
  if (currentPage==='scan') html += feedHeader('Opportunities','Latest scan batch · Scores reflect bot signals.',sortControl())+cards(opportunities,'Waiting for a scan.');
  else if (currentPage==='new') html += feedHeader('New Pairs',`<span class="feed-dot"></span>${escapeHtml(launches.feed.status || 'connecting')} · Pump.fun launches from the past hour`,sortControl())+cards(launches.items,'Waiting for live launches. Market data appears after indexing.');
  else if (currentPage==='trending') html += feedHeader('Trending','Volume + market cap · Recently scanned coins',`<label>Window <select id="trend-window">${['5m','1h','24h'].map(x=>`<option value="${x}" ${x===windowSize?'selected':''}>${x}</option>`).join('')}</select></label>`)+cards(trending.items,'Waiting for scanned coins with volume and market cap.')+'<p class="muted feed-count">Ranking: 70% volume + 30% market cap. Covers coins checked in the last 10 minutes.</p>';
  else if (currentPage==='watch') {
    html += feedHeader('Watch History','Every discovery, check and filter decision.');
    if (selectedMint) html += `<div class="card"><button id="back-watch">All watched coins</button><h3 class="mint">${escapeHtml(selectedMint)}</h3><p class="muted">Latest checks first</p></div>`+cards(details,'No scored checks yet; this launch is awaiting indexed market data.');
    else html += cards(watched,'No coins checked yet.',true);
  } else if (currentPage==='positions') html += `<div class="card"><h2>Open Positions</h2><pre>${escapeHtml(JSON.stringify(status.open_positions || [],null,2))}</pre></div>`;
  else if (currentPage==='agents') html += connectionsView();
  else if (currentPage==='routes') html += '<div class="card"><h2>Execution Routes</h2><p>Pump Direct → PumpSwap → Jupiter fallback</p><p class="muted">Live trading is not enabled.</p></div>';
  else if (currentPage==='wallets') html += walletRegistryView();
  else if (currentPage==='research') html += researchView();
  else if (currentPage==='history') html += `<div class="card"><h2>Trade History</h2><pre>${escapeHtml(JSON.stringify(trades,null,2))}</pre></div>`;
  document.getElementById('content').innerHTML = html;
}
document.querySelectorAll('nav button').forEach(button => button.addEventListener('click',()=>{currentPage=button.dataset.v;selectedMint=null;tokenSort='default';render();}));
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

function researchSummary(data) {
  if(!data) return '<h4>Security &amp; narrative</h4><p class="muted">Research is pending.</p>';
  const security=data.security || {}, learning=data.learning || {}, features=data.features || {};
  const cohorts=features.market_cap_group ? `<p>Market cohort: ${escapeHtml(features.market_cap_group)} (${escapeHtml(features.cap_basis)}) · 5m volume: ${escapeHtml(features.volume_5m_group)}<br>Holder concentration: ${escapeHtml(features.holder_concentration)}<br>${Object.entries(data.outcomes_by_horizon || {}).map(([h,o])=>`${escapeHtml(h)}: ${Number(o.distinct_coins || 0)} coins · observed +50% peak ${o.gain_50pct_frequency == null ? '—':Number(o.gain_50pct_frequency)+'%'} · ended −50% ${o.loss_50pct_frequency == null ? '—':Number(o.loss_50pct_frequency)+'%'}`).join('<br>')}</p>`:'';
  const timing=learning.timing || {};
  const timingSummary=features.market_cap_group ? `<p class="muted">Influencer attention: ${escapeHtml(features.influencer_attention || 'unknown')}<br>1h cohort median observed time to +50%: ${timing.median_seconds_to_gain_50 == null ? '—':Number(timing.median_seconds_to_gain_50)+'s'} (${Number(timing.gain_50_observations || 0)} coins); to −30%: ${timing.median_seconds_to_loss_30 == null ? '—':Number(timing.median_seconds_to_loss_30)+'s'} (${Number(timing.loss_30_observations || 0)} coins). Sampled timing, not an exit guarantee.</p>`:'';
  return `<h4>Security &amp; narrative</h4>${cohorts}${timingSummary}<p>RugCheck: ${escapeHtml(security.status || 'pending')}${security.danger ? ' · Danger detected':''} · Narrative: ${escapeHtml(features.narrative || 'unknown')}<br>Acquisition: ${escapeHtml(features.acquisition || 'unknown')}${features.large_received_transfer ? ' · Received transfer ≥5% of supply':''}<br>Bundle indicators: ${escapeHtml(data.bundle?.status || 'unknown')}</p><p class="muted">${escapeHtml(security.message || '')}<br>Learning: ${Number(learning.distinct_coins || 0)} distinct coins · 1h median change ${learning.median_return_pct == null ? '—':Number(learning.median_return_pct).toFixed(1)+'%'} · Sharp dip frequency ${learning.sharp_dip_pct == null ? '—':learning.sharp_dip_pct+'%'}</p>`;
}
function researchView() {
  const data=researchData;
  if(!researchMint) return '<div class="card"><p>Choose “Research &amp; label narrative” in coin details, or paste a coin contract into the form above. Learning starts when fresh market data is observed.</p></div>';
  if(!data) return '<div class="card"><p>Loading coin research…</p></div>';
  const claims=(data.claims || []).map(c=>`<li>${escapeHtml(c.subject || c.wallet)} · Identity: ${escapeHtml(c.identity)} · Endorsement: ${escapeHtml(c.endorsement)}<br>${escapeHtml(c.wallet)}<br>${imageUrl(c.source_url) ? `<a href="${escapeHtml(imageUrl(c.source_url))}" target="_blank" rel="noopener noreferrer">Source reviewed by user</a>`:''}<br>${escapeHtml(c.note)} · ${stamp(c.recorded_at)}</li>`).join('');
  const events=(data.events || []).map(e=>`<li>${escapeHtml(e.kind)} · ${escapeHtml(e.wallet)} · ${escapeHtml(e.quantity)} tokens${e.received_supply_pct != null ? ' · ≈'+Number(e.received_supply_pct).toFixed(2)+'% supply':''}${e.amount_approximate ? ' (approximate amount)':''}<br><a href="https://solscan.io/tx/${encodeURIComponent(e.signature)}" target="_blank" rel="noopener noreferrer">Transaction</a> · ${stamp(e.timestamp)}</li>`).join('');
  const risks=(data.security?.risks || []).map(r=>`<li>${escapeHtml(r.level)}: ${escapeHtml(r.name)} — ${escapeHtml(r.description)}</li>`).join('');
  const outcomes=(data.outcomes || []).filter(o=>o.horizon).map(o=>`<li>${escapeHtml(o.horizon)} · Return ${Number(o.return_pct).toFixed(1)}% · Observed peak ${Number(o.peak_pct).toFixed(1)}% · Worst observed drawdown ${Number(o.drawdown_pct).toFixed(1)}%<br>Case started ${stamp(o.started_at)}</li>`).join('');
  return `<div class="card"><h2>Coin research</h2><p class="mint">${escapeHtml(researchMint)}</p>${researchSummary(data)}<p class="muted">${escapeHtml(data.message)}<br>${escapeHtml(data.bundle?.scope)}<br>Learned risk adjustment begins after 10 distinct coins. Missing outcomes stay missing; price snapshots can miss intraperiod moves.</p><h3>Reviewed narrative sources</h3><ul>${claims || '<li>No identity or endorsement evidence recorded.</li>'}</ul><h3>Observed transfers and buys</h3><ul>${events || '<li>No parsed wallet events observed yet. This does not mean no transfers occurred.</li>'}</ul><h3>RugCheck flags</h3><ul>${risks || '<li>No flags returned, or report unavailable. Check status above.</li>'}</ul><h3>Forward outcomes</h3><ul>${outcomes || '<li>Waiting for fresh 5m / 1h / 24h price observations.</li>'}</ul></div>`;
}
document.getElementById('research-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.target.querySelector('button'),message=document.getElementById('research-message');button.disabled=true;message.textContent='Saving…';
  const mint=document.getElementById('research-mint').value.trim();
  try {await walletWrite('/api/research/'+encodeURIComponent(mint)+'/claims','POST',{wallet:document.getElementById('research-wallet').value.trim(),subject:document.getElementById('research-subject').value.trim(),identity:document.getElementById('research-identity').value,endorsement:document.getElementById('research-endorsement').value,source_url:document.getElementById('research-source').value.trim(),note:document.getElementById('research-note').value.trim()});researchMint=mint;researchData=await getData('/api/research/'+encodeURIComponent(mint));message.textContent='Saved as user-reviewed evidence. Learning uses future observations.';render();}catch(e) {message.textContent=e.message;}finally {button.disabled=false;}
});

function connectionsView() {
  const d=connectionData, models=d.models || {}, storage=d.storage || {}, metrics=status.paper_metrics || {};
  const modelRows=Object.entries(models).map(([name,m])=>`<li>${escapeHtml(name)}: ${m.configured ? 'Configured':'Missing key or endpoint'} · ${escapeHtml(m.status)}${m.checked_at ? ' · '+stamp(m.checked_at):''}${['openai','gemini'].includes(name) ? ' · '+escapeHtml(m.model)+' · '+Number(m.requests_today || 0)+'/'+Number(m.daily_request_limit || 0)+' requests today (UTC)':''}</li>`).join('');
  return `<div class="card"><h2>Connections &amp; paper results</h2><p>Jev → Laya → Darwin for eligible setups; deterministic risk gates remain independent. Paid model calls wait for qualified wallet evidence. Darwin is reserved for stronger fallback setups. Gemini reviews stronger setups alongside Jev when configured. Otherwise optional OpenAI can review. A second opinion can lower the score but cannot raise it. Reviews are reused for 15 minutes per coin; tests count toward daily limits. Gemini pauses on quota errors and does not automatically switch to paid OpenAI.</p><p class="muted">OpenAI uses the bot’s supplied evidence, not your ChatGPT conversation or tools. API billing is separate from ChatGPT. The request limit is not a dollar budget; zero disables requests for that provider. Keep Google project billing disabled to use Gemini’s free tier; Google’s quota may be lower than the app limit. Free-tier inputs may be used to improve Google products.</p><ul>${modelRows}<li>Wallet RPC: ${escapeHtml(d.rpc?.status || 'unknown')}</li><li>Helius history: ${escapeHtml(d.helius?.status || 'unknown')}</li><li>X social: ${escapeHtml(d.x?.x || 'unknown')}</li><li>RugCheck: ${escapeHtml(d.rugcheck?.rugcheck || 'unknown')}</li></ul><button id="test-connections">Test AI connections</button><p class="muted">Tests send one small request to each configured model endpoint and may use provider credits. Keys are never shown. A valid score tests the adapter response, not trading quality.</p><h3>Learning storage</h3><p>${escapeHtml(storage.message)}<br>Database: <span class="mint">${escapeHtml(storage.db_path)}</span></p><h3>Paper performance</h3><p>${Number(metrics.closed_trades || 0)} closed trades · ${Number(metrics.cost_model_trades || 0)} with cost model · ${Number(metrics.legacy_trades || 0)} legacy<br>Net PnL: ${Number(metrics.net_pnl_sol || 0).toFixed(4)} SOL · Today's realized: ${Number(metrics.daily_realized_sol || 0).toFixed(4)} SOL (UTC)<br>Win rate: ${metrics.win_rate_pct == null ? '—':metrics.win_rate_pct+'%'}</p><p class="muted">Simulated fees and slippage; actual fills, liquidity impact and network costs can differ. Telegram/Discord feeds and automatic endorsement verification are not connected. Live execution remains disabled.</p></div>`;
}
