import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/worker.js';
test('unknown route is 404', async()=>{const r=await worker.fetch(new Request('https://example.test/nope'),{});assert.equal(r.status,404)});
test('health fails closed without bindings', async()=>{const r=await worker.fetch(new Request('https://example.test/health'),{});assert.equal((await r.json()).configured,false)});
test('webhook requires configured secrets',async()=>{const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',body:'{}'}),{});assert.equal(r.status,503)});
test('webhook rejects missing authentication',async()=>{const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',body:'{}'}),{DB:{},TELEGRAM_BOT_TOKEN:'test',TELEGRAM_WEBHOOK_SECRET:'secret',TELEGRAM_ALLOWED_USER_IDS:'123'});assert.equal(r.status,401)});
test('invalid JSON rejected after authentication',async()=>{const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:{'X-Telegram-Bot-Api-Secret-Token':'secret'},body:'{' }),{DB:{},TELEGRAM_BOT_TOKEN:'test',TELEGRAM_WEBHOOK_SECRET:'secret',TELEGRAM_ALLOWED_USER_IDS:'123'});assert.equal(r.status,400)});

test('missing allowlist fails closed',async()=>{const r=await worker.fetch(new Request('https://example.test/telegram',{method:'POST',headers:{'X-Telegram-Bot-Api-Secret-Token':'secret'},body:'{}'}),{DB:{},TELEGRAM_BOT_TOKEN:'test',TELEGRAM_WEBHOOK_SECRET:'secret'});assert.equal(r.status,503)});
