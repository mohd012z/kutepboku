import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/worker.js';
import {gatherGlobal, research, researchReport, researchMenuMarkup,
        subjectTopic, RESEARCH_SUBJECTS} from '../src/research.js';

const authEnv={DB:{},TELEGRAM_BOT_TOKEN:'test',TELEGRAM_WEBHOOK_SECRET:'secret',TELEGRAM_ALLOWED_USER_IDS:'123'};
const authHeaders={'X-Telegram-Bot-Api-Secret-Token':'secret'};

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

// One fake globalThis.fetch that answers every registry, the LLM, and Telegram.
function wireFetch(t){
 const calls=[];
 globalThis.fetch=async(url,opts)=>{
  const u=String(url);calls.push({url:u,method:opts?.method||'GET'});
  if(u.startsWith('https://api.telegram.org/')){
   const method=u.split('/').pop();
   if(method==='sendMessage')return Response.json({ok:true,result:{message_id:500,chat:{id:123}}});
   if(method==='answerCallbackQuery')return Response.json({ok:true,result:true});
   return Response.json({ok:true,result:{}});
  }
  if(u.startsWith('https://minda.test/')){
   return Response.json({choices:[{message:{content:"OVERVIEW: test digest\nNOTES: fine."}}]});
  }
  if(u.startsWith('https://api.github.com/search/repositories')){
   return Response.json({items:[{full_name:'gh/one',description:'gh hit',stargazers_count:9},
    {full_name:'bad',description:'no slash',stargazers_count:1}]});
  }
  if(u.startsWith('https://gitlab.com/api/v4/projects')){
   return Response.json([{path_with_namespace:'gl/one',web_url:'https://gitlab.com/gl/one',
    description:'gl hit',star_count:3},
    {path_with_namespace:'gl/deletion_scheduled_x',star_count:5}]);
  }
  if(u.startsWith('https://registry.npmjs.org/-/v1/search')){
   return Response.json({objects:[{package:{name:'npm-one',description:'npm hit'},
    downloads:{monthly:1200}}]});
  }
  if(u.startsWith('https://crates.io/api/v1/crates')){
   return Response.json({crates:[{name:'crates-one',description:'crates hit',downloads:5000,
    repository_url:'https://github.com/c/rates'},{name:'tiny',downloads:10}]});
  }
  if(u.startsWith('https://hub.docker.com/v2/search/repositories/')){
   return Response.json({results:[{repo_name:'docker/one',short_description:'docker hit',
    pull_count:42}]});
  }
  if(u.includes('archive.org/advancedsearch.php')){
   return Response.json({response:{docs:[{identifier:'ia-one',title:'IA Book',
    author_name:['A Author']}]}},{status:200});
  }
  if(u.includes('gutenberg.org/ebooks/search.opds/')){
   return new Response('<feed><entry><id>https://www.gutenberg.org/ebooks/42.opds</id>'+
    '<title>PG Book</title></entry></feed>',{headers:{'content-type':'application/atom+xml'}});
  }
  return Response.json({});
 };
 return calls;
}

test('subject grid: 12 subjects, 2 per row',async()=>{
 assert.equal(RESEARCH_SUBJECTS.length,12);
 const kb=researchMenuMarkup().inline_keyboard;
 assert.equal(kb.length,7);
 for(const row of kb.slice(0,6))assert.equal(row.length,2);
 for(const row of kb.slice(0,6))for(const b of row)assert.ok(b.callback_data.startsWith('res:'));
 assert.equal(kb[6][0].callback_data,'m:menu');
});

test('subjectTopic maps grid keys to research phrases',async()=>{
 assert.equal(subjectTopic('ml'),'machine learning');
 assert.equal(subjectTopic('med'),'medicine');
 assert.equal(subjectTopic('nope'),null);
});

test('gatherGlobal merges 5 sources, drops dead ones, floors noise',async()=>{
 const original=globalThis.fetch;
 globalThis.fetch=async(url,opts)=>{
  const u=String(url);
  if(u.startsWith('https://api.github.com/'))return Response.json({items:[]});
  if(u.startsWith('https://gitlab.com/'))throw new Error('gitlab down');
  if(u.startsWith('https://registry.npmjs.org/'))return Response.json({objects:[]});
  if(u.startsWith('https://crates.io/'))return Response.json({crates:
   [{name:'good',downloads:5000,description:'x'},
    {name:'noise',downloads:5,description:'y'}]});
  if(u.startsWith('https://hub.docker.com/'))return Response.json({results:
   [{repo_name:'docker/one',short_description:'d',pull_count:1}]});
  return new Response('nope',{status:404});
 };
 try{
  const r=await gatherGlobal('quantum computing',4);
  assert.deepEqual(Object.keys(r).sort(),['crates','docker']);
  assert.equal(r.crates[0].id,'good');
  assert.ok(!r.crates.some(c=>c.id==='noise'));
 }finally{globalThis.fetch=original}
});

test('research() gathers ebooks + global sources and LLM digest (fail-open LLM)',async()=>{
 const original=globalThis.fetch;
 globalThis.fetch=async(url)=>{
  const u=String(url);
  if(u.includes('chat/completions'))throw new Error('minda down'); // LLM fail-open
  if(u.startsWith('https://api.github.com/search/repositories'))
   return Response.json({items:[{full_name:'gh/one',description:'d',stargazers_count:9}]});
  if(u.startsWith('https://gitlab.com/'))return Response.json([]);
  if(u.startsWith('https://registry.npmjs.org/'))return Response.json({objects:[]});
  if(u.startsWith('https://crates.io/'))return Response.json({crates:[]});
  if(u.startsWith('https://hub.docker.com/'))return Response.json({results:[]});
  if(u.includes('archive.org/advancedsearch.php'))
   return Response.json({response:{docs:[{identifier:'ia-one',title:'IA Book'}]}});
  if(u.includes('gutenberg.org/ebooks/search.opds/'))
   return new Response('<feed></feed>');
  return new Response('{}',{status:200});
 };
 try{
  const r=await research('machine learning',{}); // no MINDA_* -> digest null
  assert.equal(r.nEbooks,1);
  assert.equal(r.nGlobal,1);
  assert.ok(r.sources.github[0].url.startsWith('https://github.com/'));
  assert.equal(r.digest,null);
  const text=researchReport(r);
  assert.match(text,/Research report/);
  assert.match(text,/AI digest unavailable/);
  assert.match(text,/gh\/one/);
  assert.match(text,/ia-one/);
 }finally{globalThis.fetch=original}
});

test('research() includes LLM digest when Minda is configured',async()=>{
 const original=globalThis.fetch;
 globalThis.fetch=async(url)=>{
  const u=String(url);
  if(u.startsWith('https://minda.test/'))
   return Response.json({choices:[{message:{content:'OVERVIEW: bullets here.'}}]});
  if(u.startsWith('https://api.github.com/'))return Response.json({items:
   [{full_name:'gh/one',description:'d',stargazers_count:9}]});
  if(u.startsWith('https://gitlab.com/'))return Response.json([]);
  if(u.startsWith('https://registry.npmjs.org/'))return Response.json({objects:[]});
  if(u.startsWith('https://crates.io/'))return Response.json({crates:[]});
  if(u.startsWith('https://hub.docker.com/'))return Response.json({results:[]});
  if(u.includes('archive.org/'))return Response.json({response:{docs:[]}});
  if(u.includes('gutenberg.org/'))return new Response('<feed></feed>');
  return new Response('{}',{status:200});
 };
 try{
  const r=await research('physics',{MINDA_BASE_URL:'https://minda.test/v1',
   MINDA_API_KEY:'k',MINDA_MODEL:'m'});
  assert.equal(r.digest,'OVERVIEW: bullets here.');
  assert.match(researchReport(r),/AI digest/);
 }finally{globalThis.fetch=original}
});

test('/research <subject> webhook delivers one verified report message',async()=>{
 const db=fakeD1(),calls=wireFetch();
 const body=JSON.stringify({update_id:901,message:{from:{id:123},chat:{id:123},
  text:'/research machine learning'}});
 const r=await worker.fetch(new Request('https://example.test/telegram',
  {method:'POST',headers:authHeaders,body}),{...authEnv,DB:db,
  MINDA_BASE_URL:'https://minda.test/v1',MINDA_API_KEY:'k',MINDA_MODEL:'m'});
 assert.equal(r.status,200);
 const sends=calls.filter(c=>c.url.endsWith('/sendMessage'));
 assert.equal(sends.length,1);
 assert.equal(db.outbox.get(901).status,'sent');
});

test('res:ml callback runs research and delivers the report',async()=>{
 const db=fakeD1();
 const original=globalThis.fetch;let sent=null;
 globalThis.fetch=async(url,opts)=>{
  const u=String(url);
  if(u.endsWith('/sendMessage')){sent=JSON.parse(opts.body);return Response.json({ok:true,result:{message_id:501,chat:{id:123}}})}
  if(u.endsWith('/answerCallbackQuery'))return Response.json({ok:true,result:true});
  if(u.includes('chat/completions'))throw new Error('minda down');
  if(u.startsWith('https://api.github.com/'))return Response.json({items:
   [{full_name:'gh/ml',description:'d',stargazers_count:5}]});
  if(u.startsWith('https://gitlab.com/'))return Response.json([]);
  if(u.startsWith('https://registry.npmjs.org/'))return Response.json({objects:[]});
  if(u.startsWith('https://crates.io/'))return Response.json({crates:[]});
  if(u.startsWith('https://hub.docker.com/'))return Response.json({results:[]});
  if(u.includes('archive.org/'))return Response.json({response:{docs:[]}});
  if(u.includes('gutenberg.org/'))return new Response('<feed></feed>');
  return new Response('{}',{status:200});
 };
 try{
  const body=JSON.stringify({update_id:902,callback_query:{id:'cb-902',from:{id:123},
   data:'res:ml',message:{chat:{id:123}}}});
  const r=await worker.fetch(new Request('https://example.test/telegram',
   {method:'POST',headers:authHeaders,body}),{...authEnv,DB:db});
  assert.equal(r.status,200);
  assert.ok(sent);
  assert.match(sent.text,/Research report/);
  assert.match(sent.text,/machine learning/);
  assert.equal(db.outbox.get(902).status,'sent');
 }finally{globalThis.fetch=original}
});

test('res:menu callback delivers the 12-subject grid',async()=>{
 const db=fakeD1();
 const original=globalThis.fetch;let sent=null;
 globalThis.fetch=async(url,opts)=>{
  const u=String(url);
  if(u.endsWith('/sendMessage')){sent=JSON.parse(opts.body);return Response.json({ok:true,result:{message_id:502,chat:{id:123}}})}
  if(u.endsWith('/answerCallbackQuery'))return Response.json({ok:true,result:true});
  return new Response('{}',{status:200});
 };
 try{
  const body=JSON.stringify({update_id:903,callback_query:{id:'cb-903',from:{id:123},
   data:'res:menu',message:{chat:{id:123}}}});
  const r=await worker.fetch(new Request('https://example.test/telegram',
   {method:'POST',headers:authHeaders,body}),{...authEnv,DB:db});
  assert.equal(r.status,200);
  assert.ok(sent);
  assert.equal(sent.reply_markup.inline_keyboard.length,7);
 }finally{globalThis.fetch=original}
});

test('unknown res: key is acknowledged without research or outbox row',async()=>{
 const db=fakeD1();
 const original=globalThis.fetch;let calls=0;
 globalThis.fetch=async(url)=>{calls++;const u=String(url);
  if(u.endsWith('/answerCallbackQuery'))return Response.json({ok:true,result:true});
  return new Response('{}',{status:200});};
 try{
  const body=JSON.stringify({update_id:904,callback_query:{id:'cb-904',from:{id:123},
   data:'res:zzz',message:{chat:{id:123}}}});
  const r=await worker.fetch(new Request('https://example.test/telegram',
   {method:'POST',headers:authHeaders,body}),{...authEnv,DB:db});
  assert.equal(r.status,200);
  assert.equal(db.outbox.has(904),false);
 }finally{globalThis.fetch=original}
});

test('/research with no subject offers the grid instead of running',async()=>{
 const db=fakeD1();
 const original=globalThis.fetch;let sent=null;
 globalThis.fetch=async(url,opts)=>{
  const u=String(url);
  if(u.endsWith('/sendMessage')){sent=JSON.parse(opts.body);return Response.json({ok:true,result:{message_id:503,chat:{id:123}}})}
  if(u.endsWith('/answerCallbackQuery'))return Response.json({ok:true,result:true});
  return new Response('{}',{status:200});
 };
 try{
  const body=JSON.stringify({update_id:905,message:{from:{id:123},chat:{id:123},text:'/research'}});
  const r=await worker.fetch(new Request('https://example.test/telegram',
   {method:'POST',headers:authHeaders,body}),{...authEnv,DB:db});
  assert.equal(r.status,200);
  assert.ok(sent);
  assert.ok(sent.reply_markup.inline_keyboard.length>=7);
 }finally{globalThis.fetch=original}
});
