const assert = require('node:assert/strict');
const {analytics, upload} = require('../../app/static/ui-utils.js');
const now = new Date(2026, 10, 14, 12), yesterday = new Date(2026,10,13,12).getTime()/1000;
const posts = [
 {provider:'youtube',status:'submitted',created_at:yesterday},
 {provider:'facebook',status:'failed',created_at:yesterday},
 {provider:'youtube',status:'draft',created_at:yesterday},
 {provider:'youtube',status:'submitted',created_at:1}
];
const result=analytics(posts,7,'youtube',now);
assert.equal(result.rows.length,2); assert.equal(result.submitted.reduce((a,b)=>a+b),1);
assert.equal(result.other.reduce((a,b)=>a+b),0);
assert.equal(analytics(posts,7,'facebook',now).other.reduce((a,b)=>a+b),1);
assert.equal(analytics([],7,'all',now).rows.length,0);
// Fake transport verifies byte progress, validation phase, CSRF and failure handling.
let xhr;
global.XMLHttpRequest=class {
 constructor(){xhr=this;this.upload={};this.headers={};}
 open(method,url){this.method=method;this.url=url;}
 setRequestHeader(k,v){this.headers[k]=v;}
 send(body){this.body=body;}
};
(async()=>{
 const progress=[];let unauthorized=false;
 const pending=upload(new Blob(['video']), 'csrf-test', p=>progress.push(p),()=>{unauthorized=true;});
 assert.equal(xhr.url,'/api/media');assert.equal(xhr.headers['X-CSRF-Token'],'csrf-test');
 xhr.upload.onprogress({lengthComputable:true,loaded:50,total:100});xhr.upload.onload();
 assert.deepEqual(progress,[50,null]);
 xhr.status=200;xhr.responseText='{"id":"media"}';xhr.onload();assert.equal((await pending).id,'media');
 const denied=upload(new Blob(),'',()=>{},()=>{unauthorized=true;});
 xhr.status=401;xhr.responseText='{"detail":"Login required"}';xhr.onload();await assert.rejects(denied,/Login required/);assert.equal(unauthorized,true);
 const invalid=upload(new Blob(),'',()=>{},()=>{});xhr.status=502;xhr.responseText='<html>proxy error</html>';xhr.onload();await assert.rejects(invalid,/502/);
 const network=upload(new Blob(),'',()=>{},()=>{});xhr.onerror();await assert.rejects(network,/Mất kết nối/);
 console.log('UI behavior passed: filters, local dates, empty data, upload progress, CSRF, auth, malformed and network errors');
})().catch(e=>{console.error(e);process.exitCode=1;});
