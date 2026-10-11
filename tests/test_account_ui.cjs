const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();
function node(id){if(!elements.has(id))elements.set(id,{listeners:{},addEventListener(type,fn){this.listeners[type]=fn;},textContent:'',innerHTML:'',value:'',hidden:false});return elements.get(id);}
const context=vm.createContext({document:{getElementById:node,querySelectorAll:()=>[]},localStorage:{getItem:()=>null,setItem:()=>{}},URL,fetch:()=>new Promise(()=>{}),setInterval:()=>0,setTimeout:()=>0,assert});
vm.runInContext(fs.readFileSync('dashboard/app.js','utf8'),context);
vm.runInContext(`
status={balance_sol:10,open_positions:[],paper_metrics:{closed_trades:0},shadow:{active:true,balance_sol:9.95,positions:[{mint:'agg',symbol:'AGG',status:'open',amount_sol:.025}],trades:[{mint:'agg',symbol:'AGG',status:'open',amount_sol:.025}],metrics:{closed_trades:2,net_pnl_sol:.01}}};
trades=[{mint:'original',symbol:'ORIGINAL',status:'closed',amount_sol:.025,pnl_sol:0,pnl_pct:0}];
currentPage='history';render();
assert.equal(document.getElementById('balance').textContent,'9.9500 SOL');
assert.equal(document.getElementById('positions').textContent,1);
assert(document.getElementById('content').innerHTML.includes('$AGG'));
assert(!document.getElementById('content').innerHTML.includes('$ORIGINAL'));
document.getElementById('paper-account').listeners.change({target:{value:'original'}});
assert.equal(document.getElementById('balance').textContent,'10.0000 SOL');
assert.equal(document.getElementById('positions').textContent,0);
assert(document.getElementById('content').innerHTML.includes('$ORIGINAL'));
assert(!document.getElementById('content').innerHTML.includes('$AGG'));
document.getElementById('paper-account').listeners.change({target:{value:'aggressive'}});
currentPage='positions';render();assert(document.getElementById('content').innerHTML.includes('$AGG'));
status.shadow={positions:[],trades:[],metrics:{}};render();
assert.equal(document.getElementById('balance').textContent,'— SOL');
assert(document.getElementById('content').innerHTML.includes('No open positions'));
`,context);
console.log('Paper account UI switching checks passed');
