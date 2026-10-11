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
