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
