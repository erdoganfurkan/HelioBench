"""Drive HelioAI and collect what it leaves behind.

Three things in HelioAI shape this file, all of them measured rather than assumed:

- `import helioai.config` runs its validation at module scope and raises when the default
  provider has no key, so every environment variable is pinned *before* the first import.
- `config.py` calls `load_dotenv(find_dotenv(usecwd=True))`, which walks up from the working
  directory. It cannot be turned off, but it runs with `override=False`, so a variable this
  adapter sets first wins. Anything it does not set can still be inherited, which is what
  `preflight` warns about.
- `stream_chat` takes the LLM client as an argument. That is the seam used to count tokens
  without patching the agent.

The search index is passed explicitly and pinned in the run header. Up to HelioAI 0.3,
`HELIOAI_DATA_DIR` moved sessions and workspaces but not the index; from 0.4.0 (`2c6e856`) it
moves the index, the catalogues and the profile too, so without `--index-dir` the agent looks
for its index inside the benchmark's empty storage root and `preflight` refuses. Either way
the index is 83 000 products built against a live upstream inventory, and two runs against
two different indexes are not comparable.

Everything else that changes what the agent does — named experiments, a second model for a
sub-agent role, a judging backend, vision, MCP servers, the hybrid search, the loop's
limits — is pinned to HelioAI's own default before import, and moved only by `--agent-env`,
which lands in the header. Until 2026-09-28 those were inherited from the shell or a `.env`
and recorded nowhere: two arms that differed by an experiment printed the same header.
"""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from heliobench.retry import attach_backoff
from heliobench.trace import Trace
from heliobench.usage import UnmeteredProvider, add_own_client_usage, attach_token_meter

# Providers whose model is not selectable through the environment: HelioAI hardcodes it as a
# dataclass default, so it has to be set on the settings object after import.
_MODEL_ENV = {
    "azure": "AZURE_OPENAI_DEPLOYMENT",
    "opencode": "HELIOAI_OPENCODE_MODEL",
    "ollama": "HELIOAI_OLLAMA_MODEL",
}


# How much of each tool result the trace keeps. 4000 until 2026-09-28, which cut a search
# result before its accepted id often enough that the report had to count such runs apart;
# the limit now travels in every `tool_output` event, so a reader never has to know which
# version of the harness wrote a trace to know where its cut was.
_TOOL_OUTPUT_LIMIT = 16000

# Variables that change the agent's behaviour, at HelioAI's own defaults. Set rather than
# unset: an unset variable is filled from any discoverable `.env` (`load_dotenv` runs with
# `override=False`), so only a value this adapter writes first is a value it controls.
_PINNED_BEHAVIOUR = {
    "HELIOAI_EXPERIMENTS": "",
    "HELIOAI_ROLE_MODELS": "",
    "HELIOAI_JUDGMENT_BACKEND": "null",
    "HELIOAI_VISION_ENABLED": "0",
    "HELIOAI_MCP_SERVERS": "",
    "HELIOAI_RAG_HYBRID": "1",
    "HELIOAI_MAX_ITERATIONS": "10",
    "HELIOAI_MAX_OUTPUT_TOKENS": "",
}

# Written by the adapter itself from its own arguments; `--agent-env` may not move them.
_ADAPTER_OWNED = frozenset(
    {"HELIOAI_DATA_DIR", "HELIOAI_SESSION_DB", "HELIOAI_LLM_PROVIDER", "HELIOAI_LOG_FORMAT"}
)

_SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "HEADERS", "USERS")


def parse_agent_env(pairs: list[str] | None) -> dict[str, str]:
    """`["HELIOAI_EXPERIMENTS=final_answer", ...]` → a dict, refusing what it must not move.

    Only `HELIOAI_*` names are taken, so a credential can never be passed this way and end up
    in a report header; and not the ones the adapter derives from its own arguments.
    """
    out: dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(f"--agent-env expects KEY=VALUE, got {pair!r}")
        key, value = pair.split("=", 1)
        key = key.strip()
        if not key.startswith("HELIOAI_"):
            raise ValueError(f"--agent-env only sets HELIOAI_* variables, not {key!r}")
        if key in _ADAPTER_OWNED or key in _MODEL_ENV.values():
            raise ValueError(f"{key} is set by the adapter from its own flags")
        out[key] = value
    return out


def redacted_env(environ=None) -> dict[str, str]:
    """Every `HELIOAI_*` variable the agent will read, with anything credential-like masked."""
    environ = os.environ if environ is None else environ
    return {
        k: ("<set>" if any(m in k for m in _SECRET_MARKERS) and environ[k] else environ[k])
        for k in sorted(environ)
        if k.startswith("HELIOAI_")
    }


def _model_text(result) -> str:
    """The text the model was shown for a tool result.

    Up to HelioAI 0.3 the registry returned that string. From 0.4.0 (`e6a2e7f`) it returns a
    `ToolResult`, whose `for_llm()` is the model's text; `str()` of it is a dataclass repr,
    and the 0.4.0 candidate sweep of 2026-09-23 recorded that repr in all 47 traces —
    retrievable ids inside a Python dict literal, and a truncation flag measured on the
    wrong string.
    """
    if isinstance(result, str):
        return result
    for_llm = getattr(result, "for_llm", None)
    if callable(for_llm):
        return str(for_llm())
    return str(result)


# The recorder of the run whose task is executing, or None outside any run. HelioAI keeps its
# own per-session state (`helioai.workspace`) in context variables for the same reason: with
# `--jobs` above one every run shares the process, and the asyncio task context is the only
# thing that tells one run's tool call from another's.
_RECORDER: ContextVar[Callable[[str, dict | None, str], None] | None] = ContextVar(
    "heliobench_tool_recorder", default=None
)


class _ToolOutputDispatcher:
    """One wrapper on the registry for every run in flight, each writing to its own trace.

    The first version of the recorder wrapped `registry.call_tool` per run and put the
    original back on exit. The registry is a module-level singleton, so two concurrent runs
    nested their wrappers, both traces received both runs' tool output, and the first run to
    finish unwrapped the second — which then recorded nothing. That corrupted exactly the
    events the n1 rank and truncation metrics read. The wrapper is now installed once, by the
    first run to start, and dispatches to whichever recorder the current task context holds;
    the last run to finish removes it, so the registry is left as it was found.
    """

    def __init__(self) -> None:
        self._original = None
        self._had_own = False
        self._active = 0

    def acquire(self, registry) -> None:
        if self._active == 0:
            original = registry.call_tool

            async def dispatching(name, arguments=None, **kwargs):
                result = await original(name, arguments, **kwargs)
                record = _RECORDER.get()
                if record is not None:
                    record(name, arguments, result)
                return result

            # `call_tool` is normally the class's method reached through the instance; putting
            # a bound method back into the instance dict would work and would not be "as found".
            self._had_own = "call_tool" in vars(registry)
            self._original = original
            registry.call_tool = dispatching
        self._active += 1

    def release(self, registry) -> None:
        self._active -= 1
        if self._active == 0:
            if self._had_own:
                registry.call_tool = self._original
            else:
                del registry.call_tool
            self._original = None


_DISPATCHER = _ToolOutputDispatcher()


@contextmanager
def _recording_tool_output(trace: Trace, t0: float, registry=None):
    """Append what each tool actually returned to the trace, which HelioAI's events elide.

    A `tool_result` event carries a summary: five products found by `search_parameters`
    become the string `"[5 items]"`. That is enough to see that a search happened and not
    enough to say why an answer was wrong — whether the right identifier was never retrieved,
    or was retrieved and passed over. Those are different defects with different fixes, and
    telling them apart without this meant replaying the run.

    The registry is the seam, for the same reason the token meter wraps the SDK client: it
    returns the exact string the model was shown, so nothing in the agent is patched and
    nothing about the run changes. It is HelioAI's singleton unless a test passes its own:
    CI installs no agent, and the concurrency this guards against must be tested there.

    Must be entered inside the task that will run the agent, so the recorder lands in that
    task's context and nowhere else.
    """
    if registry is None:
        from helioai.tools.registry import registry

    def record(name: str, arguments: dict | None, result) -> None:
        text = _model_text(result)
        trace.events.append(
            {
                "event": "tool_output",
                "data": {
                    "name": name,
                    "arguments": arguments,
                    "result": text[:_TOOL_OUTPUT_LIMIT],
                    "truncated": len(text) > _TOOL_OUTPUT_LIMIT,
                    "limit": _TOOL_OUTPUT_LIMIT,
                },
                "t": round(time.monotonic() - t0, 3),
            }
        )

    _DISPATCHER.acquire(registry)
    token = _RECORDER.set(record)
    try:
        yield
    finally:
        _RECORDER.reset(token)
        _DISPATCHER.release(registry)


def low_disk(where: Path, need_gb: float = 2.0, jobs: int = 1) -> str | None:
    """Complain when the agent has too little room to write, or None when it has enough.

    A sweep that fills the disk dies mid-flight with the quota already spent, and it does not
    die saying "disk": it surfaces as a sqlite error inside the agent loop, several frames
    from anything about storage. HelioAI seeds each session's workspace from the speasy
    inventory — measured at ~37 MB for a session that loads data and a few kilobytes for one
    that does not — so a full sweep needs room for a workspace per run, over a gigabyte.

    Each concurrent job seeds its own workspace at the same time, so the floor rises by half
    a gigabyte per job beyond the first.
    """
    where = Path(where)
    need_gb = need_gb + 0.5 * max(jobs - 1, 0)
    probe = where if where.exists() else where.parent
    free_gb = shutil.disk_usage(probe).free / 1e9
    if free_gb >= need_gb:
        return None
    return (
        f"{free_gb:.1f} GB free where the agent writes ({where}) — a sweep seeds a workspace "
        f"per run and needs more than {need_gb:.1f} GB at jobs={jobs}"
    )


def _discoverable_dotenv(start: Path) -> Path | None:
    """The `.env` HelioAI's own discovery would find walking up from `start`."""
    for d in [start, *start.parents]:
        candidate = d / ".env"
        if candidate.is_file():
            return candidate
    return None


class HelioAIAgent:
    """HelioAI as a benchmark subject."""

    name = "helioai"

    def __init__(
        self,
        data_dir: Path,
        *,
        provider: str = "azure",
        model: str | None = None,
        index_dir: Path | None = None,
        restricted: bool = True,
        user_id: str = "heliobench",
        jobs: int = 1,
        agent_env: dict[str, str] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.provider = provider
        self.model = model
        self.index_dir = Path(index_dir) if index_dir else None
        self.restricted = restricted
        self.user_id = user_id
        self.jobs = jobs
        self.agent_env = dict(agent_env or {})
        self._imported = False

    def _pin_env(self) -> None:
        """Fix every variable that moves a result, before HelioAI reads any of them."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        os.environ["HELIOAI_DATA_DIR"] = str(self.data_dir)
        os.environ["HELIOAI_SESSION_DB"] = str(self.data_dir / "sessions.db")
        os.environ["HELIOAI_LLM_PROVIDER"] = self.provider
        os.environ["HELIOAI_LOG_FORMAT"] = "json"
        if self.model and self.provider in _MODEL_ENV:
            os.environ[_MODEL_ENV[self.provider]] = self.model
        os.environ.update(_PINNED_BEHAVIOUR)
        os.environ.update(self.agent_env)

    def _load(self):
        """Import HelioAI once, env already pinned, and apply the settings it will not
        take from the environment."""
        self._pin_env()
        import helioai.tools.setup  # noqa: F401  — registers the 17 tools; without it, empty
        from helioai.config import settings

        if self.model and self.provider not in _MODEL_ENV:
            cfg = getattr(settings.llm, self.provider, None)
            if cfg is None:
                raise ValueError(f"unknown provider {self.provider!r}")
            cfg.model = self.model
        if self.index_dir is not None:
            settings.rag.chroma_dir = self.index_dir
        self._imported = True
        return settings

    def describe(self) -> dict:
        """The arm's identity, for the report header."""
        settings = self._load()
        import helioai

        cfg = getattr(settings.llm, self.provider, None)
        return {
            "agent": self.name,
            "agent_version": helioai.__version__,
            "agent_ref": os.environ.get("HELIOBENCH_AGENT_REF"),
            "provider": self.provider,
            "model": getattr(cfg, "model", None)
            or os.environ.get(_MODEL_ENV.get(self.provider, ""), ""),
            "temperature": getattr(cfg, "temperature", None),
            "max_output_tokens": getattr(cfg, "max_output_tokens", None),
            "max_iterations": settings.agent.max_iterations,
            "restricted": self.restricted,
            "index_dir": str(settings.rag.chroma_dir),
            "index_size": self._index_size(),
            **self._behaviour(settings),
        }

    def _behaviour(self, settings) -> dict:
        """What HelioAI parsed out of the variables that change what it does.

        Read back from `settings` rather than from the environment: the header must say what
        the agent will do, and a value HelioAI does not understand is one it ignores.
        Attributes a given HelioAI version lacks are left out, not guessed.
        """
        out: dict = {"agent_env": dict(self.agent_env), "helioai_env": redacted_env()}
        agent = getattr(settings, "agent", None)
        if hasattr(agent, "experiments"):
            out["experiments"] = sorted(agent.experiments)
        if hasattr(agent, "role_models"):
            out["role_models"] = {r: list(v) for r, v in sorted(agent.role_models.items())}
        judgment = getattr(settings, "judgment", None)
        if judgment is not None:
            out["judgment"] = {"backend": judgment.backend, "model": judgment.model}
        vision = getattr(settings, "vision", None)
        if vision is not None:
            out["vision"] = {"enabled": vision.enabled, "model": vision.model}
        mcp = getattr(settings, "mcp", None)
        if mcp is not None:
            out["mcp_servers"] = bool(getattr(mcp, "servers_json", ""))
        if hasattr(getattr(settings, "rag", None), "hybrid_enabled"):
            out["rag_hybrid"] = settings.rag.hybrid_enabled
        return out

    @staticmethod
    def _backoff_policy() -> dict:
        """Record-only when HelioAI retries its own provider calls, harness backoff otherwise.

        HelioAI wraps every SDK call in `call_with_retry` (4 attempts, honouring Retry-After)
        in the versions that have it; stacking the harness's 5 inside it made one rate limit
        up to twenty requests.
        """
        try:
            from helioai.core.llm.base import call_with_retry  # noqa: F401
        except ImportError:
            return {}
        return {"attempts": 1}

    def _role_models(self) -> dict:
        """Sub-agent roles HelioAI runs on a client of their own, as it parsed them."""
        from helioai.config import settings

        return dict(getattr(settings.agent, "role_models", {}) or {})

    def _index_size(self) -> int:
        """Number of indexed products, or -1 when the index cannot be opened."""
        try:
            from helioai.tools.rag import _collection_only

            return int(_collection_only().count())
        except Exception:
            return -1

    def preflight(self) -> list[str]:
        """Everything that would make the numbers meaningless, checked before spending money."""
        problems: list[str] = []
        try:
            self._load()
        except Exception as e:
            return [f"HelioAI will not import: {type(e).__name__}: {e}"]

        # The hallucination metric fails open: `unknown_ids` returns "nothing unknown" when
        # the index is unreachable, so an absent index scores as a flawless run.
        n = self._index_size()
        hint = "" if self.index_dir else " — pass --index-dir"
        if n < 0:
            problems.append(
                f"the Chroma index is unreachable — invented ids would score as valid{hint}"
            )
        elif n == 0:
            problems.append(f"the Chroma index is empty — invented ids would score as valid{hint}")

        problems += self._client_problems()

        low = low_disk(self.data_dir, jobs=self.jobs)
        if low:
            problems.append(low)

        env_file = _discoverable_dotenv(Path.cwd())
        if env_file is not None:
            problems.append(
                f"a .env is discoverable at {env_file} and HelioAI reads it; every variable "
                "this adapter does not pin can be inherited from it"
            )
        return problems

    def _client_problems(self) -> list[str]:
        """Build every client a run will build, so a missing key fails here and not in it.

        Four stored sweeps — 154 runs — died on their first provider call: two with
        `*_API_KEY is not set`, two with a provider rejecting the request outright. Building
        the client is free and catches the first kind, for the lead and for every role
        `HELIOAI_ROLE_MODELS` sends elsewhere; the meter is attached too, because a client
        it cannot count is one whose cost the report would publish as zero. The second kind
        needs a request: `verify --canary`.
        """
        from helioai.core.llm.factory import build_llm_client

        targets = [(self.provider, None, "lead")]
        targets += [(p, m, role) for role, (p, m) in sorted(self._role_models().items())]
        problems = []
        for provider, model, who in targets:
            try:
                llm = (
                    build_llm_client(provider, model=model) if model else build_llm_client(provider)
                )
            except Exception as e:
                problems.append(
                    f"the {who} client ({provider}) cannot be built: {type(e).__name__}: {e}"
                )
                continue
            if who == "lead":
                try:
                    attach_token_meter(llm)
                except UnmeteredProvider as e:
                    problems.append(str(e))
        return problems

    async def canary(self) -> str:
        """Send one tiny request through the lead's client, exactly as a run would build it.

        Costs a few dozen tokens. It is the only check that sees what a provider does with a
        real request — the 400 `MissingSessionID` that zeroed the 2026-09-09 sweep was
        visible on the first call and on no configuration file.
        """
        self._load()
        from helioai.core.llm.base import Message, close_sdk_client
        from helioai.core.llm.factory import build_llm_client

        llm = build_llm_client(self.provider)
        meter = attach_token_meter(llm)
        try:
            await llm.chat([Message(role="user", content="Reply with the single word: ok")], [])
        finally:
            await close_sdk_client(getattr(llm, "_client", None))
        u = meter.usage
        return f"ok ({u.prompt} prompt + {u.completion} completion tokens)"

    def seed(self, workdir: Path, fixture: Path | None, session_id: str) -> str:
        """Point a session at `workdir` and pre-fill it, so the run is replayable offline.

        `stream_chat` reuses an existing workspace label verbatim, and `get_timeseries`
        consults the session datastore before the network. Seeding the manifest is therefore
        the whole offline story — no request interception anywhere.

        The session row must exist before its workspace can be recorded: `set_workspace_dir`
        is an UPDATE, and on a missing row it silently changes nothing.
        """
        from helioai.core.session import store
        from helioai.workspace import user_home

        label = workdir.name
        target = user_home(self.user_id) / "workspace" / label
        target.mkdir(parents=True, exist_ok=True)
        if fixture is not None:
            shutil.copytree(fixture, target, dirs_exist_ok=True)

        store.save(self.user_id, session_id, [])
        store.set_workspace_dir(self.user_id, session_id, label)
        return label

    async def run(
        self,
        prompt: str,
        workdir: Path,
        task_id: str = "",
        *,
        fixture: Path | None = None,
        session_id: str | None = None,
    ) -> Trace:
        """Answer one prompt and return the run's trace."""
        env = self.describe()
        from helioai.core.llm.base import close_sdk_client
        from helioai.core.llm.factory import build_llm_client
        from helioai.core.session import store
        from helioai.provenance import read_ledger
        from helioai.workspace import user_home

        workdir = Path(workdir)
        session_id = session_id or workdir.name
        label = self.seed(workdir, fixture, session_id)
        session_dir = user_home(self.user_id) / "workspace" / label

        trace = Trace(task_id=task_id or label, prompt=prompt, agent=self.name, env=env)
        llm = build_llm_client(self.provider)
        meter = attach_token_meter(llm)

        t0 = time.monotonic()
        attach_backoff(llm, trace, t0, **self._backoff_policy())
        try:
            from helioai.core.agent_loop import stream_chat

            with _recording_tool_output(trace, t0):
                async for ev in stream_chat(
                    llm, self.user_id, session_id, prompt, restricted=self.restricted
                ):
                    trace.events.append({**ev, "t": round(time.monotonic() - t0, 3)})
                    name, data = ev.get("event"), ev.get("data") or {}
                    if name == "reply":
                        trace.reply = data.get("text", "")
                    elif name == "artifact":
                        trace.artifacts.append(data)
                    elif name == "error":
                        trace.error = data.get("message", "unknown agent error")
        except Exception as e:
            trace.error = f"{type(e).__name__}: {e}"
        finally:
            trace.wall_s = round(time.monotonic() - t0, 3)
            trace.tokens = meter.usage
            add_own_client_usage(trace.tokens, trace.events, self._role_models())
            await close_sdk_client(getattr(llm, "_client", None))
            store.reset(self.user_id, session_id)

        trace.ledger = read_ledger(session_dir)
        return trace
