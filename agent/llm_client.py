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
import os
import time
from collections.abc import Generator
from dataclasses import dataclass, field

import requests
import yaml

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
        """测试 LLM provider 连通性：先测 /models，再测 /chat/completions 并校验响应格式。"""
        import requests as _req
        provider = provider or self.sql_gen_cfg.get('primary', 'enterprise_internal')
        cfg = self.providers.get(provider)
        if not cfg or not cfg.get('url'):
            return {"ok": False, "error": f"未配置 provider: {provider}"}
        base_url = cfg["url"].rstrip("/")
        api_key = self._resolve_api_key(provider, cfg)
        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        models_list = []
        try:
            resp = _req.get(f"{base_url}/models", headers=headers, timeout=5)
            if resp.status_code == 200:
                try:
                    models_list = [m["id"] for m in resp.json().get("data", [])]
                except Exception:
                    models_list = []
            elif resp.status_code in (401, 403):
                return {"ok": False, "error": "模型列表接口认证失败，请检查 API Key 配置"}
        except _req.ConnectionError:
            return {"ok": False, "error": f"无法连接 {cfg['url']}，请确认服务已启动"}
        except _req.Timeout:
            return {"ok": False, "error": "连接超时（5s）"}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

        # 实际测试 chat/completions 端点（用最小请求 + 校验响应格式）
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
                data = chat_resp.json()
                parsed = self._resolve_response_content(data, cfg)
                if parsed["ok"]:
                    return {
                        "ok": True,
                        "provider": provider,
                        "models": models_list,
                        "configured_model": model,
                    }
                else:
                    # 响应格式异常 → 给出诊断信息
                    raw_desc = parsed.get("raw_keys", _describe_keys(data))
                    result = {
                        "ok": False,
                        "error": parsed["error"].replace("{provider}", provider),
                        "models": models_list,
                        "configured_model": model,
                        "raw_response_preview": json.dumps(
                            data, ensure_ascii=False
                        )[:500],
                    }
                    # 仅当非网关错误时才追加 response_map 提示
                    if "网关返回错误" not in parsed["error"]:
                        result["hint"] = (
                            "请在 config.yaml 中为此 provider 添加 response_map "
                            "字段指定响应内容路径。例如：\n"
                            "  response_map:\n"
                            "    content_path: \"data.reply\""
                        )
                    return result
            # 非 200/401/403/5xx 的响应
            return {
                "ok": False,
                "error": f"对话接口返回未预期的 HTTP {chat_resp.status_code}",
                "models": models_list,
                "configured_model": model,
            }
        except _req.Timeout:
            return {"ok": False, "error": "对话接口响应超时，但模型列表可访问", "models": models_list}
        except _req.ConnectionError:
            return {"ok": False, "error": f"无法连接 {cfg['url']}，请确认服务已启动"}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}

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
        """
        React 文本协议兜底（本期可后置，仅当 native 解析不稳定时启用）。

        把工具说明拼进 system prompt，要求模型输出：
          最终回答 或 {"action":"tool_name","args":{...}}
        由 _parse_react_action() 解析为 tool_calls。
        """
        if tools:
            tool_desc = _format_tools_for_react(tools)
            # 找到 system 消息并追加工具说明
            for msg in messages:
                if msg.get("role") == "system":
                    msg["content"] = (
                        msg["content"] + "\n\n## 可用工具\n" + tool_desc
                        + "\n\n当需要调用工具时，输出一行 JSON："
                        '{"action":"工具名","args":{...}}'
                        "\n否则直接输出最终回答。"
                    )
                    break
            else:
                messages.insert(0, {
                    "role": "system",
                    "content": "可用工具：\n" + tool_desc,
                })

        primary = self.sql_gen_cfg.get('primary', 'enterprise_internal')
        resp = self._call(primary, messages[-1].get("content", ""),
                          system=messages[0].get("content", "") if messages else "",
                          timeout=timeout, max_tokens=max_tokens)
        if not resp.success:
            return ChatResult(success=False, error=resp.error, elapsed_ms=resp.elapsed_ms)

        text = resp.text
        tool_calls = _parse_react_action(text)
        if tool_calls:
            return ChatResult(
                success=True, text="", tool_calls=tool_calls,
                elapsed_ms=resp.elapsed_ms, token_count=resp.token_count,
                model=resp.model,
            )
        return ChatResult(
            success=True, text=text, tool_calls=[],
            elapsed_ms=resp.elapsed_ms, token_count=resp.token_count,
            model=resp.model,
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

        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

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
                data = resp.json()
                parsed = self._resolve_response_content(data, provider)
                if parsed["ok"]:
                    return LLMResponse(
                        success=True, text=parsed["content"],
                        endpoint=provider_name, model=model,
                        token_count=parsed["usage"].get('total_tokens', 0),
                        elapsed_ms=elapsed_ms,
                    )
                else:
                    return LLMResponse(
                        success=False, endpoint=provider_name, model=model,
                        text="",
                        error=parsed["error"].replace("{provider}", provider_name),
                    )
            elif resp.status_code in (401, 403):
                detail = resp.text[:100] if resp.text else ''
                return LLMResponse(success=False, endpoint=provider_name, model=model,
                                   text="", error=f"api_key ({resp.status_code}: {detail})")
            elif resp.status_code >= 500:
                return LLMResponse(success=False, endpoint=provider_name, model=model,
                                   text="", error=f"connection refused (HTTP {resp.status_code})")
            else:
                return LLMResponse(success=False, endpoint=provider_name, model=model,
                                   text="", error=f"HTTP {resp.status_code}: {resp.text[:200]}")

        except requests.Timeout:
            return LLMResponse(success=False, endpoint=provider_name, model=model,
                               text="", error="timeout")
        except requests.ConnectionError:
            return LLMResponse(success=False, endpoint=provider_name, model=model,
                               text="", error="connection refused")
        except Exception as e:
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

        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

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
                data = resp.json()
                parsed = self._resolve_response_content(data, provider)
                if parsed["ok"]:
                    return ChatResult(
                        success=True, text=parsed["content"],
                        tool_calls=parsed["tool_calls"],
                        raw=data, elapsed_ms=elapsed_ms,
                        token_count=parsed["usage"].get('total_tokens', 0),
                        model=model,
                    )
                else:
                    return ChatResult(
                        success=False,
                        error=parsed["error"].replace("{provider}", provider_name),
                        elapsed_ms=elapsed_ms, model=model,
                    )
            elif resp.status_code in (401, 403):
                detail = resp.text[:100] if resp.text else ''
                return ChatResult(success=False,
                                  error=f"api_key ({resp.status_code}: {detail})",
                                  elapsed_ms=elapsed_ms, model=model)
            elif resp.status_code >= 500:
                return ChatResult(
                    success=False, elapsed_ms=elapsed_ms, model=model,
                    error=f"connection refused (HTTP {resp.status_code})",
                )
            else:
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

        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

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
                        data = json.loads(data_str)
                        content = self._extract_stream_delta(data, provider)
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

    # ── 响应解析辅助方法 ────────────────────────────────────────

    @staticmethod
    def _get_by_path(obj: dict, path: str):
        """按点号路径从嵌套 dict 中取值，不存在时返回 None。"""
        if not path or not isinstance(obj, dict):
            return None
        current = obj
        for part in path.split('.'):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    @staticmethod
    def _resolve_response_content(
        data: dict, provider_cfg: dict | None = None
    ) -> dict:
        """
        安全解析 LLM 响应，提取 content 和 tool_calls。

        支持：
          1. provider 配置的 response_map.content_path 路径
          2. 标准 OpenAI 格式：choices[0].message.content
          3. 常见企业网关变体格式自动检测

        返回: {"ok": bool, "content": str, "tool_calls": list[dict],
               "usage": dict, "error": str, "raw_keys": str}
        """
        provider_cfg = provider_cfg or {}
        response_map = provider_cfg.get('response_map', None)

        # 1) 显式 response_map 配置（优先）
        if response_map and response_map.get('content_path'):
            content = LLMClient._get_by_path(data, response_map['content_path'])
            if content is not None:
                tc_path = response_map.get('tool_calls_path', '')
                raw_tc = LLMClient._get_by_path(data, tc_path) if tc_path else None
                tool_calls = LLMClient._normalize_tool_calls(raw_tc)
                return {
                    "ok": True, "content": str(content),
                    "tool_calls": tool_calls,
                    "usage": data.get('usage', {}),
                    "error": "", "raw_keys": "",
                }
            # response_map 路径不存在 → 错误提示包含实际 key
            return {
                "ok": False, "content": "", "tool_calls": [],
                "usage": {}, "raw_keys": _describe_keys(data),
                "error": (
                    f"response_map.content_path 指向的路径 "
                    f"\"{response_map['content_path']}\" 在响应中不存在。"
                    f"响应根级字段：{_describe_keys(data)}"
                ),
            }

        # 2) 标准 OpenAI 格式
        choices = data.get('choices', [])
        if choices:
            choice = choices[0] if isinstance(choices, list) else {}
            msg = choice.get('message', {}) if isinstance(choice, dict) else {}
            content = (msg.get('content', '') or '') if isinstance(msg, dict) else ''
            tool_calls = LLMClient._normalize_tool_calls(
                msg.get('tool_calls', []) if isinstance(msg, dict) else []
            )
            return {
                "ok": True, "content": content,
                "tool_calls": tool_calls,
                "usage": data.get('usage', {}),
                "error": "", "raw_keys": "",
            }

        # 3) 自动检测常见企业网关变体
        auto_paths = [
            'content', 'data.content', 'data.reply', 'data.text',
            'reply', 'text', 'data.result.content', 'result.content',
        ]
        for path in auto_paths:
            val = LLMClient._get_by_path(data, path)
            if isinstance(val, str) and val.strip():
                # 校验：检测到的文本是否为网关错误信息
                err_detail = _detect_error_content(val)
                if err_detail:
                    return {
                        "ok": False, "content": "", "tool_calls": [],
                        "usage": {}, "raw_keys": _describe_keys(data),
                        "error": err_detail,
                    }
                return {
                    "ok": True, "content": val,
                    "tool_calls": [],
                    "usage": data.get('usage', {}),
                    "error": "", "raw_keys": "",
                }

        # 3.5) 检测网关返回的 error 响应（多种格式）
        # 格式1: {"error": {"message": "..."}}  (OpenAI/most proxies)
        err = data.get('error')
        if isinstance(err, dict):
            err_msg = err.get('message', '') or str(err)
            return {
                "ok": False, "content": "", "tool_calls": [],
                "usage": {}, "raw_keys": _describe_keys(data),
                "error": (
                    f"LLM 网关返回错误：{err_msg[:300]}。"
                    f"请检查：1) API Key 是否正确 2) 模型名称是否正确 3) 网关服务状态。"
                ),
            }
        # 格式2: {"error": "plain error string"}
        if isinstance(err, str) and err.strip():
            err_detail = _detect_error_content(err) or (
                f"LLM 网关返回错误：{err[:300]}。"
            )
            return {
                "ok": False, "content": "", "tool_calls": [],
                "usage": {}, "raw_keys": _describe_keys(data),
                "error": err_detail,
            }
        # 格式3: {"code": "APIC.0303", "message": "Incorrect app authentication..."} (企业网关)
        gateway_msg = data.get('message', '')
        gateway_code = data.get('code', '') or data.get('errCode', '') or data.get('respCode', '')
        if isinstance(gateway_msg, str) and gateway_msg.strip():
            err_detail = _detect_error_content(gateway_msg)
            if err_detail or gateway_code:
                return {
                    "ok": False, "content": "", "tool_calls": [],
                    "usage": {}, "raw_keys": _describe_keys(data),
                    "error": (
                        f"LLM 网关返回错误{(' [' + gateway_code + ']') if gateway_code else ''}："
                        f"{gateway_msg[:300]}。"
                        f"请检查：1) API Key / appCode 是否正确 2) 模型名称是否正确 3) 网关服务状态。"
                    ),
                }
        # 格式4: {"errMsg": "...", "errCode": "..."}
        gw_err_msg = data.get('errMsg', '') or data.get('respMsg', '')
        gw_err_code = data.get('errCode', '') or data.get('respCode', '')
        if isinstance(gw_err_msg, str) and gw_err_msg.strip():
            return {
                "ok": False, "content": "", "tool_calls": [],
                "usage": {}, "raw_keys": _describe_keys(data),
                "error": (
                    f"LLM 网关返回错误{(' [' + gw_err_code + ']') if gw_err_code else ''}："
                    f"{gw_err_msg[:300]}。"
                ),
            }

        # 4) 格式无法识别
        return {
            "ok": False, "content": "", "tool_calls": [],
            "usage": {}, "raw_keys": _describe_keys(data),
            "error": (
                f"响应格式不匹配（非 OpenAI 兼容），收到根级字段："
                f"{_describe_keys(data)}。"
                f"请在 config.yaml 的 {{provider}} 配置中添加 response_map.content_path "
                f"指向响应中文本内容的 JSON 路径。"
            ),
        }

    @staticmethod
    def _normalize_tool_calls(tool_calls_raw) -> list[dict]:
        """将 OpenAI 工具调用列表归一化。"""
        if not tool_calls_raw or not isinstance(tool_calls_raw, list):
            return []
        tool_calls = []
        for tc in tool_calls_raw:
            if not isinstance(tc, dict):
                continue
            func = tc.get('function', {})
            if not isinstance(func, dict):
                continue
            try:
                args_raw = func.get('arguments', '{}')
                if isinstance(args_raw, dict):
                    args = args_raw
                else:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else {}
            except (json.JSONDecodeError, TypeError):
                args = {}
            tool_calls.append({
                'id': tc.get('id', ''),
                'name': func.get('name', ''),
                'arguments': args,
            })
        return tool_calls

    @staticmethod
    def _extract_stream_delta(
        data: dict, provider_cfg: dict | None = None
    ) -> str:
        """
        从流式响应 chunk 中安全提取增量文本。

        支持：
          1. provider 配置的 response_map 路径
          2. 标准 OpenAI SSE: choices[0].delta.content
          3. 常见企业网关流式变体
        """
        provider_cfg = provider_cfg or {}
        response_map = provider_cfg.get('response_map', None)

        # 1) 显式 response_map（优先）
        if response_map and response_map.get('content_path'):
            val = LLMClient._get_by_path(data, response_map['content_path'])
            if isinstance(val, str):
                return val
            return ""

        # 2) 标准 OpenAI delta
        choices = data.get('choices', [])
        if choices and isinstance(choices, list):
            delta = choices[0].get('delta', {}) if isinstance(choices[0], dict) else {}
            content = delta.get('content', '') if isinstance(delta, dict) else ''
            if content:
                return content

        # 3) 自动检测流式变体
        for path in ['delta.content', 'content', 'data.content',
                      'data.reply', 'reply', 'text', 'data.text',
                      'data.delta.content']:
            val = LLMClient._get_by_path(data, path)
            if isinstance(val, str) and val:
                return val

        return ""


# ── 辅助函数（模块级别）──────────────────────────────────────

def _describe_keys(data: dict, max_depth: int = 2, _depth: int = 0) -> str:
    """
    递归描述 JSON 对象的键结构，用于错误诊断。
    只显示前两层，避免输出过长。
    """
    if not isinstance(data, dict) or _depth > max_depth:
        return type(data).__name__
    parts = []
    for k, v in data.items():
        if _depth < max_depth:
            parts.append(f"{k}:{_describe_keys(v, max_depth, _depth + 1)}")
        else:
            parts.append(k)
    return "{" + ", ".join(parts) + "}"


def _detect_error_content(text: str) -> str:
    """
    检测提取到的文本是否为网关错误信息（而非正常 LLM 回复）。

    企业网关在认证失败等场景下可能返回 HTTP 200 + 错误描述文本，
    需要识别这类情况并返回友好的错误诊断。

    返回: 空字符串表示不是错误；非空字符串为错误诊断信息。
    """
    if not text or not isinstance(text, str):
        return ""

    lower = text.lower()

    # 网关认证/授权错误模式
    auth_patterns = [
        ('apic.', 'APIC 错误码'),
        ('incorrect app authentication', '应用认证信息错误'),
        ('app not found', '应用未找到（appCode 无效）'),
        ('appcode', 'appCode 相关错误'),
        ('authentication information', '认证信息错误'),
        ('request_id=', '包含 request_id 的网关错误'),
    ]
    for pattern, desc in auth_patterns:
        if pattern in lower:
            return (
                f"企业网关返回错误（{desc}）：{text[:300]}。"
                f"请检查：1) 代理程序的 Config 中 appCode/busiSendInstNo 等认证字段是否正确 "
                f"2) 模型名称是否与网关支持的模型一致 "
                f"3) 网关服务是否正常运行。"
            )

    # 通用网关错误码模式 (如 ERR_xxx, SYS_xxx 等)
    import re as _re
    if _re.search(r'\b[A-Z]{2,8}[._-]\d{3,6}\b', text):
        return (
            f"企业网关返回错误码：{text[:300]}。"
            f"请确认网关认证配置和服务状态。"
        )

    return ""

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


def _parse_react_action(text: str) -> list[dict]:
    """从 LLM 输出中解析 react 协议的 tool_call JSON"""
    import re
    # 匹配 {"action":"...","args":{...}} 格式
    match = re.search(r'\{[^{}]*"action"\s*:\s*"(\w+)"\s*,\s*"args"\s*:\s*(\{[^}]+\})[^{}]*\}', text)
    if not match:
        return []
    try:
        name = match.group(1)
        args = json.loads(match.group(2))
        return [{"id": f"call_{name}", "name": name, "arguments": args}]
    except (json.JSONDecodeError, KeyError):
        return []
