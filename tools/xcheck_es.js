const fs=require('fs');
const src=fs.readFileSync(process.argv[2],'utf8');
// 只把換算那幾支函式挖出來跑，不載整個 app.js（它要 DOM）
const a=src.indexOf('const QMON');
const b=src.indexOf('const dataUrl =');
if(a<0||b<0||b<a) { console.error('MARKER_FAIL'); process.exit(2); }
const DERIVED={};
eval(src.slice(a,b));
const payload=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const out=deriveES(payload);
if(!out){ console.error('DERIVE_NULL'); process.exit(3); }
const v=out.views.ALL;
console.log(JSON.stringify({
  ratio: out.meta.es_ratio, basis: out.meta.es_basis, quarter: out.meta.es_quarter,
  s_ref: out.meta.s_ref,
  K: v.strikes.map(s=>s.K), x: v.curve.x, F: out.expiries.map(e=>e.F),
}));
