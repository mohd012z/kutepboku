const MENU={inline_keyboard:[[{text:"📚 Search",callback_data:"m:search"},{text:"ℹ️ Help",callback_data:"m:help"}],[{text:"📊 Status",callback_data:"m:status"}]]};
function reply(command){
 if(command==="/start"||command==="/menu"||command==="m:menu")return {text:"📚 MSASoup menu",reply_markup:MENU};
 if(command==="/help"||command==="m:help")return {text:"Use /menu. The research engine is not connected to this Worker.",reply_markup:MENU};
 if(command==="/search"||command==="m:search")return {text:"Search is not available on this Worker yet. No search was started.",reply_markup:MENU};
 if(command==="/status"||command==="m:status")return {text:"MSASoup Worker is receiving updates. Research status is not verified.",reply_markup:MENU};
 return null;
}
function equal(a,b){const x=new TextEncoder().encode(a),y=new TextEncoder().encode(b);let d=x.length^y.length;for(let i=0;i<Math.max(x.length,y.length);i++)d|=(x[i]||0)^(y[i]||0);return d===0;}
async function telegram(env,method,payload){
 const r=await fetch("https://api.telegram.org/bot"+env.TELEGRAM_BOT_TOKEN+"/"+method,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});
 if(!r.ok)throw Error("Telegram HTTP "+r.status);
 const data=await r.json();if(!data.ok)throw Error("Telegram API rejected "+method);return data.result;
}
export default {async fetch(request,env){
 const path=new URL(request.url).pathname;
 if(path==="/health"&&request.method==="GET")return Response.json({service:"msasoup-telegram",configured:!!(env.DB&&env.TELEGRAM_BOT_TOKEN&&env.TELEGRAM_WEBHOOK_SECRET&&env.TELEGRAM_ALLOWED_USER_IDS)});
 if(path!=="/telegram"||request.method!=="POST")return new Response("Not found",{status:404});
 if(!env.DB||!env.TELEGRAM_BOT_TOKEN||!env.TELEGRAM_WEBHOOK_SECRET||!env.TELEGRAM_ALLOWED_USER_IDS)return new Response("Unavailable",{status:503});
 if(!equal(request.headers.get("X-Telegram-Bot-Api-Secret-Token")||"",env.TELEGRAM_WEBHOOK_SECRET))return new Response("Unauthorized",{status:401});
 const size=Number(request.headers.get("content-length"));if(Number.isFinite(size)&&size>65536)return new Response("Too large",{status:413});
 const raw=await request.text();if(new TextEncoder().encode(raw).byteLength>65536)return new Response("Too large",{status:413});
 let update;try{update=JSON.parse(raw);}catch{return new Response("Bad JSON",{status:400});}
 if(!Number.isSafeInteger(update?.update_id)||update.update_id<0)return new Response("Bad update",{status:400});
 const message=update.message,callback=update.callback_query,actor=callback?.from||message?.from,chat=callback?.message?.chat||message?.chat;
 if(!chat?.id||!actor?.id)return new Response("OK");
 const allowed=(env.TELEGRAM_ALLOWED_USER_IDS||"").split(",").map(x=>x.trim()).filter(Boolean);
 if(!allowed.includes(String(actor.id)))return new Response("OK");
 const command=callback?callback.data:(message?.text||"").trim().split(/\s+/)[0].split("@")[0].toLowerCase();
 const response=reply(command);if(!response)return new Response("OK");
 const id=update.update_id;
 try{
  const existing=await env.DB.prepare("SELECT status FROM telegram_updates WHERE update_id=?").bind(id).first();
  if(existing)return new Response("OK");
  try {await env.DB.batch([env.DB.prepare("INSERT INTO telegram_updates(update_id,status) VALUES (?,'received')").bind(id),env.DB.prepare("INSERT INTO telegram_outbox(update_id,chat_id,reply_text,status) VALUES (?,?,?,'pending')").bind(id,String(chat.id),response.text)]);}
  catch(err){const duplicate=await env.DB.prepare("SELECT status FROM telegram_updates WHERE update_id=?").bind(id).first();if(duplicate)return new Response("OK");throw err;}
  await env.DB.prepare("UPDATE telegram_outbox SET status='sending',attempts=attempts+1 WHERE update_id=? AND status='pending'").bind(id).run();
  await telegram(env,"sendMessage",{chat_id:chat.id,...response});
  await env.DB.prepare("UPDATE telegram_outbox SET status='sent' WHERE update_id=?").bind(id).run();
  await env.DB.prepare("UPDATE telegram_updates SET status='sent' WHERE update_id=?").bind(id).run();
  if(callback?.id)await telegram(env,"answerCallbackQuery",{callback_query_id:callback.id});
  return new Response("OK");
 }catch(e){
  await env.DB.prepare("UPDATE telegram_outbox SET status='uncertain' WHERE update_id=? AND status='sending'").bind(id).run().catch(()=>{});
  return new Response("Accepted for reconciliation",{status:200});
 }
}};