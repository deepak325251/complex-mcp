import os
from abc import ABC, abstractmethod
from openai import AsyncClient
from fastmcp import Client as MCPClient
from typing import List, Dict, Any, Literal
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log
from collections import defaultdict
from functools import lru_cache
import asyncio
import json
import logging
import colorlog
import readline
import tiktoken

import sys
import argparse
import re
import ast

sys.path.append('.')

from client.utils import parse_tool, TOOL_START_SEQ, TOOL_STOP_SEQ
from client.rag import RAGEngine, ChromaRAG

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


@lru_cache(maxsize=32)
def get_encoding(model: str):
    # Non-OpenAI models (Claude, etc.) are never in tiktoken's registry, so
    # cl100k_base is the expected approximation -- not a warnable condition.
    if not str(model).startswith(("gpt-", "o1", "o3", "text-", "davinci", "curie")):
        return tiktoken.get_encoding("cl100k_base")
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str, model: str) -> int:
    if not text:
        return 0
    return len(get_encoding(model).encode(text))

class Toolbox:
    def __init__(self, tools: Dict[str, Dict[str, Any]] = {}, rag_cls = None, method: Literal["list_all", "provide", "rag", "fetch"] = "list_all", *args, **kwargs):
        self.tools = tools
        self.clients = {}
        self.servers = {}
        self.rag: RAGEngine | None = rag_cls() if rag_cls else None
        self.method = method
        # ETOM pseudo-execution: no world, no server. When on, call() returns a
        # schema-shaped pseudo output instead of POSTing to the live app, and
        # login/logout are short-circuited (see AgentClient). Grading is then the
        # tool DAG alone (benchmark/graph_judge).
        from client.pseudo_exec import is_enabled as _pseudo_enabled, PSEUDO_CACHE
        self.pseudo = _pseudo_enabled()
        self._pseudo_cache = PSEUDO_CACHE
        if self.pseudo:
            logger.info("[ETOM] pseudo-execution ON -- tools return schema-shaped "
                        "outputs; no world / no server is contacted.")

        if self.method == "rag" or self.method == "fetch":
            assert self.rag
            self.default_k = kwargs.get("default_k", 3)
        
        if self.method == "fetch":
            tools["retrieve_tools"] = {
                "tool_name": "retrieve_tools",
                "description": "As there are too many tools available, use this tool to find the most relevant tools based on your query and a requested number k.",
                "arguments": {
                    "query": {"type": "str", "description": "A description of the task or requirements used to find relevant tools (e.g. 'I need to add two numbers'; 'I want to know that time is it now')"},
                    "k": {"type": "int", "description": "Maximum number of the most relevant tools to return"}
                },
                "returns": {
                    "type": "list",
                    "description": "A list of up to k tools most relevant to the provided query"
                }
            }
    
    @retry(
        stop=stop_after_attempt(10),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def call(
        self,
        key_name: str,
        arguments: Dict[str, Any],
        session_id_dict: Dict[str, str] = {}
    ):
        if key_name not in self.tools:
            return {
                "status": "error",
                "output": f"This tool `{key_name}` doesn't exist."
            }
        if key_name == "retrieve_tools":
            try:
                return self.retrieve_tools(
                    query=arguments["query"],
                    k=arguments.get("k", self.default_k)
                )
            except Exception as e:
                return {
                    "status": "error",
                    "output": e.__str__()
                }
        tool = self.tools[key_name]
        if self.pseudo:
            # ETOM: no world, no session, no server -- return a schema-shaped
            # success so the agent proceeds through its plan structurally.
            from client.pseudo_exec import pseudo_output
            return pseudo_output(tool, arguments, self._pseudo_cache)
        tool_name = tool["tool_name"]
        server = tool["server"]
        url = server["url"]
        need_session = server["need_session"]

        if need_session:
            server_name = server["name"]
            if server_name not in session_id_dict:
                return {
                    "status": "failed",
                    "output": f"{server_name} has not been logged into yet."
                }
            session_id = session_id_dict[server_name]
            arguments["session_id"] = session_id

        if url not in self.clients:
            self.clients[url] = MCPClient(url)
        
        client = self.clients[url]
        try:
            async with client:
                result = (await client.call_tool(
                    name=tool_name,
                    arguments=arguments
                )).content[0].text
                return result
        except Exception as e:
            return {
                "status": "error",
                "output": e.__str__()
            }

    async def call_with_server(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any]
    ):
        server = self.servers[server_name]
        url = server["url"]

        if url not in self.clients:
            self.clients[url] = MCPClient(url)
        
        client = self.clients[url]
        try:
            async with client:
                result = (await client.call_tool(
                    name=tool_name,
                    arguments=arguments
                )).content[0].text
                return result
        except Exception as e:
            return {
                "status": "failed",
                "output": e.__str__()
            }.__str__()
    
    def __get_desc_of_one_tool(self, key_name: str):
        tool = self.tools[key_name]
        tool_desc = {
            "tool_name": key_name,
            "description": tool["description"],
            "arguments": tool["arguments"]
        }
        if "returns" in tool:
            tool_desc["returns"] = tool["returns"]
        return tool_desc
    
    def get_tool_descs(self, key_names: List[str]) -> str:
        tools_desc = [self.__get_desc_of_one_tool(key_name) for key_name in key_names if key_name in self.tools]

        return '\n'.join(map(lambda x: f"- {x}", tools_desc))
    
    @staticmethod
    def _json_schema_type(t: str) -> Dict[str, Any]:
        """Map a desc.json argument type string to a JSON-schema fragment."""
        t = (t or "").strip().lower()
        if t.startswith("array") or t.startswith("list"):
            return {"type": "array", "items": {"type": "string"}}
        if t in ("int", "integer"):
            return {"type": "integer"}
        if t in ("float", "number", "double"):
            return {"type": "number"}
        if t in ("bool", "boolean"):
            return {"type": "boolean"}
        if t in ("object", "dict"):
            return {"type": "object"}
        return {"type": "string"}

    def to_openai_schema(self, key_names: List[str]) -> List[Dict[str, Any]]:
        """Build native OpenAI function-calling tool schemas for the given tools."""
        schemas = []
        for key_name in key_names:
            if key_name not in self.tools:
                continue
            tool = self.tools[key_name]
            props = {}
            for arg_name, arg_spec in (tool.get("arguments") or {}).items():
                spec = arg_spec if isinstance(arg_spec, dict) else {}
                schema = self._json_schema_type(spec.get("type", "string"))
                if spec.get("description"):
                    schema["description"] = spec["description"]
                props[arg_name] = schema
            schemas.append({
                "type": "function",
                "function": {
                    "name": key_name,
                    "description": tool.get("description", "") or "",
                    "parameters": {"type": "object", "properties": props},
                },
            })
        return schemas

    def get_native_system_prompt(self) -> str:
        """System prompt for native function-calling mode (tools passed via the API,
        not described in text). No <tool> protocol."""
        return (
            "You are an autonomous AI assistant with access to a set of tools (functions). "
            "Use the provided tools by calling them directly through the function-calling interface "
            "to accomplish the user's task. There is no human available to answer questions, so never "
            "ask for clarification or confirmation and never wait for further input. Make reasonable "
            "assumptions, resolve ambiguity yourself, and drive the task to completion using the tools. "
            "When the task is finished (or you are certain it is unsolvable), reply with a short final "
            "summary and output [END]."
        )

    def get_system_prompt(self, discard_tools: bool = False):
        SYSTEM_PROMPT = (
            "You are an AI assistant with access to a set of tools (APIs). "
            f"When you need to use a tool, invoke it by outputting a JSON object enclosed by {TOOL_START_SEQ} and {TOOL_STOP_SEQ} in the following format:\n"
            f"{TOOL_START_SEQ}\n"
            "{\"name\": \"tool_name\", \"arguments\": {\"arg1\": value1, \"arg2\": value2, ...}}\n"
            f"{TOOL_STOP_SEQ}\n"
            "After you submit the tool call in this format, I will execute it and return the result to you. "
            "You operate autonomously: there is no human available to answer questions, so never ask for "
            "clarification or confirmation and never wait for further user input. Make reasonable assumptions, "
            "resolve ambiguity yourself, and drive the task to completion using the tools. When the task is "
            "finished (or you are certain it is unsolvable), output [END].\n"
            "Below is the list of available tools and their descriptions:\n"
        )
        if discard_tools:
            return SYSTEM_PROMPT

        if self.method == "list_all":
            tool_desc_list = [self.__get_desc_of_one_tool(key_name).__str__() for key_name in self.tools]
            SYSTEM_PROMPT += '\n'.join(map(lambda x: f"- {x}", tool_desc_list))
        elif self.method == "provide":
            SYSTEM_PROMPT += '${PROVIDE_TOOLS}'
        elif self.method == "rag":
            SYSTEM_PROMPT += '${CHOSEN_TOOLS}'
        elif self.method == "fetch":
            SYSTEM_PROMPT += self.__get_desc_of_one_tool("retrieve_tools").__str__() + '\n'
        else:
            raise NotImplementedError

        return SYSTEM_PROMPT
    
    def register_server(self, server_name: str, server_url: str, desc_path: str = None, use_sandbox: bool = False):
        if use_sandbox:
            assert desc_path, "An MCP server which use sandbox must provide a description file."
        
        self.servers[server_name] = {
            "url": server_url,
            "need_session": use_sandbox,
            "tools": []
        }

        if desc_path:
            """Optional, you can provide more LLM-friendly descriptions of MCP tools."""
            with open(desc_path) as f:
                desc = json.load(f)
                for tool_desc in desc:
                    assert "tool_name" in tool_desc and "description" in tool_desc
                    tool_name = tool_desc["tool_name"]

                    key_name = tool_name[:]
                    while key_name in self.tools:
                        key_name = f"{server_name}_{key_name}"
                    
                    self.servers[server_name]["tools"].append(key_name)
                    self.tools[key_name] = {**tool_desc, **{
                        "server": {
                            "name": server_name,
                            "url": server_url,
                            "need_session": use_sandbox
                        }
                    }}
                    if self.rag:
                        self.rag.write(
                            doc=f"({tool_name}) {tool_desc['description']}",
                            meta_data={
                                "key_name": key_name
                            }
                        )
        else:
            if server_name not in self.clients:
                self.clients[server_name] = MCPClient(server_url)
            client: MCPClient = self.clients[server_name]
            async def get_tools():
                async with client:
                    tools = await client.list_tools()
                    return tools
            tools = asyncio.run(get_tools())
            for tool in tools:
                tool_name = tool.name

                key_name = tool_name[:]
                while key_name in self.tools:
                    key_name = f"{server_name}_{key_name}"
                
                self.servers[server_name]["tools"].append(key_name)
                self.tools[key_name] = {
                    "tool_name": tool_name,
                    "description": tool.description,
                    "arguments": tool.inputSchema["properties"],
                    "returns": {
                        "type": tool.outputSchema["type"] if tool.outputSchema else "unknown"
                    },
                    "server": {
                        "name": server_name,
                        "url": server_url,
                        "need_session": use_sandbox
                    }
                }
                if self.rag:
                    self.rag.write(
                        doc=f"({tool_name}) {tool.description}",
                        meta_data={
                            "key_name": key_name
                        }
                    )
        
    def retrieve_tools(self, query: str, k: int | None = None) -> List[Dict[str, Any]]:
        assert self.rag, "RAG engine is required."
        if k is None:
            k = self.default_k
        tools_list = []
        results = self.rag.read(query=query, k=k)
        for result in results:
            key_name = result["meta_data"]["key_name"]
            tools_list.append(
                self.__get_desc_of_one_tool(key_name)
            )

        return tools_list

    def retrieve_tool_keys(self, query: str, k: int | None = None) -> List[str]:
        """Return the raw key_names of the top-k retrieved tools (for native mode)."""
        assert self.rag, "RAG engine is required."
        if k is None:
            k = self.default_k
        return [r["meta_data"]["key_name"] for r in self.rag.read(query=query, k=k)]


class ChatBackend(ABC):
    @abstractmethod
    async def chat(self, *_, **__) -> Dict[str, Any]:
        raise NotImplemented

class OpenAIBackend(ChatBackend):
    def __init__(self, model: str):
        super().__init__()
        self.model = model
        self.client = AsyncClient(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ["OPENAI_BASE_URL"]
        )
    
    @retry(
        stop=stop_after_attempt(1000),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 10000,
        extra_body: Dict[str, Any] = {}
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": max_tokens,
            **extra_body
        }
        resp = await self.client.chat.completions.create(**payload)

        _msg = resp.choices[0].message
        # In native function-calling mode the model may return tool_calls with
        # content=None; only require that *something* came back.
        assert _msg.content is not None or getattr(_msg, "tool_calls", None), \
            "Model returned neither content nor tool_calls"

        return resp

class ClaudeCodeBackend(ChatBackend):
    def __init__(self, model: str):
        super().__init__()
        self.model = model
        self.claude_bin = os.environ.get("CLAUDE_BIN", "claude")

    @staticmethod
    def _serialize_messages(messages: List[Dict[str, Any]]) -> tuple:
        system_msgs = [m["content"] for m in messages if m.get("role") == "system"]
        convo = [m for m in messages if m.get("role") != "system"]
        system_prompt = "\n\n".join(system_msgs) if system_msgs else None
        lines: List[str] = []
        for m in convo:
            role = "User" if m.get("role") == "user" else "Assistant"
            lines.append(f"[{role}]\n{m.get('content', '')}\n")
        lines.append("[Assistant]\n")
        return system_prompt, "\n".join(lines)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 10000,
        extra_body: Dict[str, Any] = {},
    ) -> Dict[str, Any]:
        system_prompt, prompt = self._serialize_messages(messages)

        cmd = [
            self.claude_bin,
            "-p",
            "--model", self.model,
            # stream-json surfaces the detail `json` collapses: per-message
            # `usage` with the prompt-cache breakdown, and `thinking` content
            # (streamed as thinking_delta events). --verbose + partial messages
            # are required to receive those events with -p.
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--dangerously-skip-permissions",
        ]

        # Write system prompt to a tempfile and reference via --system-prompt-file.
        # Inline `--system-prompt <huge>` hits OS ARG_MAX (~256KB on macOS) → silent exit-1.
        # Prior workaround (inline via stdin) made claude treat the system prompt as USER input,
        # causing Opus to refuse the <tool>{...}</tool> protocol as "pasted transcript".
        system_prompt_file = None
        if system_prompt:
            import tempfile
            tf = tempfile.NamedTemporaryFile(
                "w", suffix=".txt", delete=False, encoding="utf-8"
            )
            tf.write(system_prompt)
            tf.close()
            system_prompt_file = tf.name
            cmd += ["--system-prompt-file", system_prompt_file]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await proc.communicate(prompt.encode("utf-8"))
            if proc.returncode != 0:
                raise RuntimeError(
                    f"`claude` exited {proc.returncode}: {stderr_b.decode('utf-8', errors='replace')[:1000]}"
                )
        finally:
            if system_prompt_file:
                try:
                    os.unlink(system_prompt_file)
                except OSError:
                    pass

        # stream-json emits one JSON object per line. Accumulate the thinking
        # (streamed as thinking_delta), the final text + authoritative usage
        # (the terminal `result` event, whose usage carries the cache breakdown),
        # and the model's cost.
        content = ""
        usage_data: Dict[str, Any] = {}
        last_assistant_usage: Dict[str, Any] = {}
        cost_usd = 0.0
        reasoning_parts: list[str] = []
        reasoning_tokens = 0
        _saw_result = False
        for _line in stdout_b.decode("utf-8", errors="replace").splitlines():
            _line = _line.strip()
            if not _line:
                continue
            try:
                ev = json.loads(_line)
            except json.JSONDecodeError:
                continue
            etype = ev.get("type")
            if etype == "stream_event":
                delta = (ev.get("event") or {}).get("delta") or {}
                if delta.get("type") == "thinking_delta":
                    # NOTE: the claude-code CLI redacts thinking *text* (the
                    # `thinking` field is empty); only `estimated_tokens` is
                    # exposed. So we record that reasoning happened + its size,
                    # and keep any text if a future CLI ever surfaces it.
                    if delta.get("thinking"):
                        reasoning_parts.append(delta["thinking"])
                    reasoning_tokens += delta.get("estimated_tokens", 0) or 0
            elif etype == "assistant":
                _amsg = ev.get("message") or {}
                if _amsg.get("usage"):
                    last_assistant_usage = _amsg["usage"]
                for blk in _amsg.get("content") or []:
                    if isinstance(blk, dict) and blk.get("type") == "thinking" and blk.get("thinking"):
                        reasoning_parts.append(blk["thinking"])
            elif etype == "result":
                _saw_result = True
                content = ev.get("result") or content
                usage_data = ev.get("usage") or usage_data
                cost_usd = ev.get("total_cost_usd", cost_usd) or cost_usd
        if not _saw_result:
            raise RuntimeError(
                f"claude stream-json had no result event. First 500 bytes: {stdout_b[:500]!r}")
        # result.usage is authoritative (has the final output count), but can come
        # back empty on some fast paths -- fall back to the last assistant turn's
        # usage for the input/cache breakdown so cache accounting survives.
        if not (usage_data.get("input_tokens") or usage_data.get("cache_read_input_tokens")
                or usage_data.get("cache_creation_input_tokens")):
            for _k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                if last_assistant_usage.get(_k):
                    usage_data[_k] = last_assistant_usage[_k]
            usage_data.setdefault("output_tokens", last_assistant_usage.get("output_tokens", 0))

        # The claude CLI splits input across uncached + cached buckets; with
        # prompt caching on, `input_tokens` is only the small uncached remainder.
        # Keep the breakdown AND the summed total so cache read/creation are
        # recorded, not collapsed away.
        uncached_input = usage_data.get("input_tokens", 0) or 0
        cache_read = usage_data.get("cache_read_input_tokens", 0) or 0
        cache_creation = usage_data.get("cache_creation_input_tokens", 0) or 0
        input_tokens = uncached_input + cache_read + cache_creation
        output_tokens = usage_data.get("output_tokens", 0) or 0
        reasoning = "".join(reasoning_parts)

        stops = extra_body.get("stop") or []
        if isinstance(stops, str):
            stops = [stops]
        finish_reason = "stop"
        for s in stops:
            i = content.find(s)
            if i != -1:
                content = content[: i + len(s)]
                break

        if not content:
            content = " "

        resp = argparse.Namespace(
            usage=argparse.Namespace(
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                # Real breakdown (was collapsed/dropped before) so cache
                # read/creation are recorded, not reported as 0.
                uncached_input_tokens=uncached_input,
                cache_read_tokens=cache_read,
                cache_creation_tokens=cache_creation,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                # Extended-thinking size (text is redacted by the CLI, so this
                # count is the only reasoning signal available).
                reasoning_tokens=reasoning_tokens,
            ),
            choices=[
                argparse.Namespace(
                    message=argparse.Namespace(
                        content=content,
                        reasoning_content=reasoning or None,
                    ),
                    finish_reason=finish_reason,
                )
            ],
        )
        return resp


class HumanAnnotator(ChatBackend):
    def __init__(self):
        super().__init__()
    
    async def chat(self, *_, **__):
        content = input("$ ")
        resp = argparse.Namespace(
            usage=argparse.Namespace(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0
            ),
            choices=[argparse.Namespace(
                message=argparse.Namespace(
                    content=self.convert_func_calls(content)
                ),
                finish_reason="stop"
            )]
        )

        return resp
    
    def convert_func_calls(self, text: str):
        def replace_match(match):
            func_name = match.group(1)
            args_str = match.group(2)
            
            if not args_str.strip():
                arguments = {}
            else:
                try:
                    fake_call = f"fake_func({args_str})"
                    tree = ast.parse(fake_call, mode='eval')
                    call_node = tree.body
                    
                    if not isinstance(call_node, ast.Call):
                        raise ValueError("Invalid function call format")
                    
                    arguments = {}
                    for keyword in call_node.keywords:
                        key = keyword.arg
                        value = ast.literal_eval(keyword.value)
                        arguments[key] = value
                except Exception as e:
                    raise ValueError(f"Failed to parse arguments in '{args_str}': {e}")
            
            tool_dict = {
                "name": func_name,
                "arguments": arguments
            }
            json_str = json.dumps(tool_dict, ensure_ascii=False)
            return f'<tool> {json_str} </tool>'

        # 正则表达式匹配 func(...)
        pattern = r'(\w+)\(([^)]*)\)'
        result = re.sub(pattern, replace_match, text)
        return result


class AgentClient:
    def __init__(
        self,
        llm: OpenAIBackend,
        toolbox: Toolbox | None = None,
        system_prompt: str | None = None
    ):
        self.llm = llm
        self.toolbox = toolbox
        self.system_prompt = system_prompt
    
    def set_system_prompt(
        self,
        system_prompt: str
    ):
        self.system_prompt = system_prompt
    
    async def __login(self, env: Dict[str, Any], session_id_dict: Dict[str, Any], results: Dict[str, Any]):
        if getattr(self.toolbox, "pseudo", False):
            # ETOM: no server to log into. Hand every app a fake session so the
            # need_session gate in Toolbox.call is satisfied, then bail.
            if len(env["apps"]) > 0:
                system_app = "LightSystem"
                for app in [system_app] + [a for a in env["apps"] if a != system_app]:
                    session_id_dict[app] = f"pseudo-{app}"
                    results["old_apps"][app] = {}
                env["apps"] = [system_app] + [a for a in env["apps"] if a != system_app]
            return
        if len(env["apps"]) > 0:
            system_app = "LightSystem"
            login_info = await self.toolbox.call_with_server(
                server_name=system_app,
                tool_name="login",
                arguments={}
            )
            login_info: Dict[str, Any] = json.loads(login_info)
            session_info = login_info.pop("session_info")
            results["old_apps"][system_app] = session_info
            logger.info(f"Logged into the app {system_app}: {login_info}")
            session_id_dict[system_app] = login_info["session_id"]
            system_url = self.toolbox.servers[system_app]["url"]
            for app in env["apps"]:
                # The system app is logged in above (with a different signature — no os_cfg).
                # If a task's apps list also names it, skip it here so we never re-invoke its
                # login with an os_cfg it doesn't accept (which returns a non-JSON error string
                # and crashes the run). LightSystem is implicit; tasks should not list it.
                if app == system_app:
                    continue
                if app in self.toolbox.servers:
                    server = self.toolbox.servers[app]
                    assert server["need_session"]
                    login_info = await self.toolbox.call_with_server(
                        server_name=app,
                        tool_name="login",
                        arguments={
                            "os_cfg": {
                                "session_id": session_id_dict[system_app],
                                "url": system_url
                            }
                        }
                    )
                    
                    # print(login_info)
                    login_info: Dict[str, Any] = json.loads(login_info)
                    session_info = login_info.pop("session_info")
                    results["old_apps"][app] = session_info

                    logger.info(f"Logged into the app {app} : {login_info}")

                    session_id = login_info["session_id"]
                    session_id_dict[app] = session_id
                else:
                    raise RuntimeError(f"The app `{app}` has not been registered yet.")
            env["apps"] = [system_app] + env["apps"]
        
    async def __logout(self, env: Dict[str, Any], session_id_dict: Dict[str, Any], results: Dict[str, Any]):
        if getattr(self.toolbox, "pseudo", False):
            # ETOM: no server, no world snapshot to read back. Record empty
            # per-app state so downstream writers stay happy.
            for app in env["apps"]:
                results["apps"][app] = {}
            return
        for app in env["apps"]:
            if app in self.toolbox.servers:
                server = self.toolbox.servers[app]
                assert server["need_session"]
                session_id = session_id_dict[app]
                env_info = await self.toolbox.call_with_server(
                    server_name=app,
                    tool_name="logout",
                    arguments={
                        "session_id": session_id
                    }
                )
                results["apps"][app] = json.loads(env_info)
            else:
                raise RuntimeError(f"The app `{app}` has not been registered yet.")

    async def process_query(
        self,
        query: str,
        max_turns: int = 10,
        verbose: bool = False,
        stop_tag: str = None,
        env: Dict[str, Any] = {
            "apps": []
        },
        provide_tools: List[str] | None = None,
        native: bool = False
    ) -> str:
        assert (provide_tools is None) ^ (self.toolbox.method == "provide")

        messages = []
        output = []
        extra_body = {}
        session_id_dict = {}
        results = {}

        results["old_apps"] = {}
        results["apps"] = {}
        results["tool_cnt"] = defaultdict(lambda: defaultdict(int))

        cnt_without_tc = 0

        try:
            await self.__login(
                env=env,
                session_id_dict=session_id_dict,
                results=results
            )

            system_prompt = self.system_prompt
            if self.toolbox and native:
                # Native function-calling: pass tool schemas via the API instead of
                # describing them in text / using the <tool> protocol.
                system_prompt = self.toolbox.get_native_system_prompt()
                if self.toolbox.method == "rag":
                    key_names = self.toolbox.retrieve_tool_keys(query=query)
                elif self.toolbox.method == "provide":
                    key_names = list(provide_tools or [])
                else:
                    key_names = list(self.toolbox.tools.keys())
                extra_body["tools"] = self.toolbox.to_openai_schema(key_names)
                extra_body["tool_choice"] = "auto"
                print(f"Tool number: {len(self.toolbox.tools)} (native schemas: {len(extra_body['tools'])})")
            elif self.toolbox:
                extra_body["stop"] = TOOL_STOP_SEQ
                if self.toolbox.method == "rag":
                    system_prompt = system_prompt.replace(
                        "${CHOSEN_TOOLS}",
                        "\n".join(map(lambda x: f"- {x}", self.toolbox.retrieve_tools(query=query)))
                    )
                elif self.toolbox.method == "provide":
                    system_prompt = system_prompt.replace(
                        "${PROVIDE_TOOLS}",
                        self.toolbox.get_tool_descs(key_names=provide_tools)
                    )
                print(f"Tool number: {len(self.toolbox.tools)}")
            if system_prompt:
                messages.append({
                    "role": "system",
                    "content": system_prompt
                })
            messages.append({
                "role": "user",
                "content": query
            })

            prompt_token_num = 0
            llm_token_num = 0
            tool_token_num = 0
            token_model = getattr(self.llm, "model", "gpt-4o")

            # Real API usage (incl. prompt-cache) accumulated across turns. The
            # tiktoken counters above are estimates; these are the model's own.
            usage_acc = {"input_tokens": 0, "output_tokens": 0,
                         "cache_read_tokens": 0, "cache_creation_tokens": 0,
                         "reasoning_tokens": 0, "cost_usd": 0.0}

            def _accumulate_usage(u):
                usage_acc["input_tokens"] += getattr(u, "uncached_input_tokens",
                                                     getattr(u, "prompt_tokens", 0)) or 0
                usage_acc["output_tokens"] += getattr(u, "output_tokens",
                                                      getattr(u, "completion_tokens", 0)) or 0
                usage_acc["cache_read_tokens"] += getattr(u, "cache_read_tokens", 0) or 0
                usage_acc["cache_creation_tokens"] += getattr(u, "cache_creation_tokens", 0) or 0
                usage_acc["reasoning_tokens"] += getattr(u, "reasoning_tokens", 0) or 0
                usage_acc["cost_usd"] += getattr(u, "cost_usd", 0.0) or 0.0

            for idx in range(max_turns):
                if native:
                    resp = await self.llm.chat(messages, extra_body=extra_body)
                    m = resp.choices[0].message
                    usage = resp.usage
                    # Every turn re-sends the growing history, so total prompt
                    # cost is the sum of per-turn input, not just turn 0.
                    prompt_token_num += usage.prompt_tokens
                    _accumulate_usage(usage)

                    # Preserve the model's reasoning (extended thinking) when the
                    # backend surfaces it, so it lands as the step's reasoning.
                    reasoning_text = getattr(m, "reasoning_content", None)
                    if reasoning_text:
                        output.append(reasoning_text)

                    text = m.content or ""
                    tool_calls = getattr(m, "tool_calls", None) or []

                    if text:
                        llm_token_num += count_tokens(text, token_model)
                        if verbose:
                            print(text)
                        output.append(text)

                    assistant_msg = {"role": "assistant", "content": m.content}
                    if tool_calls:
                        assistant_msg["tool_calls"] = [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments or "{}",
                                },
                            }
                            for tc in tool_calls
                        ]
                    messages.append(assistant_msg)

                    if not tool_calls:
                        cnt_without_tc += 1
                        if stop_tag and text.strip().endswith(stop_tag):
                            break
                        if cnt_without_tc >= 2:
                            break
                        continue

                    cnt_without_tc = 0
                    for tc in tool_calls:
                        tool_name = tc.function.name
                        try:
                            arguments = json.loads(tc.function.arguments or "{}")
                        except Exception:
                            arguments = {}

                        # Re-emit in <tool> text form so downstream trajectory parsing works.
                        tool_text = (
                            f"{TOOL_START_SEQ} "
                            f"{json.dumps({'name': tool_name, 'arguments': arguments}, ensure_ascii=False)} "
                            f"{TOOL_STOP_SEQ}"
                        )
                        output.append(tool_text)
                        llm_token_num += count_tokens(tool_text, token_model)

                        tool_resp = await self.toolbox.call(
                            tool_name, arguments, session_id_dict=session_id_dict
                        )
                        try:
                            tool_resp_obj = json.loads(tool_resp) if isinstance(tool_resp, str) else tool_resp
                            status = tool_resp_obj["status"]
                        except Exception:
                            status = "ok"
                        results["tool_cnt"][tool_name][status] += 1

                        format_tool_resp = f"<response>\n{tool_resp}\n</response>"
                        tool_token_num += count_tokens(format_tool_resp, token_model)
                        if verbose:
                            print(format_tool_resp)
                        output.append(format_tool_resp)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": tool_resp if isinstance(tool_resp, str)
                                       else json.dumps(tool_resp, ensure_ascii=False),
                        })
                    continue

                resp = await self.llm.chat(messages)
                msg: str = resp.choices[0].message.content
                usage = resp.usage

                # Accumulate every turn (see native branch above).
                prompt_token_num += usage.prompt_tokens
                _accumulate_usage(usage)

                _reasoning = getattr(resp.choices[0].message, "reasoning_content", None)
                if _reasoning:
                    output.append(_reasoning)

                if self.toolbox and resp.choices[0].finish_reason == "stop" and \
                    TOOL_START_SEQ in msg and TOOL_STOP_SEQ not in msg:
                    msg += TOOL_STOP_SEQ
                
                if TOOL_STOP_SEQ in msg:
                    msg = msg[: msg.find(TOOL_STOP_SEQ) + len(TOOL_STOP_SEQ)]
                llm_token_num += count_tokens(msg, token_model)
                
                if verbose:
                    print(msg)

                output.append(msg)
                messages.append({
                    "role": "assistant",
                    "content": msg
                })
                
                if msg.endswith(TOOL_STOP_SEQ) and self.toolbox:
                    tool_calling_req = parse_tool(msg)
                    cnt_without_tc *= 0
                    if tool_calling_req is None:
                        tool_resp = {
                            "status": "error",
                            "output": (
                                "Incorrect tool call format. (Not a json or missing key words) "
                                "Please provide 'name' and 'arguments' (If needed), e.g.: "
                                "{'name': 'tool_name', 'arguments': {'arg1': 'val1', 'arg2': 'val2', ...} }"
                            )
                        }
                    elif "name" not in tool_calling_req:
                        tool_resp = {
                            "status": "error",
                            "output": (
                                "Tool call format is missing required fields. "
                                "Please provide 'name' and 'arguments' (If needed), e.g.: "
                                "{'name': 'tool_name', 'arguments': {'arg1': 'val1', 'arg2': 'val2', ...} }"
                            )
                        }
                    else:
                        tool_name = tool_calling_req["name"]
                        arguments = tool_calling_req.get("arguments", {})
                        tool_resp = (await self.toolbox.call(
                            tool_name,
                            arguments,
                            session_id_dict=session_id_dict
                        ))
                        try:
                            tool_resp_dict = json.loads(tool_resp) if isinstance(tool_resp, str) else tool_resp
                            status = tool_resp_dict["status"]
                        except Exception as e:
                            status = "ok"
                        results["tool_cnt"][tool_name][status] += 1

                    format_tool_resp = f"<response>\n{tool_resp}\n</response>"
                    tool_token_num += count_tokens(format_tool_resp, token_model)

                    if verbose:
                        print(format_tool_resp)

                    output.append(format_tool_resp)
                    messages.append({
                        "role": "user",
                        "content": format_tool_resp
                    })
                else:
                    cnt_without_tc += 1
                    if stop_tag and msg.strip().endswith(stop_tag):
                        break # quit
                    if cnt_without_tc >= 5:
                        break # quit
            results["tokens"] = {
                "prompt": prompt_token_num,
                "llm": llm_token_num,
                "tool": tool_token_num
            }
            # Real API usage incl. prompt-cache read/creation and cost — the
            # cache/thinking accounting the trajectory previously reported as 0.
            results["usage"] = {
                "input_tokens": usage_acc["input_tokens"],
                "output_tokens": usage_acc["output_tokens"],
                "cache_read_tokens": usage_acc["cache_read_tokens"],
                "cache_creation_tokens": usage_acc["cache_creation_tokens"],
                "reasoning_tokens": usage_acc["reasoning_tokens"],
                "cost_usd": round(usage_acc["cost_usd"], 6),
            }

            results["tool_cnt"] = {key: dict(val) for key, val in results["tool_cnt"].items()}
            results["output"] = '\n'.join(output)
        finally:
            await self.__logout(
                env=env,
                session_id_dict=session_id_dict,
                results=results
            )

        return results