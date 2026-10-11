const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();
function node(id){if(!elements.has(id))elements.set(id,{listeners:{},addEventListener(type,fn){this.listeners[type]=fn;},textContent:'',innerHTML:'',value:'',hidden:false});return elements.get(id);}
const context=vm.createContext({document:{getElementById:node,querySelectorAll:()=>[]},localStorage:{getItem:()=>null,setItem:()=>{}},URL,fetch:()=>new Promise(()=>{}),setInterval:()=>0,setTimeout:()=>0,assert});
vm.runInContext(fs.readFileSync('dashboard/app.js','utf8'),context);
vm.runInContext(`
status={balance_sol:10,open_positions:[],paper_metrics:{closed_trades:0},shadow:{active:true,balance_sol:9.95,positions:[{mint:'agg',symbol:'AGG',status:'open',amount_sol:.025,entry_price_usd:.00000123456,entry_market_cap_usd:277000,entry_cap_is_fdv:false}],trades:[{mint:'agg',symbol:'AGG',status:'open',amount_sol:.025,entry_price_usd:.00000123456,entry_market_cap_usd:277000,entry_cap_is_fdv:false}],metrics:{closed_trades:2,net_pnl_sol:.01}}};
trades=[{mint:'original',symbol:'ORIGINAL',status:'closed',amount_sol:.025,entry_price_usd:.002,exit_price_usd:.003,entry_market_cap_usd:1400000,exit_market_cap_usd:2100000,entry_cap_is_fdv:true,exit_cap_is_fdv:true,pnl_sol:0,pnl_pct:0}];
currentPage='history';render();
assert.equal(document.getElementById('balance').textContent,'9.9500 SOL');
assert.equal(document.getElementById('positions').textContent,1);
assert(document.getElementById('content').innerHTML.includes('$AGG'));
assert(document.getElementById('content').innerHTML.includes('Entry price: $0.00000123456'));
assert(document.getElementById('content').innerHTML.includes('Entry market cap:'));
assert(document.getElementById('content').innerHTML.includes('$277K'));
assert(!document.getElementById('content').innerHTML.includes('$ORIGINAL'));
document.getElementById('paper-account').listeners.change({target:{value:'original'}});
assert.equal(document.getElementById('balance').textContent,'10.0000 SOL');
assert.equal(document.getElementById('positions').textContent,0);
assert(document.getElementById('content').innerHTML.includes('$ORIGINAL'));
assert(document.getElementById('content').innerHTML.includes('Entry price: $0.002'));
assert(document.getElementById('content').innerHTML.includes('Exit price: $0.003'));
assert(document.getElementById('content').innerHTML.includes('Entry FDV:'));
assert(document.getElementById('content').innerHTML.includes('$1.4M'));
assert(document.getElementById('content').innerHTML.includes('Exit FDV:'));
assert(!document.getElementById('content').innerHTML.includes('$AGG'));
document.getElementById('paper-account').listeners.change({target:{value:'aggressive'}});
currentPage='positions';render();assert(document.getElementById('content').innerHTML.includes('$AGG'));
status.shadow={positions:[],trades:[],metrics:{}};render();
assert.equal(document.getElementById('balance').textContent,'— SOL');
assert(document.getElementById('content').innerHTML.includes('No open positions'));
`,context);
console.log('Paper account UI switching checks passed');

(async()=>{
 let resolve;
 context.fetch=path=>path==='/api/status' ? new Promise(r=>resolve=r):Promise.reject(new Error('feed unavailable'));
 const running=vm.runInContext('loading=false;refreshDashboard()',context);
 resolve({ok:true,json:async()=>({balance_sol:.95,open_positions:[],shadow:{balance_sol:.72,positions:[],trades:[],metrics:{}}})});
 await running;await new Promise(r=>setImmediate(r));
 assert.equal(node('balance').textContent,'0.7200 SOL');
 node('paper-account').listeners.change({target:{value:'original'}});
 assert.equal(node('balance').textContent,'0.9500 SOL');
 resolve({ok:true,json:async()=>({balance_sol:.96,open_positions:[],shadow:{balance_sol:.71,positions:[],trades:[],metrics:{}}})});
 await new Promise(r=>setImmediate(r));
 assert.equal(node('balance').textContent,'0.9600 SOL');
 console.log('Fresh account balances update even when a feed fails');
})().catch(e=>{console.error(e);process.exitCode=1;});
vm.runInContext(`
status.learning={original:{metrics:{completed_positions:7,win_rate_pct:42.9},recorded_decisions:{entry:3}},aggressive:{metrics:{completed_positions:2,win_rate_pct:50},recorded_decisions:{entry:8}}};
paperAccount='aggressive';assert(learningView().includes('2 completed positions'));assert(learningView().includes('50.0%'));assert(learningView().includes('account=aggressive'));
paperAccount='original';assert(learningView().includes('7 completed positions'));assert(learningView().includes('42.9%'));assert(learningView().includes('account=original'));paperAccount='aggressive';
`,context);
vm.runInContext(`
status.learning.aggressive.entry_learning={version:'entry-loss-v1',completed_evidence_positions:9,recorded_screens:3,recent:[{mint:'test',at:1,decision:{action:'avoid',reason:'<script>bad</script>',matches:[]},outcome:{net_return_pct:10}}]};
paperAccount='aggressive';assert(learningView().includes('Entry learning'));assert(learningView().includes('avoid'));assert(learningView().includes('&lt;script&gt;bad'));assert(!learningView().includes('<script>bad'));
paperAccount='original';assert(!learningView().includes('&lt;script&gt;bad'));paperAccount='aggressive';
`,context);

vm.runInContext(`
const grouped={id:61,symbol:'UNCC',mint:'uncc',status:'closed',amount_sol:.0558,entry_market_cap_usd:128000,exit_market_cap_usd:124100,pnl_sol:-.0024,pnl_pct:-4.4,position_history:{original_amount_sol:.0992,remaining_amount_sol:0,realized_net_pnl_sol:.0968,return_pct:97.6,average_sell_market_cap_usd:260000,complete:true,fills:[{id:63,kind:'partial sale',fraction_of_remainder:.25,exit_market_cap_usd:500000,pnl_sol:.066,pnl_pct:266,exit_time:1,exit_reason:'trim'},{id:61,kind:'final exit',fraction_of_remainder:1,exit_market_cap_usd:124100,pnl_sol:-.0024,pnl_pct:-4.4,exit_time:2,exit_reason:'exit'}]}};
const html=tradeCards([grouped]);
assert(html.includes('Whole-trade realized net PnL'));
assert(html.includes('0.0968 SOL'));
assert(html.includes('Full trade history · 2 sales'));
assert(html.includes('Average sell market cap:'));
assert(html.includes('$260K'));
assert(html.includes('-0.0024 SOL'));
assert(html.includes('25% of remainder'));
`,context);
