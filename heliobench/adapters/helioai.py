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

`HELIOAI_DATA_DIR` moves sessions and workspaces but **not** the search index: `chroma_dir`
is frozen from the package's own data root at import time and no environment variable
overrides it. The index is therefore passed explicitly and pinned in the run header, which is
what it should be anyway — it is 83 000 products built over ten minutes against a live
upstream inventory, and two runs against two different indexes are not comparable.
"""

from __future__ import annotations

import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

from heliobench.trace import Trace
from heliobench.usage import attach_token_meter

# Providers whose model is not selectable through the environment: HelioAI hardcodes it as a
# dataclass default, so it has to be set on the settings object after import.
_MODEL_ENV = {
    "azure": "AZURE_OPENAI_DEPLOYMENT",
    "opencode": "HELIOAI_OPENCODE_MODEL",
    "ollama": "HELIOAI_OLLAMA_MODEL",
}


_TOOL_OUTPUT_LIMIT = 4000


@contextmanager
def _recording_tool_output(trace: Trace, t0: float):
    """Append what each tool actually returned to the trace, which HelioAI's events elide.

    A `tool_result` event carries a summary: five products found by `search_parameters`
    become the string `"[5 items]"`. That is enough to see that a search happened and not
    enough to say why an answer was wrong — whether the right identifier was never retrieved,
    or was retrieved and passed over. Those are different defects with different fixes, and
    telling them apart without this meant replaying the run.

    The registry is the seam, for the same reason the token meter wraps the SDK client: it
    returns the exact string the model was shown, so nothing in the agent is patched and
    nothing about the run changes.
    """
    from helioai.tools.registry import registry

    original = registry.call_tool

    async def recording(name, arguments=None, **kwargs):
        result = await original(name, arguments, **kwargs)
        text = result if isinstance(result, str) else str(result)
        trace.events.append(
            {
                "event": "tool_output",
                "data": {
                    "name": name,
                    "arguments": arguments,
                    "result": text[:_TOOL_OUTPUT_LIMIT],
                    "truncated": len(text) > _TOOL_OUTPUT_LIMIT,
                },
                "t": round(time.monotonic() - t0, 3),
            }
        )
        return result

    registry.call_tool = recording
    try:
        yield
    finally:
        registry.call_tool = original


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
    ) -> None:
        self.data_dir = Path(data_dir)
        self.provider = provider
        self.model = model
        self.index_dir = Path(index_dir) if index_dir else None
        self.restricted = restricted
        self.user_id = user_id
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
            "provider": self.provider,
            "model": getattr(cfg, "model", None)
            or os.environ.get(_MODEL_ENV.get(self.provider, ""), ""),
            "temperature": getattr(cfg, "temperature", None),
            "max_output_tokens": getattr(cfg, "max_output_tokens", None),
            "max_iterations": settings.agent.max_iterations,
            "restricted": self.restricted,
            "index_dir": str(settings.rag.chroma_dir),
            "index_size": self._index_size(),
        }

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
        if n < 0:
            problems.append("the Chroma index is unreachable — invented ids would score as valid")
        elif n == 0:
            problems.append("the Chroma index is empty — invented ids would score as valid")

        env_file = _discoverable_dotenv(Path.cwd())
        if env_file is not None:
            problems.append(
                f"a .env is discoverable at {env_file} and HelioAI reads it; every variable "
                "this adapter does not pin can be inherited from it"
            )
        return problems

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
            await close_sdk_client(getattr(llm, "_client", None))
            store.reset(self.user_id, session_id)

        trace.ledger = read_ledger(session_dir)
        return trace
