"""Hosted invite-accept page — the fallback for products with no
`settings.app_url`. A single static HTML document (no server-side
interpolation); it reads the token from the URL, previews the invite and posts
the chosen password to the public invite endpoints. Tokens from the response
are discarded — the user signs in from the product app afterwards."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.core.config import settings

router = APIRouter()

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Accept your invite</title>
<style>
body{font:16px/1.5 system-ui,sans-serif;max-width:420px;margin:12vh auto;padding:0 16px}
input,button{font:inherit;width:100%;padding:10px;margin:6px 0;box-sizing:border-box}
button{cursor:pointer}#msg{margin-top:12px}.err{color:#b00020}
</style></head><body>
<h1 id="title">Accept your invite</h1>
<p id="who"></p>
<form id="f" hidden>
  <input id="name" placeholder="Your name" autocomplete="name">
  <input id="pw" type="password" placeholder="Choose a password (__MINLEN__+ characters)"
         minlength="__MINLEN__" required autocomplete="new-password">
  <button type="submit">Create my account</button>
</form>
<p id="msg"></p>
<script>
const API="__API__/auth/invites";
const token=new URLSearchParams(location.search).get("token")||"";
history.replaceState(null,"",location.pathname);  // keep the token out of history
const $=id=>document.getElementById(id);
const say=(t,err)=>{$("msg").textContent=t;$("msg").className=err?"err":""};
async function post(path,body){
  const r=await fetch(API+path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const j=await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(j.message||"Something went wrong");
  return j;
}
(async()=>{
  try{
    const p=await post("/preview",{token});
    $("title").textContent="Welcome to "+p.product_name;
    $("who").textContent="Set a password for "+p.email;
    if(p.full_name) $("name").value=p.full_name;
    $("f").hidden=false;
  }catch(e){ say("This invite is invalid or has expired. Ask for a new one.",true); }
})();
$("f").addEventListener("submit",async ev=>{
  ev.preventDefault(); say("Creating your account…");
  try{
    await post("/accept",{token,password:$("pw").value,full_name:$("name").value||null});
    $("f").hidden=true; $("who").textContent="";
    say("Your account is ready. Open the app and sign in with your email and this password.");
  }catch(e){ say(e.message,true); }
});
</script></body></html>
"""


@router.get("/invite", include_in_schema=False)
async def invite_page() -> HTMLResponse:
    html = _PAGE.replace("__API__", settings.api_prefix).replace(
        "__MINLEN__", str(settings.password_min_length)
    )
    return HTMLResponse(
        html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    )
