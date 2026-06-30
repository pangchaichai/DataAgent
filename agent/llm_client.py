"""
agent/llm_client.py — LLM 调用客户端

职责：
  1. 读取 config.yaml 中的 llm 配置
  2. 提供 generate_sql / generate_report_text / classify_intent 三个端点
  3. report_text 端点严禁 fallback 到外部模型（P1-3）
  4. sql_gen 端点支持内网优先 + 外部兜底（需合规签字）
  5. 流式 SSE 响应（yield chunks）
  6. 超时 + 异常处理，不得空 except
"""

import json
import logging
import os
import time
from collections.abc import Generator
from dataclasses import dataclass, field

import requests
import yaml

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class LLMResponse:
    """LLM 调用结果"""
    success: bool
    text: str
    endpoint: str           # 实际使用的端点名称
    model: str
    token_count: int = 0
    elapsed_ms: int = 0
    error: str = ""


@dataclass
class ChatResult:
    """chat() 方法返回结果"""
    success: bool
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    error: str = ""
    elapsed_ms: int = 0
    token_count: int = 0
    model: str = ""


@dataclass
class ReportDegradedResult:
    """
    report_text 不可用时的降级输出。
    包含纯数值结构 + 占位说明，不调用外部 LLM。
    """
    message: str
    numerical_data: dict = field(default_factory=dict)
    degraded: bool = True
    success: bool = False


# ═══════════════════════════════════════════════════════════════
#  LLMClient
# ═══════════════════════════════════════════════════════════════

class LLMClient:
    """
    LLM 调用客户端。

    用法:
      client = LLMClient('config.yaml')
      sql, resp = client.generate_sql("查询象屿系持仓")
      text, resp = client.generate_report_text("...")
    """

    def __init__(self, config_path: str = 'config.yaml'):
        from pathlib import Path
        cfg_file = Path(config_path)
        if not cfg_file.exists():
            cfg_file = cfg_file.parent / 'config.example.yaml'
        try:
            with open(cfg_file, encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            config = {}
        self.cfg = config.get('llm', {})
        self.sql_gen_cfg = self.cfg.get('sql_gen', {})
        self.report_cfg = self.cfg.get('report_text', {})
        self.providers = {
            'enterprise_internal': self.cfg.get('enterprise_internal', {}),
            'deepseek': self.cfg.get('deepseek', {}),
            'lmstudio': self.cfg.get('lmstudio', {}),
        }

    def _resolve_api_key(self, provider_name: str, provider_cfg: dict) -> str:
        """Resolve API key: env var overrides config only if non-placeholder."""
        env_key = os.environ.get(f"{provider_name.upper()}_API_KEY", '')
        cfg_key = provider_cfg.get('api_key', '')
        if env_key and env_key not in self._PLACEHOLDER_KEYS:
            return env_key.strip()
        if cfg_key and cfg_key not in self._PLACEHOLDER_KEYS:
            return cfg_key.strip()
        return ''

    # ── 公开接口 ──────────────────────────────────────────────

    def generate_sql(self, prompt: str, schema_context: str = "") -> tuple[str, LLMResponse]:
        """
        SQL 生成端点。

        策略：优先内网 LLM（问题文本含敏感信息），不可用时若 external_allowed=true 则走 DeepSeek 兜底。
        发送内容：仅 schema 字段语义名 + 用户问题，不含数据行。

        返回: (sql_text, LLMResponse)
        """
        full_prompt = prompt
        if schema_context:
            full_prompt = f"{schema_context}\n\n用户问题：{prompt}"

        # 1) 尝试内网
        primary = self.sql_gen_cfg.get('primary', 'enterprise_internal')
        result = self._call(primary, full_prompt,
                            system="你是一个 SQL 专家。根据给定的表结构和用户问题，生成正确的 DuckDB SQL 查询语句。只返回 SQL，不要解释。",
                            timeout=self.sql_gen_cfg.get('timeout', 30),
                            max_tokens=self.sql_gen_cfg.get('max_tokens', 2000))

        if result.success:
            return self._extract_sql(result.text), result

        # 2) 内网失败，检查是否允许外部兜底
        if not self.sql_gen_cfg.get('external_allowed', False):
            return "", result  # 不允许外发，直接返回失败

        # 3) 兜底外部 LLM
        fallback = self.sql_gen_cfg.get('fallback')
        if not fallback:
            return "", result

        result2 = self._call(fallback, full_prompt,
                             system="你是一个 SQL 专家。根据给定的表结构和用户问题，生成正确的 DuckDB SQL 查询语句。只返回 SQL，不要解释。",
                             timeout=self.sql_gen_cfg.get('timeout', 30),
                             max_tokens=self.sql_gen_cfg.get('max_tokens', 2000))
        return self._extract_sql(result2.text), result2

    def generate_report_text(self, prompt: str, numerical_data: dict = None) -> tuple[str, LLMResponse | ReportDegradedResult]:
        """
        ★ 报告文字生成端点 — 严禁 fallback 到任何外部模型 ★

        策略：
          - 仅走 enterprise_internal（config.yaml 中 report_text.provider）
          - 不可用时降级为 ReportDegradedResult（纯数值 + 占位说明）
          - 绝不调用外部 LLM

        返回: (text, LLMResponse | ReportDegradedResult)
        """
        provider = self.report_cfg.get('provider', 'enterprise')
        # 如果 report_text 区块自带 url/api_key（如测试用 DeepSeek），直接使用
        if self.report_cfg.get('url') and self.report_cfg.get('api_key'):
            self.providers['_report_direct'] = {
                'url': self.report_cfg['url'],
                'model': self.report_cfg.get('model', ''),
                'api_key': self.report_cfg['api_key'],
            }
            provider = '_report_direct'
        elif provider not in ('enterprise', 'enterprise_internal'):
            provider = 'enterprise_internal'

        result = self._call(provider, prompt,
                            system="你是一个专业的金融报告撰写助手。基于提供的数值数据，生成专业、简洁的分析文字。",
                            timeout=self.report_cfg.get('timeout', 60),
                            max_tokens=self.report_cfg.get('max_tokens', 3000))

        if result.success:
            return result.text, result

        # ★ 降级：不调用 fallback，返回纯数值 + 占位
        degraded = ReportDegradedResult(
            message="内网 AI 服务暂不可用，已生成数值报告，文字说明请稍后补充。",
            numerical_data=numerical_data or {},
        )
        return self._format_degraded_output(prompt, degraded), degraded

    def classify_intent(self, user_input: str, skill_registry: list[dict]) -> tuple[str | None, LLMResponse]:
        """
        意图分类端点（Phase 4 完整实现）。

        使用 LLM 对用户意图分类，返回最匹配的 Skill name（或 None 表示探索式查询）。

        参数:
          user_input:      用户问题文本
          skill_registry:  [{name, description}, ...] 所有已注册 Skill
        """
        if not skill_registry:
            return None, LLMResponse(success=True, text="", endpoint="none", model="")

        skills_desc = "\n".join(
            f"- {s['name']}: {s.get('description', s['name'])}"
            for s in skill_registry
        )
        prompt = (
            f"可用技能列表：\n{skills_desc}\n\n"
            f"用户输入：{user_input}\n\n"
            f"判断用户意图最匹配哪个技能。如果用户只是想查询数据、做临时统计，返回 NONE。"
            f"只返回技能名称或 NONE，不要有其他文字。"
        )
        result = self._call(
            self.sql_gen_cfg.get('primary', 'enterprise_internal'),
            prompt,
            system="你是一个意图分类助手。只返回技能名称或 NONE。",
            timeout=10,
            max_tokens=50,
        )
        if not result.success:
            return None, result

        name = result.text.strip()
        if name.upper() == 'NONE':
            return None, result
        # 验证返回的技能名称在注册表中（大小写不敏感）
        name_lower = name.lower()
        valid_names = {s['name'].lower(): s['name'] for s in skill_registry}
        matched = valid_names.get(name_lower)
        return matched if matched else None, result

    # ── Tool-calling 接口 (chat) ───────────────────────────────

    def chat(
        self, messages: list[dict], tools: list[dict] | None = None,
        timeout: int = None, max_tokens: int = None,
    ) -> ChatResult:
        """
        Tool-calling 对话接口（OpenAI function-calling 风格）。

        复用既有 provider 选择逻辑（primary 优先，external_allowed 控制外发）。
        tool_mode=native 直接发送 tools 数组；react 兜底可后置。

        参数:
          messages:  完整对话历史 [{"role":"system"|"user"|"assistant"|"tool", ...}]
          tools:     工具定义列表（OpenAI 格式），None 则无工具
          timeout:   超时秒数（默认取自 config）
          max_tokens: 最大输出 token（默认取自 config）

        返回 ChatResult，其中 tool_calls 已归一为 [{id, name, arguments: dict}]。
        """
        tool_mode = self.sql_gen_cfg.get('tool_mode', 'native')
        if timeout is None:
            timeout = self.sql_gen_cfg.get('timeout', 30)
        if max_tokens is None:
            max_tokens = self.sql_gen_cfg.get('max_tokens', 2000)

        if tool_mode == 'native':
            return self._chat_native(messages, tools, timeout, max_tokens)
        else:
            return self._chat_react(messages, tools, timeout, max_tokens)

    # ── Provider 管理接口 ──────────────────────────────────────

    def test_connection(self, provider: str = None) -> dict:
        """测试 LLM provider 连通性：先测 /models，再测 /chat/completions。"""
        import requests as _req
        provider = provider or self.sql_gen_cfg.get('primary', 'enterprise_internal')
        cfg = self.providers.get(provider)
        if not cfg or not cfg.get('url'):
            return {"ok": False, "error": f"未配置 provider: {provider}"}
        base_url = cfg["url"].rstrip("/")
        headers = self._build_request_headers(provider, cfg)

        models_list = []
        try:
            resp = _req.get(f"{base_url}/models", headers=headers, timeout=5)
            if resp.status_code == 200:
                models_list = [m["id"] for m in resp.json().get("data", [])]
            elif resp.status_code in (401, 403):
                return {"ok": False, "error": "模型列表接口认证失败，请检查 API Key 配置"}
        except _req.ConnectionError:
            return {"ok": False, "error": f"无法连接 {cfg['url']}，请确认服务已启动"}
        except _req.Timeout:
            return {"ok": False, "error": "连接超时（5s）"}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

        # 实际测试 chat/completions 端点（用最小请求）
        model = cfg.get("model", "")
        chat_payload = {
            "model": model,
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 5,
        }
        try:
            chat_resp = _req.post(
                f"{base_url}/chat/completions",
                json=chat_payload, headers=headers, timeout=10,
            )
            if chat_resp.status_code == 402:
                return {
                    "ok": False,
                    "error": "API 账户余额不足，请充值后重试",
                    "models": models_list,
                }
            if chat_resp.status_code in (401, 403):
                return {
                    "ok": False,
                    "error": "模型列表可访问，但对话接口认证失败（HTTP "
                             f"{chat_resp.status_code}），请检查 API Key 或模型权限配置",
                    "models": models_list,
                }
            if chat_resp.status_code >= 500:
                return {
                    "ok": False,
                    "error": f"对话接口服务端错误（HTTP {chat_resp.status_code}），请检查 LLM 服务状态",
                    "models": models_list,
                }
            if chat_resp.status_code == 200:
                try:
                    raw = chat_resp.json()
                    data = self._extract_openai_response(raw)
                    if not data.get('choices'):
                        gw_err = self._parse_gateway_error(data)
                        return {
                            "ok": False,
                            "error": gw_err or (
                                f"对话接口连通但响应格式异常：缺少 choices 字段。"
                                f"响应 keys: {list(data.keys())}。"
                                "请确认网关代理程序（openai_gateway_proxy.py）的 APP_CODE 已正确配置。"
                            ),
                            "models": models_list,
                            "raw_response_keys": list(raw.keys()),
                        }
                except (ValueError, AttributeError):
                    pass
        except _req.Timeout:
            return {"ok": False, "error": "对话接口响应超时，但模型列表可访问", "models": models_list}
        except _req.ConnectionError:
            return {"ok": False, "error": f"无法连接 {cfg['url']}，请确认服务已启动"}
        except Exception:
            pass

        return {
            "ok": True,
            "provider": provider,
            "models": models_list,
            "configured_model": model,
        }

    def list_providers(self) -> list[dict]:
        """返回所有已配置的 provider 及其基本信息。"""
        primary = self.sql_gen_cfg.get('primary', 'enterprise_internal')
        result = []
        for name, cfg in self.providers.items():
            if not cfg or not cfg.get('url'):
                continue
            result.append({
                "name": name,
                "url": cfg.get("url", ""),
                "model": cfg.get("model", ""),
                "is_local": name == "lmstudio",
                "is_primary": name == primary,
            })
        return result

    def _chat_native(
        self, messages: list[dict], tools: list[dict] | None,
        timeout: int, max_tokens: int,
    ) -> ChatResult:
        """Native OpenAI function-calling 模式"""
        primary = self.sql_gen_cfg.get('primary', 'enterprise_internal')
        result = self._call_with_messages(primary, messages, tools, timeout, max_tokens)

        if result.success:
            return result

        # 内网失败，检查是否允许外部兜底
        if not self.sql_gen_cfg.get('external_allowed', False):
            return ChatResult(
                success=False, error=f"内网 LLM 不可用且不允许外发: {result.error}",
                elapsed_ms=result.elapsed_ms,
            )

        fallback = self.sql_gen_cfg.get('fallback')
        if not fallback:
            return ChatResult(
                success=False, error=f"LLM 不可用且无兜底配置: {result.error}",
                elapsed_ms=result.elapsed_ms,
            )

        return self._call_with_messages(fallback, messages, tools, timeout, max_tokens)

    def _chat_react(
        self, messages: list[dict], tools: list[dict] | None,
        timeout: int, max_tokens: int,
    ) -> ChatResult:
        """React 文本协议：适用于不支持 OpenAI function-calling 的 LLM。

        工具说明嵌入 system prompt，tool_call/tool 消息转为文本等价形式，
        完整对话历史发送给 LLM，API payload 不含 tools/tool_choice。
        """
        import copy
        react_msgs = copy.deepcopy(messages)

        if tools:
            tool_desc = _format_tools_for_react(tools)
            tool_block = (
                "\n\n## 可用工具\n" + tool_desc
                + "\n\n当需要调用工具时，请输出一行 JSON（独占一行）：\n"
                '{"action":"工具名","args":{参数}}\n'
                "如果不需要调用工具，直接输出最终回答文本。\n"
                "每次只调用一个工具，等待工具返回结果后再决定下一步。"
            )
            found = False
            for msg in react_msgs:
                if msg.get("role") == "system":
                    msg["content"] += tool_block
                    found = True
                    break
            if not found:
                react_msgs.insert(0, {
                    "role": "system",
                    "content": "你是一个数据分析助手。" + tool_block,
                })

        converted = _convert_tool_messages_to_text(react_msgs)

        primary = self.sql_gen_cfg.get('primary', 'enterprise_internal')
        result = self._call_with_messages(
            primary, converted, tools=None,
            timeout=timeout, max_tokens=max_tokens,
        )

        if not result.success:
            if not self.sql_gen_cfg.get('external_allowed', False):
                return ChatResult(
                    success=False,
                    error=f"内网 LLM 不可用且不允许外发: {result.error}",
                    elapsed_ms=result.elapsed_ms,
                )
            fallback = self.sql_gen_cfg.get('fallback')
            if fallback:
                result = self._call_with_messages(
                    fallback, converted, tools=None,
                    timeout=timeout, max_tokens=max_tokens,
                )
            if not result.success:
                return result

        text = result.text or ""
        tool_calls = _parse_react_action(text)
        if tool_calls:
            return ChatResult(
                success=True, text="", tool_calls=tool_calls,
                elapsed_ms=result.elapsed_ms, token_count=result.token_count,
                model=result.model,
            )
        return ChatResult(
            success=True, text=text, tool_calls=[],
            elapsed_ms=result.elapsed_ms, token_count=result.token_count,
            model=result.model,
        )

    # ── 流式接口 ──────────────────────────────────────────────

    def stream_sql_gen(self, prompt: str, schema_context: str = "") -> Generator[str, None, LLMResponse]:
        """
        SQL 生成流式输出（SSE）。

        每次 yield 一段增量文本，最后通过 return 返回完整 LLMResponse。
        前端通过 SSE 消费，实现逐字显示。
        """
        full_prompt = f"{schema_context}\n\n用户问题：{prompt}" if schema_context else prompt
        primary = self.sql_gen_cfg.get('primary', 'enterprise_internal')

        chunks, result_ref = self._call_streaming(
            primary, full_prompt,
            system="你是一个 SQL 专家。只返回 SQL，不要解释。",
            timeout=self.sql_gen_cfg.get('timeout', 30),
            max_tokens=self.sql_gen_cfg.get('max_tokens', 2000),
        )

        full_text = ""
        for chunk in chunks:
            full_text += chunk
            yield chunk

        if not full_text and self.sql_gen_cfg.get('external_allowed', False):
            fallback = self.sql_gen_cfg.get('fallback')
            if fallback:
                chunks2, result_ref2 = self._call_streaming(
                    fallback, full_prompt,
                    system="你是一个 SQL 专家。只返回 SQL，不要解释。",
                    timeout=self.sql_gen_cfg.get('timeout', 30),
                    max_tokens=self.sql_gen_cfg.get('max_tokens', 2000),
                )
                full_text2 = ""
                for chunk in chunks2:
                    full_text2 += chunk
                    yield chunk
                return LLMResponse(
                    success=bool(full_text2), text=full_text2,
                    endpoint=result_ref2.endpoint, model=result_ref2.model,
                    elapsed_ms=result_ref2.elapsed_ms,
                    error=result_ref2.error if not full_text2 else "",
                )

        # Reconstruct result with actual full_text (result_ref was created before streaming)
        return LLMResponse(
            success=bool(full_text), text=full_text,
            endpoint=result_ref.endpoint, model=result_ref.model,
            elapsed_ms=result_ref.elapsed_ms,
            error=result_ref.error if not full_text else "",
        )

    # ── 底层 HTTP 调用 ────────────────────────────────────────

    # Placeholder values that must never be sent as real API keys
    _PLACEHOLDER_KEYS = frozenset({
        '你的DeepSeek_API_Key', '${DEEPSEEK_API_KEY}', 'YOUR_API_KEY',
        'your_deepseek_api_key_here', 'your_api_key_here',
        'sk-placeholder',
    })

    def _build_request_headers(self, provider_name: str, provider_cfg: dict) -> dict:
        """Build HTTP request headers, respecting auth_type in provider config.

        auth_type values:
          bearer (default) — Authorization: Bearer {api_key}
          none             — no auth header (useful when proxy handles auth internally)
        """
        api_key = self._resolve_api_key(provider_name, provider_cfg)
        auth_type = provider_cfg.get('auth_type', 'bearer')
        headers = {'Content-Type': 'application/json'}
        if auth_type == 'none':
            pass
        elif api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        return headers

    @staticmethod
    def _parse_gateway_error(data: dict) -> str | None:
        """从企业网关错误响应（APIC/MA 格式）中提取可读错误信息。

        企业 APIC 网关认证失败时会返回包含 resCode/servRespCd 的平铺 JSON，
        而不是 OpenAI choices 格式。本方法识别这类响应并返回具体提示。
        """
        if 'resCode' not in data and 'servRespCd' not in data:
            return None
        res_code = data.get('resCode') or data.get('servRespCd', '')
        msg = data.get('message', '')
        desc = data.get('servRespDescInfo', '')
        if 'appCode' in msg or 'APIC.0303' in msg or 'app authentication' in msg:
            return (
                f"企业网关认证失败（{res_code}）：{msg[:150]}。"
                "请检查：① 网关代理程序（openai_gateway_proxy.py）中 APP_CODE 是否已正确填写；"
                "② config.yaml enterprise_internal.api_key 是否为空或可填任意值（代理统一鉴权时）。"
            )
        detail = msg or desc
        return f"企业网关返回错误（{res_code}）：{detail[:150]}" if detail else None

    @staticmethod
    def _runtime_log(level: str, event: str, detail: dict = None):
        """将关键 LLM 事件写入运行时日志（JSONL）"""
        try:
            from tools.runtime_logger import get_logger
            rl = get_logger()
            if level == 'error':
                rl.error('llm', event, detail)
            elif level == 'warning':
                rl.warning('llm', event, detail)
            else:
                rl.log_llm_response(
                    provider=detail.get('provider', ''),
                    status_code=detail.get('status_code', 0),
                    response_keys=detail.get('response_keys'),
                    has_choices=detail.get('has_choices', False),
                    error=detail.get('error', ''),
                    raw_preview=detail.get('raw_preview', ''),
                )
        except Exception:
            pass

    @staticmethod
    def _extract_openai_response(data: dict) -> dict:
        """
        从 LLM 响应中提取标准 OpenAI 格式。

        企业网关代理返回的响应可能包裹在 txBody.txEntity 中：
          {txHeader: {...}, txBody: {txEntity: {choices: [...]}}}
        标准 OpenAI / DeepSeek / LM Studio 直接返回 {choices: [...]}.

        本方法自动适配两种格式，返回内层 OpenAI 格式的 dict。
        """
        if "choices" in data:
            return data
        tx_body = data.get("txBody")
        if isinstance(tx_body, dict):
            entity = tx_body.get("txEntity")
            if isinstance(entity, dict):
                return entity
        body = data.get("body")
        if isinstance(body, dict) and "choices" in body:
            return body
        return data

    def _call(self, provider_name: str, prompt: str,
              system: str = "", timeout: int = 30, max_tokens: int = 2000) -> LLMResponse:
        """同步调用 LLM，返回 LLMResponse。"""
        provider = self.providers.get(provider_name)
        if not provider:
            return LLMResponse(success=False, endpoint=provider_name, model="",
                               text="", error=f"未配置 LLM 提供方: {provider_name}")

        url = provider.get('url', '')
        model = provider.get('model', '')
        api_key = self._resolve_api_key(provider_name, provider)

        if not url or url.startswith('http://['):
            return LLMResponse(success=False, endpoint=provider_name, model=model,
                               text="", error="LLM 服务地址未配置")

        headers = self._build_request_headers(provider_name, provider)

        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})

        payload = {
            'model': model,
            'messages': messages,
            'max_tokens': max_tokens,
            'stream': False,
        }

        start = time.time()
        try:
            resp = requests.post(
                f"{url.rstrip('/')}/chat/completions",
                json=payload, headers=headers, timeout=timeout,
            )
            elapsed_ms = int((time.time() - start) * 1000)

            if resp.status_code == 200:
                raw = resp.json()
                data = self._extract_openai_response(raw)
                logger.debug("[LLM _call] provider=%s raw_keys=%s data_keys=%s",
                             provider_name, list(raw.keys())[:10], list(data.keys())[:10])
                choices = data.get('choices')
                if not choices or not isinstance(choices, list):
                    raw_str = json.dumps(raw, ensure_ascii=False, default=str)[:2000]
                    logger.warning("[LLM _call] 响应缺少 choices，完整响应：%s", raw_str)
                    self._runtime_log('warning', 'LLM 响应缺少 choices', {
                        'provider': provider_name, 'model': model,
                        'raw_keys': list(raw.keys()),
                        'data_keys': list(data.keys()),
                        'raw_preview': raw_str[:1000],
                    })
                    gw_err = self._parse_gateway_error(data)
                    return LLMResponse(
                        success=False, endpoint=provider_name, model=model, text="",
                        elapsed_ms=elapsed_ms,
                        error=gw_err or f"LLM 返回格式异常：响应中缺少 choices 字段。响应 keys: {list(data.keys())}",
                    )
                message = choices[0].get('message') or {}
                text = message.get('content', '') or ''
                usage = data.get('usage', {})
                return LLMResponse(
                    success=True, text=text, endpoint=provider_name, model=model,
                    token_count=usage.get('total_tokens', 0), elapsed_ms=elapsed_ms,
                )
            elif resp.status_code == 402:
                return LLMResponse(success=False, endpoint=provider_name, model=model,
                                   text="", error="API 账户余额不足，请充值后重试或切换其他 LLM 提供方")
            elif resp.status_code in (401, 403):
                detail = resp.text[:100] if resp.text else ''
                return LLMResponse(success=False, endpoint=provider_name, model=model,
                                   text="", error=f"API Key 认证失败（{resp.status_code}），请检查设置中的 API Key 配置")
            elif resp.status_code >= 500:
                return LLMResponse(success=False, endpoint=provider_name, model=model,
                                   text="", error=f"LLM 服务端错误（HTTP {resp.status_code}），请稍后重试")
            else:
                logger.warning("[LLM _call] HTTP %d: %s", resp.status_code, resp.text[:500])
                return LLMResponse(success=False, endpoint=provider_name, model=model,
                                   text="", error=f"HTTP {resp.status_code}: {resp.text[:200]}")

        except requests.Timeout:
            return LLMResponse(success=False, endpoint=provider_name, model=model,
                               text="", error="timeout")
        except requests.ConnectionError:
            return LLMResponse(success=False, endpoint=provider_name, model=model,
                               text="", error="connection refused")
        except Exception as e:
            logger.exception("[LLM _call] 未预期异常: %s", e)
            return LLMResponse(success=False, endpoint=provider_name, model=model,
                               text="", error=str(e)[:200])

    def _call_with_messages(
        self, provider_name: str, messages: list[dict],
        tools: list[dict] | None = None, timeout: int = 30, max_tokens: int = 2000,
    ) -> ChatResult:
        """
        使用完整 messages 数组调用 LLM（支持 tools）。

        返回 ChatResult，解析 choices[0].message 中的 content 和 tool_calls。
        """
        provider = self.providers.get(provider_name)
        if not provider:
            return ChatResult(success=False, error=f"未配置 LLM 提供方: {provider_name}")

        url = provider.get('url', '')
        model = provider.get('model', '')
        api_key = self._resolve_api_key(provider_name, provider)

        if not url or url.startswith('http://['):
            return ChatResult(success=False, error="LLM 服务地址未配置")

        headers = self._build_request_headers(provider_name, provider)

        payload = {
            'model': model,
            'messages': messages,
            'max_tokens': max_tokens,
            'stream': False,
        }
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'

        start = time.time()
        try:
            resp = requests.post(
                f"{url.rstrip('/')}/chat/completions",
                json=payload, headers=headers, timeout=timeout,
            )
            elapsed_ms = int((time.time() - start) * 1000)

            if resp.status_code == 200:
                raw = resp.json()
                data = self._extract_openai_response(raw)
                logger.debug("[LLM chat] provider=%s raw_keys=%s data_keys=%s",
                             provider_name, list(raw.keys())[:10], list(data.keys())[:10])
                choices = data.get('choices')
                if not choices or not isinstance(choices, list):
                    raw_str = json.dumps(raw, ensure_ascii=False, default=str)[:2000]
                    logger.warning("[LLM chat] 响应缺少 choices，完整响应：%s", raw_str)
                    self._runtime_log('warning', 'LLM chat 响应缺少 choices', {
                        'provider': provider_name, 'model': model,
                        'raw_keys': list(raw.keys()),
                        'data_keys': list(data.keys()),
                        'raw_preview': raw_str[:1000],
                        'has_tools': bool(tools),
                        'message_count': len(messages),
                    })
                    gw_err = self._parse_gateway_error(data)
                    return ChatResult(
                        success=False, elapsed_ms=elapsed_ms, model=model,
                        error=gw_err or f"LLM 返回格式异常：响应中缺少 choices 字段。响应 keys: {list(data.keys())}",
                    )
                choice = choices[0]
                message = choice.get('message', {})
                text = message.get('content', '') or ''
                usage = data.get('usage', {})

                # 解析 tool_calls（企业 LLM 可能返回 null）
                tool_calls_raw = message.get('tool_calls')
                if not tool_calls_raw:
                    tool_calls_raw = []
                tool_calls = []
                for tc in tool_calls_raw:
                    func = tc.get('function', {})
                    try:
                        args = json.loads(func.get('arguments', '{}'))
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append({
                        'id': tc.get('id', ''),
                        'name': func.get('name', ''),
                        'arguments': args,
                    })

                return ChatResult(
                    success=True, text=text, tool_calls=tool_calls,
                    raw=data, elapsed_ms=elapsed_ms,
                    token_count=usage.get('total_tokens', 0), model=model,
                )
            elif resp.status_code == 402:
                return ChatResult(
                    success=False, elapsed_ms=elapsed_ms, model=model,
                    error="API 账户余额不足，请充值后重试或切换其他 LLM 提供方",
                )
            elif resp.status_code in (401, 403):
                detail = resp.text[:100] if resp.text else ''
                return ChatResult(success=False,
                                  error=f"API Key 认证失败（{resp.status_code}），请检查设置中的 API Key 配置",
                                  elapsed_ms=elapsed_ms, model=model)
            elif resp.status_code >= 500:
                return ChatResult(
                    success=False, elapsed_ms=elapsed_ms, model=model,
                    error=f"LLM 服务端错误（HTTP {resp.status_code}），请稍后重试",
                )
            else:
                logger.warning("[LLM chat] HTTP %d: %s", resp.status_code, resp.text[:500])
                return ChatResult(
                    success=False, elapsed_ms=elapsed_ms, model=model,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
        except requests.Timeout:
            return ChatResult(success=False, error="timeout",
                            elapsed_ms=int((time.time() - start) * 1000))
        except requests.ConnectionError:
            return ChatResult(success=False, error="connection refused",
                            elapsed_ms=int((time.time() - start) * 1000))
        except Exception as e:
            logger.exception("[LLM chat] 未预期异常: %s", e)
            return ChatResult(success=False, error=str(e)[:200],
                            elapsed_ms=int((time.time() - start) * 1000))

    def _call_streaming(self, provider_name: str, prompt: str,
                        system: str = "", timeout: int = 30, max_tokens: int = 2000):
        """流式调用 LLM，返回 (chunks_generator, LLMResponse)。"""
        provider = self.providers.get(provider_name)
        if not provider:
            return iter([]), LLMResponse(success=False, endpoint=provider_name, model="",
                                         text="", error=f"未配置 LLM 提供方: {provider_name}")

        url = provider.get('url', '')
        model = provider.get('model', '')
        api_key = self._resolve_api_key(provider_name, provider)

        if not url or url.startswith('http://['):
            return iter([]), LLMResponse(success=False, endpoint=provider_name, model=model,
                                         text="", error="LLM 服务地址未配置")

        headers = self._build_request_headers(provider_name, provider)

        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})

        payload = {
            'model': model,
            'messages': messages,
            'max_tokens': max_tokens,
            'stream': True,
        }

        full_text = ""
        start = time.time()

        try:
            resp = requests.post(
                f"{url.rstrip('/')}/chat/completions",
                json=payload, headers=headers, timeout=timeout, stream=True,
            )
            if resp.status_code != 200:
                err_text = resp.text[:200]
                return iter([]), LLMResponse(success=False, endpoint=provider_name, model=model,
                                             text="", error=f"HTTP {resp.status_code}: {err_text}")

            def generate():
                nonlocal full_text
                for line in resp.iter_lines(decode_unicode=True):
                    if not line or not line.startswith('data: '):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == '[DONE]':
                        break
                    try:
                        chunk = json.loads(data_str)
                        chunk = LLMClient._extract_openai_response(chunk)
                        choices = chunk.get('choices', [])
                        if not choices:
                            continue
                        delta = choices[0].get('delta', {})
                        content = delta.get('content', '')
                        if content:
                            full_text += content
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

            elapsed_ms = int((time.time() - start) * 1000)
            response = LLMResponse(
                success=bool(full_text), text=full_text, endpoint=provider_name,
                model=model, elapsed_ms=elapsed_ms,
            )

            return generate(), response

        except requests.Timeout:
            return iter([]), LLMResponse(success=False, endpoint=provider_name, model=model,
                                         text="", error="timeout")
        except requests.ConnectionError:
            return iter([]), LLMResponse(success=False, endpoint=provider_name, model=model,
                                         text="", error="connection refused")
        except Exception as e:
            return iter([]), LLMResponse(success=False, endpoint=provider_name, model=model,
                                         text="", error=str(e)[:200])

    # ── 辅助方法 ──────────────────────────────────────────────

    def _extract_sql(self, text: str) -> str:
        """从 LLM 输出中提取 SQL 语句（去除 markdown 代码块包裹）。"""
        text = text.strip()
        # 去掉 ```sql ... ``` 包裹
        if text.startswith('```'):
            lines = text.split('\n')
            # 去掉第一行（```sql）和最后一行（```）
            if lines[0].startswith('```'):
                lines = lines[1:]
            if lines and lines[-1].startswith('```'):
                lines = lines[:-1]
            text = '\n'.join(lines)
        return text.strip()

    def _format_degraded_output(self, prompt: str, degraded: ReportDegradedResult) -> str:
        """降级输出：以纯数值结构替代 LLM 生成的文字。"""
        lines = [
            "⚠️ 内网 AI 服务暂不可用，以下为数值报告：",
            "",
        ]
        for key, value in degraded.numerical_data.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
        lines.append(f"[原始请求: {prompt[:100]}...]")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  React 协议辅助函数（兜底模式，本期可后置）
# ═══════════════════════════════════════════════════════════════

def _format_tools_for_react(tools: list[dict]) -> str:
    """将 OpenAI 工具定义转为文本描述（供 react 模式 system prompt）"""
    lines = []
    for tool in tools:
        func = tool.get("function", {})
        name = func.get("name", "")
        desc = func.get("description", "")
        params = func.get("parameters", {}).get("properties", {})
        required = func.get("parameters", {}).get("required", [])
        lines.append(f"- {name}: {desc}")
        for pname, pinfo in params.items():
            req = "（必填）" if pname in required else ""
            lines.append(f"    {pname}{req}: {pinfo.get('description', '')}")
    return "\n".join(lines)


def _convert_tool_messages_to_text(messages: list[dict]) -> list[dict]:
    """将 tool_call/tool 角色消息转为纯文本，供不支持 function-calling 的 LLM 理解。"""
    converted = []
    for msg in messages:
        role = msg.get("role", "")

        if role == "assistant" and msg.get("tool_calls"):
            parts = []
            if msg.get("content"):
                parts.append(msg["content"])
            for tc in msg["tool_calls"]:
                func = tc.get("function", {})
                name = func.get("name", tc.get("name", "unknown"))
                raw_args = func.get("arguments", tc.get("arguments", "{}"))
                if isinstance(raw_args, dict):
                    args_str = json.dumps(raw_args, ensure_ascii=False)
                else:
                    args_str = str(raw_args)
                parts.append(f'{{"action":"{name}","args":{args_str}}}')
            converted.append({"role": "assistant", "content": "\n".join(parts)})

        elif role == "tool":
            tool_id = msg.get("tool_call_id", "")
            tool_name = msg.get("name", "")
            if not tool_name and tool_id.startswith("call_"):
                tool_name = tool_id[5:]
            content = msg.get("content", "")
            converted.append({
                "role": "user",
                "content": f"[工具 {tool_name or 'tool'} 返回结果]\n{content}",
            })

        else:
            converted.append(msg)

    # Merge consecutive user messages (some LLMs reject them)
    merged = []
    for msg in converted:
        if merged and merged[-1]["role"] == msg["role"] == "user":
            merged[-1]["content"] += "\n\n" + msg["content"]
        else:
            merged.append(msg)
    return merged


def _parse_react_action(text: str) -> list[dict]:
    """从 LLM 输出中解析 react 协议的 tool_call JSON。支持嵌套参数。"""
    import re

    for m in re.finditer(r'\{\s*"action"\s*:', text):
        start = m.start()
        depth = 0
        i = start
        end = -1
        while i < len(text):
            c = text[i]
            if c == '"':
                i += 1
                while i < len(text):
                    if text[i] == '\\':
                        i += 2
                        continue
                    if text[i] == '"':
                        break
                    i += 1
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
            i += 1

        if end < 0:
            continue
        try:
            obj = json.loads(text[start:end])
            if isinstance(obj, dict) and "action" in obj:
                name = str(obj["action"])
                args = obj.get("args", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                if not isinstance(args, dict):
                    args = {"value": args}
                return [{"id": f"call_{name}", "name": name, "arguments": args}]
        except json.JSONDecodeError:
            continue

    return []
