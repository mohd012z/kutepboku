const MENU={inline_keyboard:[[{text:"📚 Search",callback_data:"m:search"},{text:"ℹ️ Help",callback_data:"m:help"}],[{text:"📊 Status",callback_data:"m:status"}]]};
function reply(command){
 if(command==="/start"||command==="/menu"||command==="m:menu")return {text:"📚 MSASoup menu",reply_markup:MENU};
 if(command==="/help"||command==="m:help")return {text:"Use /menu. The research engine is not connected to this Worker.",reply_markup:MENU};
 if(command==="/search"||command==="m:search")return {text:"Search is not available on this Worker yet. No search was started.",reply_markup:MENU};
 if(command==="/status"||command==="m:status")return {text:"📊 MSASoup status: Worker command handler active. Live webhook delivery and research engine availability are not confirmed by this message.",reply_markup:MENU};
 return null;
}
function equal(a,b){const x=new TextEncoder().encode(a),y=new TextEncoder().encode(b);let d=x.length^y.length;for(let i=0;i<Math.max(x.length,y.length);i++)d|=(x[i]||0)^(y[i]||0);return d===0;}
async function telegram(env,method,payload){
 const r=await fetch("https://api.telegram.org/bot"+env.TELEGRAM_BOT_TOKEN+"/"+method,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload),signal:AbortSignal.timeout(8000)});
 if(!r.ok)throw Error("Telegram HTTP "+r.status);
 const data=await r.json();if(!data.ok)throw Error("Telegram API rejected "+method);return data.result;
}
export default {async fetch(request,env){
 const path=new URL(request.url).pathname;
 if(path==="/health"&&request.method==="GET"){
  const configured=!!(env.DB&&env.TELEGRAM_BOT_TOKEN&&env.TELEGRAM_WEBHOOK_SECRET&&env.TELEGRAM_ALLOWED_USER_IDS);
  let databaseReady=false;
  if(configured){try{const row=await env.DB.prepare("SELECT 1 AS ok").first();databaseReady=row?.ok===1;}catch{databaseReady=false;}}
  return Response.json({service:"msasoup-telegram",configured,databaseReady,ready:configured&&databaseReady},{status:configured&&databaseReady?200:503});
 }
 if(path!=="/telegram"||request.method!=="POST")return new Response("Not found",{status:404});
 if(!env.DB||!env.TELEGRAM_BOT_TOKEN||!env.TELEGRAM_WEBHOOK_SECRET||!env.TELEGRAM_ALLOWED_USER_IDS)return new Response("Unavailable",{status:503});
 if(!equal(request.headers.get("X-Telegram-Bot-Api-Secret-Token")||"",env.TELEGRAM_WEBHOOK_SECRET))return new Response("Unauthorized",{status:401});
 const lengthHeader=request.headers.get("content-length");
 if(lengthHeader!==null){
  if(!/^(0|[1-9][0-9]*)$/.test(lengthHeader))return new Response("Invalid content length",{status:400});
  if(Number(lengthHeader)>65536)return new Response("Too large",{status:413});
 }
 const reader=request.body?.getReader();
 let raw="";
 if(reader){
  const decoder=new TextDecoder("utf-8",{fatal:true});
  let bytes=0;
  try{
   while(true){
    const {done,value}=await reader.read();
    if(done)break;
    bytes+=value.byteLength;
    if(bytes>65536){await reader.cancel().catch(()=>{});return new Response("Too large",{status:413});}
    raw+=decoder.decode(value,{stream:true});
   }
   raw+=decoder.decode();
  }catch{return new Response("Invalid UTF-8",{status:400});}
 }
 let update;try{update=JSON.parse(raw);}catch{return new Response("Bad JSON",{status:400});}
 if(!Number.isSafeInteger(update?.update_id)||update.update_id<0)return new Response("Bad update",{status:400});
 const message=update.message,callback=update.callback_query,actor=callback?.from||message?.from,chat=callback?.message?.chat||message?.chat;
 if(!chat?.id||!actor?.id)return new Response("OK");
 const allowed=(env.TELEGRAM_ALLOWED_USER_IDS||"").split(",").map(x=>x.trim()).filter(Boolean);
 if(!allowed.includes(String(actor.id)))return new Response("OK");
 const command=callback?callback.data:(message?.text||"").trim().split(/\s+/)[0].split("@")[0].toLowerCase();
 const response=reply(command);if(!response)return new Response("OK");
 if(typeof env.DB.prepare!=="function"||typeof env.DB.batch!=="function")return new Response("Unavailable",{status:503});
 const id=update.update_id;
 try{
  let existing=await env.DB.prepare("SELECT status FROM telegram_updates WHERE update_id=?").bind(id).first();
  if(!existing){
   try{
    await env.DB.batch([
     env.DB.prepare("INSERT INTO telegram_updates(update_id,status) VALUES (?,'received')").bind(id),
     env.DB.prepare("INSERT INTO telegram_outbox(update_id,chat_id,reply_text,status) VALUES (?,?,?,'pending')").bind(id,String(chat.id),response.text)
    ]);
   }catch(err){
    existing=await env.DB.prepare("SELECT status FROM telegram_updates WHERE update_id=?").bind(id).first();
    if(!existing)throw err;
   }
  }
  const current=await env.DB.prepare("SELECT status FROM telegram_outbox WHERE update_id=?").bind(id).first();
  if(!current)throw Error("Outbox row missing");
  if(current.status==="sent"){
   if(callback?.id)await telegram(env,"answerCallbackQuery",{callback_query_id:callback.id}).catch(()=>{});
   return new Response("OK");
  }
  // Unknown outcomes cannot be resent automatically without risking duplicate messages.
  if(current.status==="sending"||current.status==="uncertain")return new Response("Delivery requires reconciliation",{status:503});
  if(current.status!=="pending")return new Response("Invalid delivery state",{status:503});
  const claimed=await env.DB.prepare("UPDATE telegram_outbox SET status='sending',attempts=attempts+1 WHERE update_id=? AND status='pending' RETURNING id").bind(id).first();
  if(!claimed)return new Response("Concurrent delivery in progress",{status:503});
  await telegram(env,"sendMessage",{chat_id:chat.id,...response});
  const finalized=await env.DB.prepare("UPDATE telegram_outbox SET status='sent' WHERE update_id=? AND status='sending' RETURNING id").bind(id).first();
  if(!finalized)throw Error("Outbox finalization failed");
  // The outbox is authoritative after Telegram acknowledges delivery. A secondary status update must not turn a confirmed send into a retryable failure.
  await env.DB.prepare("UPDATE telegram_updates SET status='sent' WHERE update_id=?").bind(id).run().catch(()=>{});
  if(callback?.id)await telegram(env,"answerCallbackQuery",{callback_query_id:callback.id}).catch(()=>{});
  return new Response("OK");
 }catch(e){
  await env.DB.prepare("UPDATE telegram_outbox SET status='uncertain' WHERE update_id=? AND status='sending'").bind(id).run().catch(()=>{});
  return new Response("Temporary delivery failure",{status:503});
 }
}};