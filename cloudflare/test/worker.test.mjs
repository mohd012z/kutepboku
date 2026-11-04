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
test('interrupted webhook streams return retryable 503 without D1 access',async()=>{
 for(const error of [new Error('stream interrupted'),new TypeError('stream transport failure')]){
  let reads=0;
  const stream=new ReadableStream({pull(){throw error}});
  const env={...authEnv,DB:{prepare(){reads++;throw Error('D1 must not be accessed')}}};
  const request=new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body:stream,duplex:'half'});
  const response=await worker.fetch(request,env);
  assert.equal(response.status,503,'transport failure must remain retryable');
  assert.equal(reads,0);
 }
});
test('stream read failure after partial JSON remains retryable',async()=>{
 let count=0;
 const stream=new ReadableStream({pull(controller){
  if(count++===0)controller.enqueue(new TextEncoder().encode('{"update_id":1'));
  else controller.error(new Error('connection dropped'));
 }});
 const request=new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body:stream,duplex:'half'});
 const response=await worker.fetch(request,authEnv);
 assert.equal(response.status,503);
});
test('invalid UTF-8 split across stream chunks is a nonretryable 400',async()=>{
 const stream=new ReadableStream({start(controller){
  controller.enqueue(new Uint8Array([0xc3]));
  controller.enqueue(new Uint8Array([0x28]));
  controller.close();
 }});
 const request=new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body:stream,duplex:'half'});
 const response=await worker.fetch(request,authEnv);
 assert.equal(response.status,400);
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
const validSchema={
 telegram_updates:['update_id','status'],
 telegram_outbox:['id','update_id','chat_id','reply_text','status','attempts']
};
function schemaDb(schema=validSchema){
 const queries=[];
 return {queries,prepare(sql){
  const table=sql==='PRAGMA table_info(telegram_updates)' ? 'telegram_updates' :
   sql==='PRAGMA table_info(telegram_outbox)' ? 'telegram_outbox' : null;
  assert.ok(table,'unexpected schema probe: '+sql);
  queries.push(table);
  return {all:async()=>({results:(schema[table]||[]).map(name=>({name}))})};
 }};
}
test('health accepts empty D1 tables with all required columns',async()=>{
 const db=schemaDb();
 const r=await worker.fetch(new Request('https://example.test/health'),{...authEnv,DB:db});
 assert.equal(r.status,200);
 assert.equal((await r.json()).ready,true);
 assert.deepEqual(db.queries,['telegram_updates','telegram_outbox']);
});
test('health fails closed if the webhook D1 migration is missing',async()=>{
 const db=schemaDb({telegram_updates:validSchema.telegram_updates});
 const r=await worker.fetch(new Request('https://example.test/health'),{...authEnv,DB:db});
 assert.equal(r.status,503);
 const body=await r.json();
 assert.equal(body.configured,true);
 assert.equal(body.databaseReady,false);
 assert.equal(body.ready,false);
});
test('health rejects legacy tables missing required delivery columns',async()=>{
 const db=schemaDb({...validSchema,telegram_outbox:['id','update_id','status']});
 const r=await worker.fetch(new Request('https://example.test/health'),{...authEnv,DB:db});
 assert.equal(r.status,503);
 assert.equal((await r.json()).ready,false);
});
test('health rejects malformed schema metadata rather than claiming readiness',async()=>{
 const env={...authEnv,DB:{prepare(){return {all:async()=>({results:null})}}}};
 const r=await worker.fetch(new Request('https://example.test/health'),env);
 assert.equal(r.status,503);
 assert.equal((await r.json()).ready,false);
});
test('health fails closed on D1 schema query errors',async()=>{
 const env={...authEnv,DB:{prepare(){return {all:async()=>{throw Error('D1 unavailable')}}}}};
 const r=await worker.fetch(new Request('https://example.test/health'),env);
 assert.equal(r.status,503);
 assert.equal((await r.json()).ready,false);
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
    if(sql.includes('FROM telegram_updates')&&sql.includes('FROM telegram_outbox'))return {inbox_rows:updates.size,outbox_rows:outbox.size};
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
 globalThis.fetch=async()=>{sends++;return Response.json({ok:true,result:{message_id:7,chat:{id:123}}})};
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

test('concurrent identical updates cannot send twice after one successful claim',async()=>{
 const db=fakeD1(),original=globalThis.fetch;let sends=0;
 globalThis.fetch=async()=>{sends++;await Promise.resolve();return Response.json({ok:true,result:{message_id:77,chat:{id:123}}})};
 try{
  const env={...authEnv,DB:db},body=JSON.stringify({update_id:702,message:{from:{id:123},chat:{id:123},text:'/menu'}});
  const request=()=>worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body}),env);
  const results=await Promise.all([request(),request()]);
  assert.equal(sends,1);
  assert.ok(results.every(r=>[200,503].includes(r.status)));
  assert.equal(db.outbox.get(702).status,'sent');
 }finally{globalThis.fetch=original}
});
test('malformed callback actor is ignored without DB access',async()=>{
 const body=JSON.stringify({update_id:703,callback_query:{id:'cb',data:'m:menu',message:{chat:{id:123}}}});
 const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body}),authEnv);
 assert.equal(r.status,200);
});

test('secondary update status failure cannot negate a confirmed Telegram send',async()=>{
 const db=fakeD1(),original=globalThis.fetch,originalPrepare=db.prepare;let sends=0;
 db.prepare=function(sql){
  if(sql.startsWith("UPDATE telegram_updates SET status='sent'"))return {bind(){return {run:async()=>{throw Error('secondary status write unavailable')}}}};
  return originalPrepare(sql);
 };
 globalThis.fetch=async()=>{sends++;return Response.json({ok:true,result:{message_id:81,chat:{id:123}}})};
 try{
  const env={...authEnv,DB:db},body=JSON.stringify({update_id:704,message:{from:{id:123},chat:{id:123},text:'/menu'}});
  const send=()=>worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body}),env);
  assert.equal((await send()).status,200);
  assert.equal((await send()).status,200);
  assert.equal(sends,1);
  assert.equal(db.outbox.get(704).status,'sent');
 }finally{globalThis.fetch=original}
});

test('duplicate update repairs secondary status after confirmed send without resend',async()=>{
 const db=fakeD1(),original=globalThis.fetch;let sends=0;
 globalThis.fetch=async()=>{sends++;return Response.json({ok:true,result:{message_id:82,chat:{id:123}}})};
 try{
  const env={...authEnv,DB:db},body=JSON.stringify({update_id:705,message:{from:{id:123},chat:{id:123},text:'/menu'}});
  const send=()=>worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body}),env);
  assert.equal((await send()).status,200);
  db.updates.set(705,'received');
  assert.equal((await send()).status,200);
  assert.equal(sends,1);
  assert.equal(db.updates.get(705),'sent');
 }finally{globalThis.fetch=original}
});

test('menu callback sends exactly one menu and acknowledges callback',async()=>{
 const db=fakeD1(),original=globalThis.fetch,calls=[];
 globalThis.fetch=async(url,options)=>{calls.push({method:String(url).split('/').pop(),payload:JSON.parse(options.body)});return Response.json({ok:true,result:{message_id:99,chat:{id:123}}})};
 try{
  const env={...authEnv,DB:db};
  const body=JSON.stringify({update_id:801,callback_query:{id:'callback-801',from:{id:123},data:'m:menu',message:{chat:{id:123}}}});
  const request=()=>worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body}),env);
  assert.equal((await request()).status,200);
  assert.equal((await request()).status,200);
  assert.equal(calls.filter(c=>c.method==='sendMessage').length,1);
  assert.equal(calls[0].payload.reply_markup.inline_keyboard.length,2);
  assert.equal(calls.filter(c=>c.method==='answerCallbackQuery').length,2);
  assert.equal(db.outbox.get(801).status,'sent');
 }finally{globalThis.fetch=original}
});
test('search callback states actual unavailability instead of fabricating results',async()=>{
 const db=fakeD1(),original=globalThis.fetch,calls=[];
 globalThis.fetch=async(url,options)=>{calls.push({method:String(url).split('/').pop(),payload:JSON.parse(options.body)});return Response.json({ok:true,result:{message_id:100,chat:{id:123}}})};
 try{
  const env={...authEnv,DB:db};
  const body=JSON.stringify({update_id:802,callback_query:{id:'callback-802',from:{id:123},data:'m:search',message:{chat:{id:123}}}});
  const response=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body}),env);
  assert.equal(response.status,200);
  const sent=calls.find(c=>c.method==='sendMessage');
  assert.ok(sent);
  assert.match(sent.payload.text,/not available/i);
  assert.equal(calls.filter(c=>c.method==='answerCallbackQuery').length,1);
 }finally{globalThis.fetch=original}
});
test('unauthorized callback does not send or acknowledge through Telegram',async()=>{
 const original=globalThis.fetch;let calls=0;
 globalThis.fetch=async()=>{calls++;throw Error('should not call Telegram')};
 try{
  const body=JSON.stringify({update_id:803,callback_query:{id:'callback-803',from:{id:999},data:'m:menu',message:{chat:{id:999}}}});
  const response=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body}),authEnv);
  assert.equal(response.status,200);
  assert.equal(calls,0);
 }finally{globalThis.fetch=original}
});

test('callback acknowledgement failure cannot trigger duplicate send',async()=>{
 const db=fakeD1(),original=globalThis.fetch;let sends=0,acks=0;
 globalThis.fetch=async(url)=>{
  if(String(url).endsWith('/answerCallbackQuery')){acks++;throw Error('callback acknowledgement unavailable')}
  sends++;return Response.json({ok:true,result:{message_id:91,chat:{id:123}}});
 };
 try{
  const env={...authEnv,DB:db};
  const body=JSON.stringify({update_id:804,callback_query:{id:'callback-804',from:{id:123},data:'m:status',message:{chat:{id:123}}}});
  const request=()=>worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body}),env);
  assert.equal((await request()).status,200);
  assert.equal((await request()).status,200);
  assert.equal(sends,1);
  assert.equal(acks,2);
  assert.equal(db.outbox.get(804).status,'sent');
 }finally{globalThis.fetch=original}
});
test('search command does not claim verified book results when provider is disconnected',async()=>{
 const db=fakeD1(),original=globalThis.fetch;let payload;
 globalThis.fetch=async(url,options)=>{if(String(url).endsWith('/sendMessage'))payload=JSON.parse(options.body);return Response.json({ok:true,result:{message_id:92,chat:{id:123}}})};
 try{
  const body=JSON.stringify({update_id:805,message:{from:{id:123},chat:{id:123},text:'/search aviation'}});
  const response=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body}),{...authEnv,DB:db});
  assert.equal(response.status,200);
  assert.match(payload.text,/not available/i);
  assert.equal(db.outbox.get(805).status,'sent');
 }finally{globalThis.fetch=original}
});

for(const [caseName,receipt] of [
 ['missing message ID',{chat:{id:123}}],
 ['wrong destination',{message_id:91,chat:{id:999}}],
 ['boolean destination',{message_id:91,chat:{id:true}}],
 ['zero message ID',{message_id:0,chat:{id:123}}],
 ['missing destination',{message_id:91}]
]){
 test('unverified Telegram receipt: '+caseName+' is uncertain and not resent',async()=>{
  const db=fakeD1(),original=globalThis.fetch;let sends=0;
  globalThis.fetch=async(url)=>{
   if(String(url).endsWith('/sendMessage'))sends++;
   return Response.json({ok:true,result:receipt});
  };
  try{
   const id=806+['missing message ID','wrong destination','boolean destination','zero message ID','missing destination'].indexOf(caseName);
   const body=JSON.stringify({update_id:id,message:{from:{id:123},chat:{id:123},text:'/menu'}});
   const env={...authEnv,DB:db};
   const request=()=>worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:authHeaders,body}),env);
   assert.equal((await request()).status,503);
   assert.equal(db.outbox.get(id).status,'uncertain');
   assert.equal((await request()).status,503);
   assert.equal(sends,1);
  }finally{globalThis.fetch=original}
 });
}
