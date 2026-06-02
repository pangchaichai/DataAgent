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
from dataclasses import dataclass, field
from typing import Generator, Optional

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
class ReportDegradedResult:
    """
    report_text 不可用时的降级输出。
    包含纯数值结构 + 占位说明，不调用外部 LLM。
    """
    message: str
    numerical_data: dict = field(default_factory=dict)
    degraded: bool = True


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
        with open(config_path, encoding='utf-8') as f:
            config = yaml.safe_load(f)
        self.cfg = config.get('llm', {})
        self.sql_gen_cfg = self.cfg.get('sql_gen', {})
        self.report_cfg = self.cfg.get('report_text', {})
        self.providers = {
            'enterprise_internal': self.cfg.get('enterprise_internal', {}),
            'deepseek': self.cfg.get('deepseek', {}),
        }

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

    def classify_intent(self, user_input: str, skill_registry: list[dict]) -> tuple[Optional[str], LLMResponse]:
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

        name = result.text.strip().upper()
        if name == 'NONE':
            return None, result
        # 验证返回的技能名称在注册表中
        valid_names = {s['name'] for s in skill_registry}
        return name if name in valid_names else None, result

    # ── 流式接口 ──────────────────────────────────────────────

    def stream_sql_gen(self, prompt: str, schema_context: str = "") -> Generator[str, None, LLMResponse]:
        """
        SQL 生成流式输出（SSE）。

        每次 yield 一段增量文本，最后通过 return 返回完整 LLMResponse。
        前端通过 SSE 消费，实现逐字显示。
        """
        full_prompt = f"{schema_context}\n\n用户问题：{prompt}" if schema_context else prompt
        primary = self.sql_gen_cfg.get('primary', 'enterprise_internal')

        chunks, result = self._call_streaming(
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
                chunks2, result2 = self._call_streaming(
                    fallback, full_prompt,
                    system="你是一个 SQL 专家。只返回 SQL，不要解释。",
                    timeout=self.sql_gen_cfg.get('timeout', 30),
                    max_tokens=self.sql_gen_cfg.get('max_tokens', 2000),
                )
                for chunk in chunks2:
                    yield chunk
                return result2

        return result

    # ── 底层 HTTP 调用 ────────────────────────────────────────

    def _call(self, provider_name: str, prompt: str,
              system: str = "", timeout: int = 30, max_tokens: int = 2000) -> LLMResponse:
        """同步调用 LLM，返回 LLMResponse。"""
        provider = self.providers.get(provider_name)
        if not provider:
            return LLMResponse(success=False, endpoint=provider_name, model="",
                               text="", error=f"未配置 LLM 提供方: {provider_name}")

        url = provider.get('url', '')
        model = provider.get('model', '')
        api_key = os.environ.get(f"{provider_name.upper()}_API_KEY") or provider.get('api_key', '')

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
                text = data['choices'][0]['message']['content']
                usage = data.get('usage', {})
                return LLMResponse(
                    success=True, text=text, endpoint=provider_name, model=model,
                    token_count=usage.get('total_tokens', 0), elapsed_ms=elapsed_ms,
                )
            elif resp.status_code in (401, 403):
                return LLMResponse(success=False, endpoint=provider_name, model=model,
                                   text="", error="api_key")
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

    def _call_streaming(self, provider_name: str, prompt: str,
                        system: str = "", timeout: int = 30, max_tokens: int = 2000):
        """流式调用 LLM，返回 (chunks_generator, LLMResponse)。"""
        provider = self.providers.get(provider_name)
        if not provider:
            return iter([]), LLMResponse(success=False, endpoint=provider_name, model="",
                                         text="", error=f"未配置 LLM 提供方: {provider_name}")

        url = provider.get('url', '')
        model = provider.get('model', '')
        api_key = os.environ.get(f"{provider_name.upper()}_API_KEY") or provider.get('api_key', '')

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
                        delta = data['choices'][0].get('delta', {})
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
