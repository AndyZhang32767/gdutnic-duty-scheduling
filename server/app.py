from __future__ import annotations

import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.middleware.sessions import SessionMiddleware

from server import admin_store, chat_store, db, duty_settings, field_duty, operation_log, overview, permissions, schedule_store, swap_store, system_clock, weekly_store, member_store, security
from server.mcp_client import McpError, OutlineMcpClient, normalize_mcp_url
from server.oauth import exchange_code, start_oauth

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DATA = ROOT / "data"
ICON = ROOT / "icon"
DEFAULT_MCP = ""


def _session_secret() -> str:
    env = os.environ.get("SESSION_SECRET")
    if env:
        return env
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / "session_secret.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    secret = secrets.token_hex(32)
    path.write_text(secret, encoding="utf-8")
    return secret


@asynccontextmanager
def _qq_bot():
    """Load the optional QQ bridge lazily: it pulls in asyncio helpers we otherwise skip."""
    from server import qq_bot
    return qq_bot


def _chat_helpers():
    from server import chat
    return chat


async def lifespan(_app: FastAPI):
    admin_store.load()
    permissions.ensure_defaults()
    system_clock.load()
    with db.read() as conn:
        operation_log.init(conn)
    result = member_store.provision()
    print(f"[members] 新建普通用户账号 {result['created']} 个，保留现有账号 {result['existing']} 个")
    slug = admin_store.path()
    print("")
    print(f"管理员界面: http://127.0.0.1:50025/{slug}")
    if not admin_store.has_user():
        print("尚未注册管理员，首次打开站点会跳转到该地址并创建账号。")
    print("")
    if admin_store.qq_config().get('enabled'):
        await _qq_bot().sync()
    yield
    if admin_store.qq_config().get('enabled'):
        await _qq_bot().stop()


class NoCacheStatic(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        # Old scripts must never survive a deploy; browsers revalidate every static file.
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


app = FastAPI(title="网络服务协会 排班签到", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret(),
    session_cookie="gdutnic_wiki",
    same_site="lax",
    # HTTPS is required whenever the app is served over TLS; plain HTTP on a LAN stays usable.
    https_only=os.environ.get("SESSION_HTTPS_ONLY", "").lower() in {"1", "true", "yes"},
    max_age=security.SESSION_TTL,
)

ADMIN_LIMITER = security.AttemptLimiter()
MEMBER_LIMITER = security.AttemptLimiter()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)

    # Credentials must never leak through a referrer or be framed for clickjacking.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline';"
        " script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none';"
        " form-action 'self'",
    )
    if os.environ.get("SESSION_HTTPS_ONLY", "").lower() in {"1", "true", "yes"}:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response

VISITOR_COOKIE = "gdutnic_visitor"
ADMIN_COOKIE = "gdutnic_admin"


def _admin_signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_session_secret(), salt="gdutnic-admin")


def _set_admin_cookie(response: JSONResponse, username: str) -> None:
    token = _admin_signer().dumps({"u": username})
    response.set_cookie(
        ADMIN_COOKIE,
        token,
        max_age=security.SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("SESSION_HTTPS_ONLY", "").lower() in {"1", "true", "yes"},
        path="/",
    )


def _clear_admin_cookie(response: JSONResponse) -> None:
    response.delete_cookie(ADMIN_COOKIE, path="/")


def _admin_from_cookie(request: Request) -> str:
    raw = request.cookies.get(ADMIN_COOKIE) or ""
    if not raw:
        return ""
    try:
        data = _admin_signer().loads(raw, max_age=security.SESSION_TTL)
    except (BadSignature, Exception):
        return ""
    name = str(data.get("u") or "").strip()
    if name and name in admin_store.usernames():
        return name
    return ""


def _visitor_id(request: Request) -> str:
    value = (request.cookies.get(VISITOR_COOKIE) or "").strip()
    if len(value) >= 16:
        return value
    return secrets.token_urlsafe(18)


def _with_visitor_cookie(request: Request, payload: dict[str, Any], visitor: str) -> JSONResponse:
    response = JSONResponse(payload)
    if request.cookies.get(VISITOR_COOKIE) != visitor:
        response.set_cookie(
            VISITOR_COOKIE,
            visitor,
            max_age=60 * 60 * 24 * 400,
            httponly=True,
            samesite="lax",
            path="/",
        )
    return response

app.mount("/static", NoCacheStatic(directory=WEB), name="static")
ICON.mkdir(parents=True, exist_ok=True)
app.mount("/icon", NoCacheStatic(directory=ICON), name="icon")


@app.get("/favicon.ico")
async def favicon():
    path = ICON / "gdutnic.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="缺少 icon/gdutnic.png")
    return FileResponse(path, media_type="image/png")


@app.get("/")
async def index():
    if not admin_store.has_user():
        return RedirectResponse(f"/{admin_store.path()}", status_code=302)
    return FileResponse(
        WEB / "index.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def _resolve_mcp_url(request: Request, body: dict[str, Any] | None = None) -> str:
    body = body or {}
    admin = admin_store.mcp_url()
    if admin:
        return admin
    return ((body.get("mcp_url") or "") or request.session.get("mcp_url") or "").strip()


@app.get("/api/defaults")
async def defaults(request: Request) -> dict[str, Any]:
    session = request.session
    return {
        "mcp_url": admin_store.mcp_url() or session.get("mcp_url") or "",
        "has_outline_token": bool(session.get("outline_token") or session.get("mcp_api_key")),
        "oauth_connected": bool(session.get("outline_token")),
    }


@app.post("/api/settings")
async def save_settings(request: Request) -> dict[str, Any]:
    body = await request.json()
    raw = (body.get("mcp_url") or "").strip()
    if raw:
        request.session["mcp_url"] = normalize_mcp_url(raw)
    api_key = (body.get("mcp_api_key") or "").strip()
    if api_key:
        request.session["mcp_api_key"] = api_key
    if body.get("clear_mcp_api_key"):
        request.session.pop("mcp_api_key", None)
    return {"ok": True, "mcp_url": request.session["mcp_url"]}


@app.post("/api/mcp/connect")
async def mcp_connect(request: Request) -> dict[str, Any]:
    body = await request.json()
    raw = _resolve_mcp_url(request, body)
    if not raw:
        raise HTTPException(status_code=400, detail="请先在管理员界面填写网协 MCP 地址")
    mcp_url = normalize_mcp_url(raw)
    request.session["mcp_url"] = mcp_url
    token = _token_from(request, body)
    if not token:
        raise HTTPException(status_code=401, detail="尚未登录：请点击「企业登录」在弹窗中输入账号密码")
    try:
        async with OutlineMcpClient(mcp_url, token) as mcp:
            tools = await mcp.list_tools()
            return {
                "ok": True,
                "mcp_url": mcp.mcp_url,
                "server": mcp.server_info.get("serverInfo") or mcp.server_info,
                "tools": [
                    {"name": t.get("name"), "description": t.get("description") or ""}
                    for t in tools
                ],
            }
    except McpError as exc:
        print(f"[mcp_connect] {exc} payload={exc.payload!r}")
        status = exc.status if exc.status and 400 <= exc.status < 600 else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except Exception as exc:
        print(f"[mcp_connect] {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=502, detail=f"MCP 连接失败: {type(exc).__name__}: {exc}") from exc


@app.get("/api/mcp/oauth/start")
async def oauth_start(request: Request, mcp_url: str | None = None):
    raw = (admin_store.mcp_url() or mcp_url or request.session.get("mcp_url") or "").strip()
    if not raw:
        return _oauth_popup_result("missing_url")
    mcp_url = normalize_mcp_url(raw)
    redirect_uri = str(request.base_url).rstrip("/") + str(request.url_for("oauth_callback").path)
    try:
        flow = await start_oauth(mcp_url, redirect_uri)
    except Exception as exc:
        print(f"[oauth_start] {type(exc).__name__}: {exc}")
        return _oauth_popup_result("start", str(exc))
    flow["redirect_uri"] = redirect_uri
    request.session["oauth_flow"] = flow
    request.session["mcp_url"] = mcp_url
    return RedirectResponse(flow["authorize_url"], status_code=302)


@app.get("/api/mcp/oauth/callback")
async def oauth_callback(request: Request, code: str | None = None, state: str | None = None) -> HTMLResponse:
    flow = request.session.get("oauth_flow") or {}
    if not code or not flow:
        return _oauth_popup_result("missing")
    if state != flow.get("state"):
        return _oauth_popup_result("state")
    try:
        tokens = await exchange_code(
            token_endpoint=flow["token_endpoint"],
            client_id=flow["client_id"],
            client_secret=flow.get("client_secret") or "",
            code=code,
            redirect_uri=flow.get("redirect_uri") or str(request.url_for("oauth_callback")),
            code_verifier=flow["code_verifier"],
            mcp_url=flow["mcp_url"],
        )
    except Exception as exc:
        return _oauth_popup_result("token", str(exc))
    request.session["outline_token"] = (
        tokens.get("access_token")
        or (tokens.get("data") or {}).get("access_token")
        or ""
    )
    request.session["outline_refresh"] = tokens.get("refresh_token")
    request.session["oauth_meta"] = {
        "token_endpoint": flow["token_endpoint"],
        "client_id": flow["client_id"],
        "client_secret": flow.get("client_secret") or "",
        "mcp_url": flow["mcp_url"],
    }
    request.session.pop("oauth_flow", None)
    if _admin_ok(request) and request.session.get("outline_token"):
        admin_store.save_oauth(
            request.session.get("outline_token") or "",
            request.session.get("outline_refresh") or "",
            request.session.get("oauth_meta") or {},
        )
    return _oauth_popup_result(
        "ok",
        extra={
            "access_token": request.session.get("outline_token") or "",
            "refresh_token": request.session.get("outline_refresh") or "",
            "mcp_url": flow.get("mcp_url") or "",
        },
    )


@app.post("/api/mcp/restore")
async def mcp_restore(request: Request) -> dict[str, bool]:
    body = await request.json()
    token = (body.get("outline_token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="缺少登录凭证")
    request.session["outline_token"] = token
    refresh = (body.get("outline_refresh") or "").strip()
    if refresh:
        request.session["outline_refresh"] = refresh
    raw = (body.get("mcp_url") or "").strip()
    if raw:
        request.session["mcp_url"] = normalize_mcp_url(raw)
    return {"ok": True}


@app.post("/api/mcp/logout")
async def mcp_logout(request: Request) -> dict[str, bool]:
    for key in ("outline_token", "outline_refresh", "oauth_meta", "mcp_api_key", "oauth_flow"):
        request.session.pop(key, None)
    return {"ok": True}


@app.post("/api/chat")
async def chat(request: Request) -> StreamingResponse:
    body = await request.json()
    raw = _resolve_mcp_url(request, body)
    if not raw:
        raise HTTPException(status_code=400, detail="请先在管理员界面填写网协 MCP 地址")
    mcp_url = normalize_mcp_url(raw)
    request.session["mcp_url"] = mcp_url
    token = _token_from(request, body)
    if not token:
        return JSONResponse({"error": "尚未连接 Outline MCP，请先在弹窗中完成企业登录"}, status_code=401)

    openai_base, openai_key, model, provider = admin_store.chat_credentials()
    messages = []
    for item in body.get("messages") or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = chat_store._trim_content(item.get("content"))
        if content in ("", []):
            continue
        messages.append({"role": role, "content": content})
    if not openai_base or not openai_key or not model:
        raise HTTPException(status_code=400, detail="尚未配置模型接口，请先打开管理员界面完成设置")
    if not messages:
        raise HTTPException(status_code=400, detail="消息不能为空")

    async def events():
        try:
            async with OutlineMcpClient(mcp_url, token) as mcp:
                tools = await mcp.list_tools() if admin_store.mcp_heat() > 0 else []
                yield _sse({"type": "mcp_ready", "tools": [t.get("name") for t in tools]})
                async for event in _chat_helpers().stream_chat(
                    openai_base=openai_base,
                    openai_key=openai_key,
                    model=model,
                    messages=messages,
                    mcp=mcp,
                    tools=tools,
                    provider=provider,
                    system_prompt=admin_store.system_prompt(),
                    mcp_heat=admin_store.mcp_heat(),
                ):
                    yield _sse(event)
        except McpError as exc:
            yield _sse({"type": "error", "message": str(exc)})
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/api/chat/title")
async def chat_title(request: Request) -> dict[str, str]:
    body = await request.json()
    openai_base, openai_key, model, provider = admin_store.chat_credentials()
    if not openai_base or not openai_key or not model:
        raise HTTPException(status_code=400, detail="尚未配置模型接口")
    messages = []
    for item in body.get("messages") or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = chat_store._trim_content(item.get("content"))
        if isinstance(content, list):
            texts = [
                part
                for part in content
                if isinstance(part, dict) and part.get("type") == "text" and str(part.get("text") or "").strip()
            ]
            content = texts
        if role != "assistant":
            continue
        if content in ("", []):
            continue
        messages.append({"role": "assistant", "content": content})
        if len(messages) >= 2:
            break
    if not messages:
        raise HTTPException(status_code=400, detail="消息不能为空")
    try:
        title = await _chat_helpers().summarize_title(
            openai_base=openai_base,
            openai_key=openai_key,
            model=model,
            messages=messages,
            provider=provider,
        )
    except Exception:
        title = ""
    return {"title": title}


def _token_from(request: Request, body: dict[str, Any]) -> str:
    from_body = (body.get("mcp_api_key") or "").strip()
    if from_body:
        request.session["mcp_api_key"] = from_body
        return from_body
    return (
        request.session.get("mcp_api_key")
        or request.session.get("outline_token")
        or ""
    ).strip()


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _oauth_popup_result(status: str, message: str = "", extra: dict[str, Any] | None = None) -> HTMLResponse:
    payload = json.dumps(
        {"type": "outline-oauth", "status": status, "message": message, **(extra or {})},
        ensure_ascii=False,
    )
    ok = status == "ok"
    detail = message or ("登录成功，正在关闭窗口…" if ok else "登录未完成，请关闭此窗口后重试。")
    auto_close = "window.close();" if ok else ""
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
  <head><meta charset="utf-8"><title>知识库登录</title></head>
  <body style="font-family:sans-serif;padding:24px;max-width:420px">
    <p>{detail}</p>
    <script>
      const payload = {payload};
      try {{
        if (payload.status === "ok" && payload.access_token) {{
          localStorage.setItem("gdutnic-wiki-auth", JSON.stringify({{
            access_token: payload.access_token,
            refresh_token: payload.refresh_token || "",
            mcp_url: payload.mcp_url || ""
          }}));
        }}
      }} catch (e) {{}}
      try {{
        if (window.opener) {{
          window.opener.postMessage(payload, window.location.origin);
        }}
      }} catch (e) {{}}
      {auto_close}
      setTimeout(function () {{
        if (!window.closed && payload.status === "ok") {{
          location.replace("/?oauth=" + encodeURIComponent(payload.status));
        }}
      }}, 400);
    </script>
  </body>
</html>"""
    return HTMLResponse(html)


def _admin_gate(request: Request) -> bool:
    return request.session.get("admin_gate") == admin_store.path()


def _log(actor, action, detail='', role='admin'):
    """Record an operation; the actor is whatever name the session belonged to."""
    operation_log.record(actor, action, detail, role)


def _shift_summary(body):
    """Human-readable description of a shift payload."""
    names = body.get('members') if isinstance(body, dict) else None
    people = '、'.join(str(n) for n in names) if isinstance(names, list) else ''
    if not isinstance(body, dict):
        return ''
    return (f"{body.get('day', '')} {body.get('start', '')}–{body.get('end', '')}"
            + (f"（{people}）" if people else ''))


def _session_account(request: Request) -> str:
    """The account behind this admin session, from the signed cookie or the session."""
    name = _admin_from_cookie(request)
    if name:
        return name if permissions.is_admin(name) else ""
    if not request.session.get("admin_ok"):
        return ""
    name = str(request.session.get("admin_username") or "").strip()
    return name if name and permissions.is_admin(name) else ""


def _admin_ok(request: Request) -> bool:
    return bool(_session_account(request))


def _require_admin(request: Request) -> None:
    if not _admin_ok(request):
        raise HTTPException(status_code=401, detail="请先登录管理员")


def _require_permission(request: Request, permission: str) -> str:
    """Administrator endpoints are gated per permission group."""
    name = _session_account(request)
    if not name:
        raise HTTPException(status_code=401, detail="请先登录管理员")
    if not permissions.has(name, permission):
        raise HTTPException(status_code=403, detail="当前账号没有此权限")
    return name


def _may_manage(target: str, actor: str) -> bool:
    """Without the grant permission, an account cannot touch a privileged account.

    A plain duty account (only the user permission) is fair game; anyone holding any
    administrative permission is protected from accounts that cannot grant permissions.
    """
    if target == actor:
        return True
    if permissions.has(actor, "accounts_protected"):
        return True
    return not permissions.is_admin(target)


def _admin_username(request: Request) -> str:
    name = _admin_from_cookie(request)
    if name:
        return name
    if not _admin_ok(request):
        return ""
    name = str(request.session.get("admin_username") or "").strip()
    if name:
        return name
    names = admin_store.usernames()
    if names:
        request.session["admin_username"] = names[0]
        return names[0]
    return ""


@app.get("/api/admin/status")
async def admin_status(request: Request) -> dict[str, Any]:
    name = _session_account(request)
    return {
        "setup": admin_store.has_user(),
        "logged_in": bool(name),
        "gate": _admin_gate(request),
        "username": name or _admin_username(request) if name else "",
        "permissions": sorted(permissions.permissions_of(name)) if name else [],
        "now": system_clock.public(),
        "can_grant": bool(name and permissions.has(name, "accounts_protected")),
    }


@app.post("/api/admin/register")
async def admin_register(request: Request) -> dict[str, Any]:
    if not _admin_gate(request):
        raise HTTPException(status_code=403, detail="请从控制台提示的管理员网址进入")
    if admin_store.has_user():
        raise HTTPException(status_code=409, detail="管理员已注册，请直接登录")
    body = await request.json()
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    try:
        # The first administrator is an ordinary account granted every permission.
        member_store.create(username, password)
        permissions.set_permissions(username, permissions.ADMIN_DEFAULTS)
        admin_store.remember_setup(username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.session["admin_ok"] = True
    request.session["admin_username"] = str(body.get("username") or "").strip()
    _log(request.session["admin_username"], '创建管理员账号', '首次注册并获得全部权限')
    response = JSONResponse({"ok": True, "username": request.session["admin_username"]})
    _set_admin_cookie(response, request.session["admin_username"])
    return response


@app.post("/api/admin/login")
async def admin_login(request: Request) -> JSONResponse:
    if not _admin_gate(request):
        raise HTTPException(status_code=403, detail="请从控制台提示的管理员网址进入")
    key = "admin:" + security.client_key(request)
    if ADMIN_LIMITER.blocked(key):
        raise HTTPException(status_code=429, detail="登录尝试过于频繁，请稍后再试")
    body = await request.json()
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    version = member_store.authenticate(username, password)
    if not version:
        ADMIN_LIMITER.fail(key)
        raise HTTPException(status_code=401, detail="用户名或密码不正确")
    # Administrator pages are open to any account with at least one admin permission.
    if not permissions.is_admin(username):
        ADMIN_LIMITER.fail(key)
        raise HTTPException(status_code=403, detail="该账号没有管理员权限")
    ADMIN_LIMITER.reset(key)
    _log(username, '登录管理端')
    request.session["admin_ok"] = True
    request.session["admin_username"] = username
    response = JSONResponse({"ok": True, "username": username})
    _set_admin_cookie(response, username)
    return response


@app.post("/api/admin/logout")
async def admin_logout(request: Request) -> JSONResponse:
    _log(_admin_username(request), '退出管理端')
    request.session.pop("admin_ok", None)
    request.session.pop("admin_username", None)
    response = JSONResponse({"ok": True})
    _clear_admin_cookie(response)
    return response


@app.get("/api/admin/users")
async def admin_list_users(request: Request) -> dict[str, Any]:
    _require_admin(request)
    return {"usernames": admin_store.usernames()}


@app.post("/api/admin/users")
async def admin_add_user(request: Request) -> dict[str, Any]:
    _require_admin(request)
    body = await request.json()
    try:
        admin_store.add_user(str(body.get("username") or ""), str(body.get("password") or ""))
        _log(_admin_username(request), '新增管理员账号', str(body.get("username") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "usernames": admin_store.usernames()}


@app.patch("/api/admin/users")
async def admin_update_user(request: Request) -> dict[str, Any]:
    _require_admin(request)
    body = await request.json()
    old = str(body.get("old_username") or "").strip()
    if old and old == str(request.session.get("admin_username") or ""):
        raise HTTPException(status_code=400, detail="不能修改当前登录的管理员")
    try:
        name = admin_store.update_user(old, str(body.get("username") or ""), str(body.get("password") or ""))
        _log(_admin_username(request), '修改管理员账号', f'{old} → {name}')
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "username": name, "usernames": admin_store.usernames()}


@app.delete("/api/admin/users")
async def admin_delete_user(request: Request) -> dict[str, Any]:
    _require_admin(request)
    body = await request.json()
    name = str(body.get("username") or "").strip()
    try:
        admin_store.delete_user(name, str(request.session.get("admin_username") or ""))
        _log(_admin_username(request), '删除管理员账号', name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "usernames": admin_store.usernames()}


@app.get("/api/admin/model")
async def admin_model_get(request: Request) -> dict[str, Any]:
    _require_admin(request)
    return admin_store.model_public()


@app.post("/api/admin/model")
async def admin_model_save(request: Request) -> dict[str, Any]:
    _require_admin(request)
    body = await request.json()
    return admin_store.save_model(body)


@app.get("/api/admin/mcp")
async def admin_mcp_get(request: Request) -> dict[str, Any]:
    _require_admin(request)
    return admin_store.mcp_public()


@app.post("/api/admin/mcp")
async def admin_mcp_save(request: Request) -> dict[str, Any]:
    _require_admin(request)
    body = await request.json()
    return admin_store.save_mcp(body)


@app.post("/api/admin/oauth")
async def admin_oauth_persist(request: Request) -> dict[str, Any]:
    _require_admin(request)
    token = str(request.session.get("outline_token") or "").strip()
    refresh = str(request.session.get("outline_refresh") or "").strip()
    meta = request.session.get("oauth_meta") if isinstance(request.session.get("oauth_meta"), dict) else {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    if isinstance(body, dict):
        token = str(body.get("access_token") or token).strip()
        refresh = str(body.get("refresh_token") or refresh).strip()
    if not token:
        raise HTTPException(status_code=400, detail="尚未完成知识库登录")
    if token:
        request.session["outline_token"] = token
    if refresh:
        request.session["outline_refresh"] = refresh
    return admin_store.save_oauth(token, refresh, meta)


@app.post("/api/admin/oauth/logout")
async def admin_oauth_logout(request: Request) -> dict[str, Any]:
    _require_admin(request)
    return admin_store.clear_oauth()


@app.get("/api/admin/qq")
async def admin_qq_get(request: Request) -> dict[str, Any]:
    _require_admin(request)
    return _qq_bot().public_status()


@app.post("/api/admin/qq")
async def admin_qq_save(request: Request) -> dict[str, Any]:
    _require_admin(request)
    body = await request.json()
    admin_store.save_qq(body)
    return await _qq_bot().sync()


@app.get("/api/chats")
async def chats_get(request: Request) -> JSONResponse:
    visitor = _visitor_id(request)
    packed = chat_store.load_visitor_chats(visitor)
    return _with_visitor_cookie(request, packed, visitor)


@app.put("/api/chats")
async def chats_put(request: Request) -> JSONResponse:
    visitor = _visitor_id(request)
    body = await request.json()
    sessions = body.get("sessions") if isinstance(body.get("sessions"), list) else []
    chat_store.save_visitor_chats(visitor, sessions, str(body.get("currentId") or ""))
    return _with_visitor_cookie(request, {"ok": True}, visitor)


@app.get("/api/admin/chats")
async def admin_chats_list(request: Request) -> dict[str, Any]:
    _require_admin(request)
    return {"items": chat_store.list_all(), **chat_store.stats()}


@app.post("/api/admin/chats/cache")
async def admin_chats_cache(request: Request) -> dict[str, Any]:
    _require_admin(request)
    body = await request.json()
    try:
        max_mb = int(body.get("max_mb"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="请填写有效的缓存大小") from None
    stats = chat_store.set_max_mb(max_mb)
    return {"ok": True, "items": chat_store.list_all(), **stats}


@app.get("/api/admin/chats/{visitor_id}/{chat_id}")
async def admin_chats_detail(request: Request, visitor_id: str, chat_id: str) -> dict[str, Any]:
    _require_admin(request)
    rec = chat_store.get_session(visitor_id, chat_id)
    if not rec:
        raise HTTPException(status_code=404, detail="对话不存在")
    return rec


def _schedule_error(exc):
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc) or "排班数据格式不正确")


@app.get("/api/admin/logs")
async def admin_logs(request: Request, limit: int = 300, actor: str = "", q: str = ""):
    _require_admin(request)
    limit = max(1, min(int(limit or 300), 1000))
    return {"items": operation_log.list_entries(limit, actor.strip(), q.strip()),
            "actors": operation_log.actors()}


@app.get("/api/admin/anomalies")
async def admin_anomalies(request: Request, weeks: int = 2):
    _require_admin(request)
    return overview.anomaly_stats(weeks)


@app.get("/api/admin/overview")
async def admin_overview(request: Request, month: str = "", week: str = ""):
    _require_permission(request, "schedule")
    try:
        return overview.overview(month or None, week=week.strip() or None)
    except ValueError as exc:
        raise _schedule_error(exc) from exc


@app.get("/api/schedules")
async def schedules_get(request: Request, day: str):
    name = None if _admin_ok(request) else _require_member(request)
    try:
        return {
            "items": schedule_store.list_day(day, name),
            "rules": duty_settings.load() if name is not None else None,
            "now": system_clock.public(),
        }
    except ValueError as exc:
        raise _schedule_error(exc) from exc


@app.get("/api/special-schedules")
async def special_schedules_get(request: Request, from_day: str = ""):
    name = None if _admin_ok(request) else _require_member(request)
    try:
        return {"items": schedule_store.list_special(from_day or None, name)}
    except ValueError as exc:
        raise _schedule_error(exc) from exc


@app.get("/api/admin/clock")
async def admin_clock_get(request: Request):
    _require_permission(request, "schedule")
    return system_clock.public()


@app.put("/api/admin/clock")
async def admin_clock_save(request: Request):
    _require_permission(request, "schedule")
    body = await request.json()
    try:
        state = system_clock.save(
            automatic=body.get("automatic") is not False,
            hour=body.get("hour", 0), minute=body.get("minute", 0),
            day=str(body.get("date") or "") or None)
        _log(_admin_username(request), '修改系统时间',
             '自动设置' if state['automatic'] else f"{state['date']} {state['hour']:02d}:{state['minute']:02d}")
        return state
    except (TypeError, ValueError) as exc:
        raise _schedule_error(exc) from exc


@app.get("/api/admin/rules")
async def admin_rules_get(request: Request):
    _require_permission(request, "schedule")
    return duty_settings.load()


@app.put("/api/admin/rules")
async def admin_rules_save(request: Request):
    _require_permission(request, "schedule")
    try:
        rules = duty_settings.save(await request.json())
        _log(_admin_username(request), '修改值班时间设置',
             f"提前 {rules['early_minutes']} 分 / 迟到 {rules['late_minutes']} 分 / 旷班 {rules['absent_minutes']} 分")
        return rules
    except (ValueError, TypeError) as exc:
        raise _schedule_error(exc) from exc


@app.post("/api/schedules/{shift_id}/check-in")
async def schedule_check_in(shift_id: int, request: Request):
    name = _require_member(request)
    try:
        stamp, chained = schedule_store.check_in_with_chain(shift_id, name)
        _log(name, '到岗签到',
             f"班次 #{shift_id}" + (f"，并自动签到 {len(chained)} 个连班" if chained else ''),
             role='member')
        return {"checked_at": stamp, "chained": chained}
    except (ValueError, LookupError) as exc:
        raise _schedule_error(exc) from exc


@app.get("/api/admin/attendance-history")
async def admin_attendance_history(request: Request):
    _require_permission(request, "schedule")
    return {"items": schedule_store.history()}


@app.delete("/api/admin/schedules")
async def schedules_clear(request: Request):
    _require_permission(request, "schedule")
    result = schedule_store.clear_all()
    _log(_admin_username(request), '清除所有排班',
         f"删除 {result['deleted']} 个班次，归档 {result.get('archived', 0)} 条打卡")
    return result


@app.post("/api/admin/schedules")
async def schedule_create(request: Request):
    _require_permission(request, "schedule")
    try:
        body = await request.json()
        shift_id = schedule_store.save(body)
        _log(_admin_username(request), '新增班次', _shift_summary(body))
        return {"id": shift_id}
    except (ValueError, TypeError, LookupError) as exc:
        raise _schedule_error(exc) from exc


@app.post("/api/admin/special-schedules")
async def special_schedule_create(request: Request):
    _require_permission(request, "schedule")
    body = await request.json()
    try:
        shift_id = schedule_store.save({**body, "special": True})
        _log(_admin_username(request), '新增特殊排班', _shift_summary(body))
        return {"id": shift_id}
    except (ValueError, TypeError, LookupError) as exc:
        raise _schedule_error(exc) from exc


@app.put("/api/admin/special-schedules/{shift_id}")
async def special_schedule_update(shift_id: int, request: Request):
    _require_permission(request, "schedule")
    body = await request.json()
    try:
        schedule_store.save({**body, "special": True}, shift_id)
        _log(_admin_username(request), '修改特殊排班', f'#{shift_id} {_shift_summary(body)}')
        return {"id": shift_id}
    except (ValueError, TypeError, LookupError) as exc:
        raise _schedule_error(exc) from exc


@app.delete("/api/admin/special-schedules/{shift_id}")
async def special_schedule_delete(shift_id: int, request: Request):
    _require_permission(request, "schedule")
    try:
        schedule_store.delete(shift_id)
        _log(_admin_username(request), '删除特殊排班', f'#{shift_id}')
        return {"ok": True}
    except LookupError as exc:
        raise _schedule_error(exc) from exc


@app.put("/api/admin/schedules/{shift_id}")
async def schedule_update(shift_id: int, request: Request):
    _require_permission(request, "schedule")
    try:
        body = await request.json()
        schedule_store.save(body, shift_id)
        _log(_admin_username(request), '修改班次', f'#{shift_id} {_shift_summary(body)}')
        return {"id": shift_id}
    except (ValueError, TypeError, LookupError) as exc:
        raise _schedule_error(exc) from exc


@app.delete("/api/admin/schedules/{shift_id}")
async def schedule_delete(shift_id: int, request: Request):
    _require_permission(request, "schedule")
    try:
        schedule_store.delete(shift_id)
        _log(_admin_username(request), '删除班次', f'#{shift_id}')
        return {"ok": True}
    except LookupError as exc:
        raise _schedule_error(exc) from exc


@app.get("/api/admin/weekly-roster")
async def weekly_get(request: Request):
    _require_permission(request, "schedule")
    return weekly_store.load()


@app.put("/api/admin/weekly-roster")
async def weekly_save(request: Request):
    _require_permission(request, "schedule")
    try:
        roster = weekly_store.save(await request.json())
        _log(_admin_username(request), '保存每周排班模板',
             f"{len(roster.get('slots') or [])} 个班次")
        # Only after the reviewed roster is stored do we create missing duty accounts.
        created = member_store.create_missing(
            {name for slot in roster['slots'] for names in slot['days'] for name in names})
        return {**roster, "members_created": created['created']}
    except (ValueError, TypeError) as exc:
        raise _schedule_error(exc) from exc


@app.post("/api/admin/weekly-roster/publish")
async def weekly_publish(request: Request):
    _require_permission(request, "schedule")
    try:
        body = await request.json()
        result = weekly_store.publish_until(
            str(body.get("end_date") or ""), str(body.get("start_date") or "") or None)
        _log(_admin_username(request), '生成排班',
             f"{body.get('start_date') or '今天'} 至 {body.get('end_date') or ''}："
             f"新增/覆盖 {result['created']} 个，跳过 {result['skipped']} 个")
        return result
    except (ValueError, TypeError) as exc:
        raise _schedule_error(exc) from exc


def _require_member(request: Request) -> str:
    name = str(request.session.get("member_username") or "")
    if not name or not member_store.session_valid(name, request.session.get("member_version")):
        raise HTTPException(status_code=401, detail="请先登录值班账号")
    return name


@app.get("/api/member/status")
async def member_status(request: Request):
    clock = system_clock.public()
    try:
        return {"logged_in": True, "username": _require_member(request), "now": clock}
    except HTTPException:
        return {"logged_in": False, "username": "", "now": clock}


@app.post("/api/member/login")
async def member_login(request: Request):
    key = "member:" + security.client_key(request)
    if MEMBER_LIMITER.blocked(key):
        raise HTTPException(status_code=429, detail="登录尝试过于频繁，请稍后再试")
    body = await request.json()
    name = str(body.get("username") or "").strip()
    version = member_store.authenticate(name, str(body.get("password") or ""))
    if not version:
        MEMBER_LIMITER.fail(key)
        raise HTTPException(status_code=401, detail="姓名或密码不正确，或账号已停用")
    MEMBER_LIMITER.reset(key)
    _log(name, '登录值班账号', role='member')
    request.session["member_username"] = name
    request.session["member_version"] = version
    return {"ok": True, "username": name}


@app.get("/api/member/field-duty")
async def member_field_duty(request: Request):
    name = _require_member(request)
    return field_duty.member_status(name)


@app.get("/api/member/field-duty/pending")
async def member_field_pending(request: Request):
    _require_member(request)
    return field_duty.pending()


@app.post("/api/member/field-duty/pending/{username}")
async def member_field_confirm(username: str, request: Request):
    _require_member(request)
    try:
        result = field_duty.confirm(username.strip())
        _log(_require_member(request), '确认外勤', username.strip(), role='member')
        return result
    except LookupError as exc:
        raise _schedule_error(exc) from exc


@app.delete("/api/member/field-duty/pending/{username}")
async def member_field_reject(username: str, request: Request):
    name = _require_member(request)
    result = field_duty.set_participation(username.strip(), False)
    _log(name, '删除外勤登记', username.strip(), role='member')
    return result


@app.post("/api/member/field-duty")
async def member_field_duty_register(request: Request):
    name = _require_member(request)
    result = field_duty.register(name)
    _log(name, '登记外勤', result.get('label', ''), role='member')
    return result


@app.put("/api/admin/overview/attendance")
async def admin_set_attendance(request: Request):
    _require_permission(request, "schedule")
    body = await request.json()
    try:
        shift_id = int(body.get("shift_id"))
        name = str(body.get("name") or "").strip()
        result = overview.set_member_status(shift_id, name, str(body.get("status") or ""))
        _log(_admin_username(request), '更改考勤状态',
             f"{name} 班次 #{shift_id} → {result['status']}")
        return result
    except (TypeError, ValueError) as exc:
        raise _schedule_error(exc) from exc
    except LookupError as exc:
        raise _schedule_error(exc) from exc


@app.put("/api/admin/field-duty")
async def admin_set_field_duty(request: Request):
    _require_permission(request, "field")
    body = await request.json()
    try:
        result = field_duty.set_participation(
            str(body.get("username") or "").strip(), bool(body.get("registered")),
            str(body.get("month") or "") or None)
        _log(_admin_username(request), '更改外勤状态',
             f"{result['username']} {result['month']} → {'已参加' if result['registered'] else '未参加'}")
        return result
    except (TypeError, ValueError) as exc:
        raise _schedule_error(exc) from exc


@app.get("/api/admin/swaps")
async def admin_swaps(request: Request):
    _require_permission(request, "schedule")
    return {"items": swap_store.list_swaps()}


@app.get("/api/admin/swaps/candidates")
async def admin_swap_candidates(request: Request, username: str = "", shift_id: int = 0):
    _require_permission(request, "schedule")
    name = username.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请先选择人员")
    return {"items": swap_store.candidates(name, shift_id or None)}


@app.post("/api/admin/swaps")
async def admin_swap_create(request: Request):
    _require_permission(request, "schedule")
    body = await request.json()
    try:
        swap_id = swap_store.create(
            int(body.get("shift_a")), str(body.get("name_a") or "").strip(),
            int(body.get("shift_b")), str(body.get("name_b") or "").strip(),
            confirmed=body.get("confirmed") is True)
        _log(_admin_username(request), '新增调班',
             f"{body.get('name_a')} 与 {body.get('name_b')} 互换班次")
    except (TypeError, ValueError, LookupError) as exc:
        raise _schedule_error(exc) from exc
    return {"id": swap_id}


@app.delete("/api/admin/swaps/{swap_id}")
async def admin_swap_delete(swap_id: int, request: Request):
    _require_permission(request, "schedule")
    try:
        swap_store.delete(swap_id)
        _log(_admin_username(request), '删除调班', f'#{swap_id}')
    except (ValueError, LookupError) as exc:
        raise _schedule_error(exc) from exc
    return {"ok": True}


@app.get("/api/admin/field-duty")
async def admin_field_duty(request: Request, month: str = ""):
    _require_permission(request, "field")
    try:
        return field_duty.overview(month or None)
    except ValueError as exc:
        raise _schedule_error(exc) from exc


@app.post("/api/member/logout")
async def member_logout(request: Request):
    request.session.pop("member_username", None)
    request.session.pop("member_version", None)
    return {"ok": True}


@app.post("/api/member/password")
async def member_password(request: Request):
    name = _require_member(request)
    body = await request.json()
    try:
        member_store.change_password(name, str(body.get("old_password") or ""), str(body.get("new_password") or ""))
        _log(name, '修改个人密码', role='member')
    except ValueError as exc:
        raise _schedule_error(exc) from exc
    request.session["member_version"] = member_store.session_version(name)
    return {"ok": True}


@app.get("/api/admin/members")
async def admin_members(request: Request):
    actor = _require_permission(request, "accounts")
    return {
        "items": member_store.list_accounts(),
        "permissions": [{"id": key, "label": label, "hint": hint}
                        for key, (label, hint) in permissions.PERMISSIONS.items()],
        "tree": permissions.TREE,
        "groups": list(permissions.GROUP_IDS),
        "me": actor,
        "can_grant": permissions.has(actor, "accounts_protected"),
    }


@app.put("/api/admin/members/permissions")
async def admin_member_permissions(request: Request):
    actor = _require_permission(request, "accounts")
    body = await request.json()
    name = str(body.get("username") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请指定账号")
    if not permissions.has(actor, "accounts_protected"):
        raise HTTPException(status_code=403, detail="当前账号没有更改权限的资格")
    try:
        perms = permissions.set_permissions(name, body.get("permissions") or [])
        _log(_admin_username(request), '更改权限', f"{name} → {'、'.join(sorted(perms)) or '无权限'}")
    except LookupError as exc:
        raise _schedule_error(exc) from exc
    return {"ok": True, "username": name, "permissions": sorted(perms)}


@app.put("/api/admin/members/password")
async def admin_member_password(request: Request):
    actor = _require_permission(request, "accounts")
    body = await request.json()
    name = str(body.get("username") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请指定账号")
    # Only the account itself or a holder of "更改权限" may set a password.
    if name != actor and not permissions.has(actor, "accounts_protected"):
        raise HTTPException(status_code=403, detail="仅账号本人或拥有“更改权限”者可以更改密码")
    try:
        member_store.set_password(name, str(body.get("password") or ""))
        _log(_admin_username(request), '更改账号密码', name)
    except (ValueError, LookupError) as exc:
        raise _schedule_error(exc) from exc
    return {"ok": True}


@app.post("/api/admin/members/provision")
async def admin_provision_members(request: Request):
    _require_permission(request, "accounts")
    result = member_store.provision()
    _log(_admin_username(request), '补齐排班人员账号',
         f"新建 {result['created']} 个，已存在 {result['existing']} 个")
    return result


@app.post("/api/admin/members")
async def admin_add_member(request: Request):
    _require_permission(request, "accounts_manage")
    body = await request.json()
    try:
        result = member_store.create(body.get("username"))
        _log(_admin_username(request), '添加账号', str(body.get("username") or ""))
        return result
    except ValueError as exc:
        raise _schedule_error(exc) from exc


@app.delete("/api/admin/members")
async def admin_delete_member(request: Request, username: str = ""):
    actor = _require_permission(request, "accounts_manage")
    name = username.strip()
    if not name:
        try:
            name = str((await request.json()).get("username") or "").strip()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="请指定要删除的账号") from exc
    if not _may_manage(name, actor):
        raise HTTPException(status_code=403, detail="该账号拥有权限，需具备更改权限的资格才能删除")
    try:
        member_store.delete(name)
        _log(_admin_username(request), '删除账号', name)
    except (ValueError, LookupError) as exc:
        raise _schedule_error(exc) from exc
    return {"ok": True}


@app.patch("/api/admin/members")
async def admin_update_member(request: Request):
    actor = _require_permission(request, "accounts")
    body = await request.json()
    if "active" in body and not isinstance(body["active"], bool):
        raise HTTPException(status_code=400, detail="账号状态格式错误")
    target = str(body.get("username") or "").strip()
    # Changing state or resetting a password of a privileged account needs the grant right.
    if not _may_manage(target, actor):
        raise HTTPException(status_code=403, detail="该账号拥有权限，需具备更改权限的资格才能操作")
    try:
        target = str(body.get("username") or "")
        member_store.update(target, body.get("active"), body.get("reset_password") is True)
        changes = []
        if "active" in body:
            changes.append('启用' if body.get("active") else '停用')
        if body.get("reset_password") is True:
            changes.append('重置密码')
        _log(_admin_username(request), '修改账号', f"{target}：{'、'.join(changes) or '无变化'}")
    except ValueError as exc:
        raise _schedule_error(exc) from exc
    return {"ok": True}


@app.get("/{slug}")
async def admin_page(slug: str, request: Request):
    if len(slug) != 8 or slug != admin_store.path():
        raise HTTPException(status_code=404, detail="页面不存在")
    request.session["admin_gate"] = slug
    return FileResponse(
        WEB / "admin.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
