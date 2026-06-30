#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gateway_proxy.py — 企业网关代理（OpenAI API ↔ 企业内网网关格式转换）

将标准 OpenAI API 请求（/v1/chat/completions 等）转换为企业内网网关格式
（txHeader + txBody.txEntity），并将网关响应转换回 OpenAI 格式。

使用方式：
  1. 独立运行：python gateway_proxy.py
  2. 集成启动：由 main.py 自动启动（config.yaml 配置 gateway.enabled: true）

配置来源：
  - 优先读取 config.yaml 中 llm.enterprise_internal.gateway 段
  - 未配置时使用代码内默认值
"""

import json
import logging
import random
from datetime import datetime

import requests as _requests
from flask import Flask, Response, jsonify, request, stream_with_context

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("gateway_proxy")


# ═══════════════════════════════════════════════════════════════
#  默认配置（可通过 config.yaml 覆盖）
# ═══════════════════════════════════════════════════════════════

DEFAULT_PROXY_PORT = 8081
DEFAULT_GATEWAY_URL = "http://20.12.37.190:8080"
DEFAULT_ENDPOINTS = {
    "chat": "/ai",
    "completion": "/ai",
    "embedding": "/ai",
    "rerank": "/ai",
}

DEFAULT_TX_HEADER = {
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


# ═══════════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════════

def _build_tx_header(tx_type: str, template: dict = None) -> dict:
    header = dict(template or DEFAULT_TX_HEADER)
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d%H%M%S%f")[:17]
    track_no = (
        header.get("sendSysOrCmptNo", "")
        + timestamp
        + "".join(str(random.randint(0, 9)) for _ in range(6))
    )
    header.update({
        "txStartTime": timestamp,
        "txSendTime": timestamp,
        "servNo": tx_type,
        "globalBusiTrackNo": track_no,
    })
    return header


def _is_vision_request(messages: list) -> bool:
    if not isinstance(messages, list):
        return False
    for msg in messages:
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") in (
                    "image_url", "image_base64", "image",
                ):
                    return True
    return False


def _to_gateway_format(openai_body: dict, tx_type: str, header_template: dict = None) -> dict:
    return {
        "txHeader": _build_tx_header(tx_type, header_template),
        "txBody": {"txComin": "", "txEntity": openai_body},
    }


def _from_gateway_format(gateway_response: dict) -> dict:
    tx_body = gateway_response.get("txBody", {})
    return tx_body.get("txEntity", gateway_response)


def _parse_stream_line(line: str) -> str | None:
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


# ═══════════════════════════════════════════════════════════════
#  Flask 应用工厂
# ═══════════════════════════════════════════════════════════════

def create_proxy_app(
    gateway_url: str = None,
    endpoints: dict = None,
    tx_header_template: dict = None,
) -> Flask:
    """创建网关代理 Flask 应用。"""
    gw_url = (gateway_url or DEFAULT_GATEWAY_URL).rstrip("/")
    eps = endpoints or DEFAULT_ENDPOINTS
    header_tmpl = tx_header_template or DEFAULT_TX_HEADER

    http_session = _requests.Session()
    http_session.timeout = 300

    app = Flask(__name__)

    def _stream_forward(url: str, payload: dict, headers: dict):
        try:
            with http_session.post(url, json=payload, headers=headers, stream=True) as resp:
                for line in resp.iter_lines(decode_unicode=True):
                    if line:
                        sse_data = _parse_stream_line(line)
                        if sse_data:
                            yield sse_data.encode("utf-8")
        except Exception as e:
            yield (
                f'data: {{"error":{{"message":"{e}","type":"gateway_error"}}}}\n\n'
            ).encode("utf-8")
            yield b"data: [DONE]\n\n"

    def _handle_gateway(tx_type: str, endpoint_key: str = "chat"):
        body = request.get_json(silent=True)
        if body is None:
            return jsonify({"error": {"message": "Invalid JSON body"}}), 400

        if endpoint_key == "chat":
            tx_type = "390202" if _is_vision_request(body.get("messages", [])) else "390201"

        gateway_payload = _to_gateway_format(body, tx_type, header_tmpl)
        url = gw_url + eps.get(endpoint_key, "/ai")

        headers = {}
        auth = request.headers.get("Authorization")
        if auth:
            headers["Authorization"] = auth

        model = body.get("model", "unknown")
        is_stream = body.get("stream", False)
        logger.info("请求 | 端点: %s | 模型: %s | 流式: %s", endpoint_key, model, is_stream)

        if is_stream:
            return Response(
                stream_with_context(_stream_forward(url, gateway_payload, headers)),
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        resp = http_session.post(url, json=gateway_payload, headers=headers, timeout=300)
        logger.info("网关响应 | 状态码: %s", resp.status_code)

        if resp.status_code >= 400:
            logger.error("网关错误 | %s | %s", resp.status_code, resp.text[:500])
            return jsonify(
                {"error": {"message": resp.text[:500], "type": "gateway_error"}}
            ), resp.status_code

        result = _from_gateway_format(resp.json())
        return jsonify(result)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "gateway": gw_url})

    @app.route("/v1/models", methods=["GET"])
    def list_models():
        return jsonify({"data": [], "object": "list"})

    @app.route("/v1/chat/completions", methods=["POST"])
    def chat_completions():
        return _handle_gateway(tx_type="", endpoint_key="chat")

    @app.route("/v1/completions", methods=["POST"])
    def completions():
        return _handle_gateway(tx_type="390201", endpoint_key="completion")

    @app.route("/v1/embeddings", methods=["POST"])
    def embeddings():
        return _handle_gateway(tx_type="390203", endpoint_key="embedding")

    @app.route("/v1/rerank", methods=["POST"])
    def rerank():
        return _handle_gateway(tx_type="390204", endpoint_key="rerank")

    return app


# ═══════════════════════════════════════════════════════════════
#  集成启动（由 main.py 调用）
# ═══════════════════════════════════════════════════════════════

_proxy_thread = None


def start_proxy_background(gateway_cfg: dict, port: int = None) -> int | None:
    """在后台线程启动网关代理，返回监听端口。

    Args:
        gateway_cfg: config.yaml 中 llm.enterprise_internal.gateway 段
        port: 代理端口（默认从 gateway_cfg 读取或 8081）

    Returns:
        实际监听端口，启动失败返回 None
    """
    import socket
    import threading

    global _proxy_thread

    if _proxy_thread and _proxy_thread.is_alive():
        logger.info("网关代理已在运行")
        return None

    proxy_port = port or gateway_cfg.get("proxy_port", DEFAULT_PROXY_PORT)
    gateway_url = gateway_cfg.get("gateway_url", DEFAULT_GATEWAY_URL)

    tx_header = dict(DEFAULT_TX_HEADER)
    if gateway_cfg.get("tx_header"):
        tx_header.update(gateway_cfg["tx_header"])

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", proxy_port)) == 0:
                logger.info("端口 %d 已被占用，跳过代理启动（可能已在运行）", proxy_port)
                return proxy_port
    except Exception:
        pass

    app = create_proxy_app(
        gateway_url=gateway_url,
        tx_header_template=tx_header,
    )

    def _run():
        import werkzeug.serving
        werkzeug.serving.run_simple(
            "127.0.0.1", proxy_port, app,
            use_reloader=False, use_debugger=False, threaded=True,
        )

    _proxy_thread = threading.Thread(target=_run, daemon=True, name="gateway-proxy")
    _proxy_thread.start()

    logger.info("网关代理已启动 | 端口: %d | 网关: %s", proxy_port, gateway_url)
    return proxy_port


# ═══════════════════════════════════════════════════════════════
#  独立运行入口
# ═══════════════════════════════════════════════════════════════

def _load_config_for_standalone() -> dict:
    """独立运行时从 config.yaml 读取网关配置。"""
    from pathlib import Path
    try:
        import yaml
        cfg_path = Path(__file__).parent / "config.yaml"
        if not cfg_path.exists():
            cfg_path = Path(__file__).parent / "config.example.yaml"
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("llm", {}).get("enterprise_internal", {}).get("gateway", {})
    except Exception:
        return {}


if __name__ == "__main__":
    gw_cfg = _load_config_for_standalone()
    proxy_port = gw_cfg.get("proxy_port", DEFAULT_PROXY_PORT)
    gateway_url = gw_cfg.get("gateway_url", DEFAULT_GATEWAY_URL)

    tx_header = dict(DEFAULT_TX_HEADER)
    if gw_cfg.get("tx_header"):
        tx_header.update(gw_cfg["tx_header"])

    print(f"{'=' * 50}")
    print(f"OpenAI Gateway Proxy")
    print(f"监听: http://127.0.0.1:{proxy_port}")
    print(f"网关: {gateway_url}")
    print(f"{'=' * 50}")

    app = create_proxy_app(
        gateway_url=gateway_url,
        tx_header_template=tx_header,
    )
    app.run(host="0.0.0.0", port=proxy_port, threaded=True)
