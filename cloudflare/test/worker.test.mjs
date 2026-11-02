import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/worker.js';
test('unknown route is 404', async()=>{const r=await worker.fetch(new Request('https://example.test/nope'),{});assert.equal(r.status,404)});
test('health fails closed without bindings', async()=>{const r=await worker.fetch(new Request('https://example.test/health'),{});assert.equal((await r.json()).configured,false)});
test('webhook requires configured secrets',async()=>{const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',body:'{}'}),{});assert.equal(r.status,503)});
test('webhook rejects missing authentication',async()=>{const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',body:'{}'}),{DB:{},TELEGRAM_BOT_TOKEN:'test',TELEGRAM_WEBHOOK_SECRET:'secret',TELEGRAM_ALLOWED_USER_IDS:'123'});assert.equal(r.status,401)});
test('invalid JSON rejected after authentication',async()=>{const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:{'X-Telegram-Bot-Api-Secret-Token':'secret'},body:'{' }),{DB:{},TELEGRAM_BOT_TOKEN:'test',TELEGRAM_WEBHOOK_SECRET:'secret',TELEGRAM_ALLOWED_USER_IDS:'123'});assert.equal(r.status,400)});

test('missing allowlist fails closed',async()=>{const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:{'X-Telegram-Bot-Api-Secret-Token':'secret'},body:'{}'}),{DB:{},TELEGRAM_BOT_TOKEN:'test',TELEGRAM_WEBHOOK_SECRET:'secret'});assert.equal(r.status,503)});

const authEnv={DB:{},TELEGRAM_BOT_TOKEN:'test',TELEGRAM_WEBHOOK_SECRET:'secret',TELEGRAM_ALLOWED_USER_IDS:'123'};
const authHeaders={'X-Telegram-Bot-Api-Secret-Token':'secret'};
test('health requires allowlist',async()=>{const r=await worker.fetch(new Request('https://example.test/health'),{DB:{},TELEGRAM_BOT_TOKEN:'test',TELEGRAM_WEBHOOK_SECRET:'secret'});assert.equal((await r.json()).configured,false)});
test('health accepts complete bindings',async()=>{const r=await worker.fetch(new Request('https://example.test/health'),authEnv);assert.equal((await r.json()).configured,true)});
test('negative update id rejected',async()=>{const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body:JSON.stringify({update_id:-1})}),authEnv);assert.equal(r.status,400)});
test('noninteger update id rejected',async()=>{const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body:JSON.stringify({update_id:1.5})}),authEnv);assert.equal(r.status,400)});
test('oversized UTF-8 body rejected',async()=>{const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body:JSON.stringify({update_id:1,message:{text:'🌍'.repeat(18000)}})}),authEnv);assert.equal(r.status,413)});
test('unrecognized update does not write to D1',async()=>{const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body:JSON.stringify({update_id:1})}),authEnv);assert.equal(r.status,200)});

test('unauthorized Telegram actor is ignored without database access',async()=>{
 const body=JSON.stringify({update_id:17,message:{from:{id:999},chat:{id:999},text:'/start'}});
 const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body}),authEnv);
 assert.equal(r.status,200);
 assert.equal(await r.text(),'OK');
});
test('unsupported command from authorized actor is ignored without database access',async()=>{
 const body=JSON.stringify({update_id:18,message:{from:{id:123},chat:{id:123},text:'/not-a-command'}});
 const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body}),authEnv);
 assert.equal(r.status,200);
 assert.equal(await r.text(),'OK');
});
test('valid Telegram update with missing D1 adapter fails closed',async()=>{
 const body=JSON.stringify({update_id:19,message:{from:{id:123},chat:{id:123},text:'/start'}});
 const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body}),authEnv);
 assert.equal(r.status,503);
});

test('invalid UTF-8 is rejected without D1 access',async()=>{
 const bytes=new Uint8Array([0xc3,0x28]);
 const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body:bytes}),authEnv);
 assert.equal(r.status,400);
});
test('oversized streamed body is rejected without D1 access',async()=>{
 const body=new ReadableStream({start(c){c.enqueue(new Uint8Array(32768));c.enqueue(new Uint8Array(32769));c.close()}});
 const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body,duplex:'half'}),authEnv);
 assert.equal(r.status,413);
});

test('health is 503 when D1 adapter is unavailable',async()=>{
 const r=await worker.fetch(new Request('https://example.test/health'),authEnv);
 const data=await r.json();
 assert.equal(r.status,503);
 assert.equal(data.configured,true);
 assert.equal(data.databaseReady,false);
 assert.equal(data.ready,false);
});
test('health is ready only after a successful D1 query',async()=>{
 const env={...authEnv,DB:{prepare(sql){assert.equal(sql,'SELECT 1 AS ok');return {first:async()=>({ok:1})}}}};
 const r=await worker.fetch(new Request('https://example.test/health'),env);
 assert.equal(r.status,200);
 assert.equal((await r.json()).ready,true);
});

test('content-length above limit is rejected before body processing',async()=>{
 const body=JSON.stringify({update_id:22});
 const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:{...authHeaders,'content-length':'65537'},body}),authEnv);
 assert.equal(r.status,413);
});
test('missing content-length still permits a valid ignored update',async()=>{
 const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body:JSON.stringify({update_id:23})}),authEnv);
 assert.equal(r.status,200);
});

test('malformed content-length is rejected before database access',async()=>{
 const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:{...authHeaders,'content-length':'garbage'},body:'{}'}),authEnv);
 assert.equal(r.status,400);
});
test('negative content-length is rejected before database access',async()=>{
 const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:{...authHeaders,'content-length':'-1'},body:'{}'}),authEnv);
 assert.equal(r.status,400);
});

function fakeD1(){
 const updates=new Map(),outbox=new Map();
 function statement(sql,args=[]){
  return {
   sql,args,
   bind(...values){return statement(sql,values)},
   async first(){
    const id=args[0];
    if(sql.startsWith('SELECT status FROM telegram_updates'))return updates.has(id)?{status:updates.get(id)}:null;
    if(sql.startsWith('SELECT status FROM telegram_outbox'))return outbox.has(id)?{status:outbox.get(id).status}:null;
    if(sql.startsWith("UPDATE telegram_outbox SET status='sending'")){
     const row=outbox.get(id);if(!row||row.status!=='pending')return null;
     row.status='sending';row.attempts++;return {id:1};
    }
    if(sql.startsWith("UPDATE telegram_outbox SET status='sent'")){
     const row=outbox.get(id);if(!row||row.status!=='sending')return null;
     row.status='sent';return {id:1};
    }
    if(sql==='SELECT 1 AS ok')return {ok:1};
    throw Error('Unexpected first SQL: '+sql);
   },
   async run(){
    const id=args[0];
    if(sql.startsWith("UPDATE telegram_updates SET status='sent'")){updates.set(id,'sent');return {success:true}}
    if(sql.startsWith("UPDATE telegram_outbox SET status='uncertain'")){
     const row=outbox.get(id);if(row?.status==='sending')row.status='uncertain';
     return {success:true};
    }
    throw Error('Unexpected run SQL: '+sql);
   }
  };
 }
 return {updates,outbox,prepare:statement,async batch(statements){
  for(const s of statements){
   const sql=s.sql,args=s.args;
   if(sql.startsWith('INSERT INTO telegram_updates'))updates.set(args[0],'received');
   else if(sql.startsWith('INSERT INTO telegram_outbox'))outbox.set(args[0],{status:'pending',attempts:0});
   else throw Error('Unexpected batch SQL: '+sql);
  }
 }};
}
test('duplicate authorized update is delivered only once in mock D1',async()=>{
 const db=fakeD1(),original=globalThis.fetch;let sends=0;
 globalThis.fetch=async()=>{sends++;return Response.json({ok:true,result:{message_id:7}})};
 try{
  const env={...authEnv,DB:db},body=JSON.stringify({update_id:700,message:{from:{id:123},chat:{id:123},text:'/menu'}});
  for(let i=0;i<2;i++){
   const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body}),env);
   assert.equal(r.status,200);
  }
  assert.equal(sends,1);assert.equal(db.outbox.get(700).status,'sent');
 }finally{globalThis.fetch=original}
});
test('ambiguous Telegram send remains uncertain and is never automatically resent',async()=>{
 const db=fakeD1(),original=globalThis.fetch;let sends=0;
 globalThis.fetch=async()=>{sends++;throw Error('simulated lost Telegram response')};
 try{
  const env={...authEnv,DB:db},body=JSON.stringify({update_id:701,message:{from:{id:123},chat:{id:123},text:'/start'}});
  const send=()=>worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body}),env);
  assert.equal((await send()).status,503);
  assert.equal(db.outbox.get(701).status,'uncertain');
  assert.equal((await send()).status,503);
  assert.equal(sends,1);
 }finally{globalThis.fetch=original}
});
