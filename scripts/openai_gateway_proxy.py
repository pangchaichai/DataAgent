#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAI ↔ 企业内网网关 代理程序 (FastAPI 实现)

支持: Chat/Completion/Embedding/Rerank
支持: 流式(Streaming) 和 非流式(Non-streaming)

── 配置说明 ──────────────────────────────────────────────────────
1. 修改下方 "用户配置区" 中的变量（尤其是 APP_CODE）
2. 启动: uvicorn openai_gateway_proxy:app --host 0.0.0.0 --port 8081
   或:    python openai_gateway_proxy.py
3. 在 DataAgent config.yaml 中配置:
     enterprise_internal:
       url: http://localhost:8081/v1
       model: <你的模型名>
       api_key: ""          # 留空即可，代理统一鉴权
       auth_type: none      # 告知 DataAgent 不发送 Authorization 头
──────────────────────────────────────────────────────────────────
"""

import json
import random
from collections.abc import AsyncGenerator
from datetime import datetime
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse, JSONResponse


# ==================== ★ 用户配置区（必须修改） ====================

PROXY_HOST = "0.0.0.0"
PROXY_PORT = 8081
GATEWAY_BASE_URL = "http://20.12.37.190:8080"    # 企业网关地址
ENDPOINTS = {"chat": "/ai", "completion": "/ai", "embedding": "/ai", "rerank": "/ai"}

# ★ 企业网关鉴权（从管理员处获取，填写后代理统一鉴权，DataAgent 不需要配置 api_key）
APP_CODE = ""    # 应用标识 appCode（必填，留空则认证会失败）
APP_SECRET = ""  # 应用密钥 appSecret（如需要，留空则不发送）

# 暴露给 DataAgent /v1/models 端点的默认模型名（与 config.yaml model 字段一致）
DEFAULT_MODEL = "Qwen25-72B-1-test"

# ==================== 网关报文头模板 ====================

TX_HEADER_TEMPLATE = {
    "startSysOrCmptNo": "99710970039",
    "sendSysOrCmptNo": "99710970039",
    "startChnlfgCd": "99",
    "busiSendInstNo": "11005293",
    "dataCenterCode": "H",
    "msgrptTotalLen": "999",
    "msgrptfmtVerNo": "10000",
    "msgAgrType": "1",
    "pubMsgHeadLen": "999",
    "embedMsgrptLen": "999",
    "targetSysOrCmptNo": "99710970044",
    "servTpCd": "1",
    "servVerNo": "10000",
    "msgrptMac": "mac",
    "subTxSeqNo": "",
    "mainMapElementInfo": "",
    "reqSysSriNo": "",
    "servGrayscLabelNo": "",
    "resvedInputInfo": "",
}


# ==================== 工具函数 ====================

def build_tx_header(tx_type: str) -> dict:
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d%H%M%S%f")[:17]
    track_no = (TX_HEADER_TEMPLATE["sendSysOrCmptNo"] + timestamp
                + "".join(str(random.randint(0, 9)) for _ in range(6)))
    return {**TX_HEADER_TEMPLATE, "txStartTime": timestamp, "txSendTime": timestamp,
            "servNo": tx_type, "globalBusiTrackNo": track_no}


def is_vision_request(messages: list) -> bool:
    if not isinstance(messages, list):
        return False
    for msg in messages:
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") in ("image_url", "image_base64", "image"):
                    return True
        elif isinstance(content, str) and any(
            p in content.lower() for p in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", "image_url")
        ):
            return True
    return False


def to_gateway_format(openai_body: dict, tx_type: str) -> dict:
    return {"txHeader": build_tx_header(tx_type), "txBody": {"txComin": "", "txEntity": openai_body}}


def from_gateway_format(gateway_response: dict) -> dict:
    tx_body = gateway_response.get("txBody", {})
    return tx_body.get("txEntity", gateway_response)


def _build_gateway_headers(forwarded_auth: str | None = None) -> dict:
    """
    构建发往企业网关的认证头。

    优先使用本地配置的 APP_CODE；若未配置，则透传调用方的 Authorization。
    """
    headers = {}
    if APP_CODE:
        # APIC 应用鉴权：X-IBM-Client-Id + X-IBM-Client-Secret
        headers["X-IBM-Client-Id"] = APP_CODE
        if APP_SECRET:
            headers["X-IBM-Client-Secret"] = APP_SECRET
    elif forwarded_auth:
        headers["Authorization"] = forwarded_auth
    return headers


def _is_gateway_auth_error(response_json: dict) -> bool:
    """判断网关响应是否为认证失败（APIC.0303 等）"""
    msg = response_json.get("message", "")
    res_code = response_json.get("resCode", "") or response_json.get("servRespCd", "")
    return (
        "appCode" in msg
        or "APIC.0303" in msg
        or "app authentication" in msg
        or res_code.startswith("X99LG001ATF")
    )


def parse_gateway_stream_line(line: str) -> str | None:
    """将网关流式响应一行转换为 SSE 格式"""
    try:
        if line.startswith("data:"):
            line = line[5:]
        chunk = json.loads(line)
    except json.JSONDecodeError:
        return f"data: {line}\n\n" if not line.startswith("data:") else f"{line}\n\n"

    if chunk.get("txHeader", {}).get("messageType") == "heartbeat":
        return None

    entity = chunk.get("txBody", {}).get("txEntity")
    return None if entity is None else f"data: {json.dumps(entity, ensure_ascii=False)}\n\n"


# ==================== FastAPI App ====================

client = httpx.AsyncClient(timeout=300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    auth_status = f"APP_CODE={'已配置' if APP_CODE else '★ 未配置（认证会失败）'}"
    print(f"\n{'=' * 55}")
    print(f"OpenAI Gateway Proxy (FastAPI)")
    print(f"监听地址: http://{PROXY_HOST}:{PROXY_PORT}")
    print(f"网关地址: {GATEWAY_BASE_URL}")
    print(f"认证状态: {auth_status}")
    print(f"{'=' * 55}")
    print("可用端点:")
    print("  GET  /v1/models            - 模型列表（静态）")
    print("  POST /v1/chat/completions  - LLM/VL 对话")
    print("  POST /v1/completions       - Legacy Completion")
    print("  POST /v1/embeddings        - 文本嵌入")
    print("  POST /v1/rerank            - 重排序")
    print("  GET  /health               - 健康检查")
    if not APP_CODE:
        print("\n⚠️  APP_CODE 未配置！请编辑本文件顶部的配置区，填写企业网关 appCode。")
    print(f"{'=' * 55}\n")
    yield
    await client.aclose()


app = FastAPI(title="OpenAI Gateway Proxy", lifespan=lifespan)


async def stream_forward(gateway_url: str, payload: dict, headers: dict) -> AsyncGenerator[bytes, None]:
    """将网关流式响应转发为 SSE 流"""
    try:
        async with client.stream("POST", gateway_url, json=payload, headers=headers) as resp:
            async for line in resp.aiter_lines():
                if line:
                    sse_data = parse_gateway_stream_line(line)
                    if sse_data:
                        yield sse_data.encode("utf-8")
    except Exception as e:
        yield f'data: {{"error":{{"message":"{e}","type":"gateway_error","code":"internal_error"}}}}\n\n'.encode("utf-8")
        yield b"data: [DONE]\n\n"


async def handle_gateway(req: Request, tx_type: str, endpoint_key: str = "chat") -> Response:
    body = await req.json()

    if endpoint_key == "chat":
        tx_type = "390202" if is_vision_request(body.get("messages", [])) else "390201"

    gateway_payload = to_gateway_format(body, tx_type)
    gateway_url = GATEWAY_BASE_URL + ENDPOINTS[endpoint_key]
    forwarded_auth = req.headers.get("Authorization")
    headers = _build_gateway_headers(forwarded_auth)

    if body.get("stream", False):
        return StreamingResponse(
            stream_forward(gateway_url, gateway_payload, headers),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    resp = await client.post(gateway_url, json=gateway_payload, headers=headers)
    if resp.status_code >= 400:
        return JSONResponse(
            {"error": {"message": str(resp.text), "type": "gateway_error", "code": "upstream_error"}},
            status_code=resp.status_code,
        )

    raw = resp.json()
    openai_body = from_gateway_format(raw)

    # 检测网关认证/业务错误，返回 4xx 而非 200（避免 DataAgent 把错误响应当成格式异常）
    if _is_gateway_auth_error(openai_body):
        msg = openai_body.get("message", "")
        res_code = openai_body.get("resCode", "")
        return JSONResponse(
            {"error": {"message": f"企业网关认证失败（{res_code}）：{msg}", "type": "auth_error", "code": "gateway_auth"}},
            status_code=401,
        )
    if "resCode" in openai_body and "choices" not in openai_body:
        msg = openai_body.get("message") or openai_body.get("servRespDescInfo", "网关返回错误")
        res_code = openai_body.get("resCode", "")
        return JSONResponse(
            {"error": {"message": f"网关错误（{res_code}）：{msg}", "type": "gateway_error", "code": "upstream_error"}},
            status_code=502,
        )

    return JSONResponse(openai_body)


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat(), "app_code_configured": bool(APP_CODE)}


@app.get("/v1/models")
async def list_models():
    """返回静态模型列表，供 DataAgent test_connection() 使用"""
    return {
        "object": "list",
        "data": [{"id": DEFAULT_MODEL, "object": "model", "created": 0, "owned_by": "enterprise"}],
    }


@app.post("/v1/chat/completions")
async def chat_completions(req: Request):
    return await handle_gateway(req, tx_type="", endpoint_key="chat")


@app.post("/v1/completions")
async def completions(req: Request):
    return await handle_gateway(req, tx_type="390201", endpoint_key="completion")


@app.post("/v1/embeddings")
async def embeddings(req: Request):
    return await handle_gateway(req, tx_type="390203", endpoint_key="embedding")


@app.post("/v1/rerank")
async def rerank(req: Request):
    return await handle_gateway(req, tx_type="390204", endpoint_key="rerank")


# ==================== 启动入口 ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=PROXY_HOST, port=PROXY_PORT)
