#!/usr/bin/env python3
"""Minimal immutable API facade for the isolated oMLX inference experiment."""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Protocol

import mlx.core as mx
import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi import Request as FastAPIRequest
from omlx.api.openai_models import ChatCompletionRequest, CompletionRequest

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
MODEL_ROOT = ROOT / "models"
ALLOWED = {
    ("GET", "/health"),
    ("GET", "/api/status"),
    ("GET", "/v1/models"),
    ("GET", "/v1/models/status"),
    ("POST", "/v1/completions"),
    ("POST", "/v1/chat/completions"),
}
NATIVE_CONTEXT_WINDOW = 262_144
ALLOWED_CONTEXT_WINDOWS = frozenset({32_768, NATIVE_CONTEXT_WINDOW})
MAX_OUTPUT_TOKENS = 8_192


class _MtpSafetyViolation(RuntimeError):
    """Abort decoding when speculative state cannot be proven recoverable."""


class _HasMaxTokens(Protocol):
    max_tokens: int | None


@dataclass(slots=True)
class _RequestOutputBudget:
    request: _HasMaxTokens
    requested_max_tokens: int | None
    max_prompt_tokens: int = 0


_REQUEST_OUTPUT_BUDGET: ContextVar[_RequestOutputBudget | None] = ContextVar(
    "qwen_omlx_request_output_budget", default=None
)


def _validate_prompt_budget(
    prompt_tokens: int,
    *,
    context_window: int,
) -> None:
    effective_context = min(int(context_window), NATIVE_CONTEXT_WINDOW)
    if int(prompt_tokens) >= effective_context:
        raise HTTPException(
            status_code=400,
            detail="Prompt leaves no room for generation in the active context window",
        )


def _bounded_max_tokens(
    requested: int | None,
    configured: int,
    *,
    prompt_tokens: int | None,
    context_window: int = NATIVE_CONTEXT_WINDOW,
) -> int:
    """Clamp generation to the active and native total sequence budgets."""
    requested_or_default = configured if requested is None else int(requested)
    if requested_or_default <= 0:
        raise HTTPException(status_code=400, detail="max_tokens must be positive")

    effective_context = min(int(context_window), NATIVE_CONTEXT_WINDOW)
    remaining = (
        effective_context - int(prompt_tokens)
        if prompt_tokens is not None
        else effective_context
    )
    if remaining <= 0:
        raise HTTPException(
            status_code=400,
            detail="Prompt leaves no room for generation in the active context window",
        )
    return min(requested_or_default, configured, MAX_OUTPUT_TOKENS, remaining)


def _max_cache_position(cache: Any) -> int | None:
    """Return the greatest scalar leaf-cache offset in a singleton MTP path."""
    positions: list[int] = []
    pending = list(cache) if isinstance(cache, (list, tuple)) else [cache]
    seen: set[int] = set()
    while pending:
        entry = pending.pop()
        if entry is None or id(entry) in seen:
            continue
        seen.add(id(entry))
        if isinstance(entry, (list, tuple)):
            pending.extend(entry)
            continue
        children = getattr(entry, "caches", None)
        if children is not None:
            try:
                pending.extend(list(children))
            except TypeError:
                pass
        offset = getattr(entry, "offset", None)
        if type(offset) is int:
            positions.append(offset)
        elif offset is not None:
            # BatchKVCache is the only array-offset family admitted onto this
            # profile's guarded path. Its host `_idx` is exact for compact
            # singleton rows and a conservative upper bound with left padding,
            # avoiding a GPU synchronization. Other array-offset families can
            # use `_idx`/`_offset` as a ring or resident-window counter (false
            # low), so read their real offset or fail closed instead.
            buffered = getattr(entry, "_idx", None)
            if type(entry).__name__ == "BatchKVCache" and type(buffered) is int:
                positions.append(buffered)
            elif int(getattr(offset, "size", 0) or 0) > 0:
                try:
                    positions.append(int(mx.max(offset).item()))
                except Exception:
                    try:
                        positions.append(int(offset.max().item()))
                    except Exception:
                        continue
    return max(positions) if positions else None


def _bounded_mtp_draft_depth(
    desired_depth: int,
    *,
    sequence_tokens: int,
    emitted_tokens: int,
    queued_tokens: int,
    max_output_tokens: int,
    context_window: int,
) -> int:
    """Bound the next speculative chain by output and positional room.

    ``sequence_tokens`` contains the prompt plus outputs already emitted.
    ``queued_tokens`` are confirmed outputs that will be emitted before the
    next verify forward. A depth-``k`` cycle can emit those ``k`` drafts plus
    one final target token, so both budgets reserve that final slot.
    """
    effective_context = min(int(context_window), NATIVE_CONTEXT_WINDOW)
    # A verify with k drafts can commit k accepted drafts plus one final
    # target token. Reserve that final slot here; depth zero is the ordinary
    # one-token step used when exactly one output/position remains.
    remaining_output = (
        int(max_output_tokens) - int(emitted_tokens) - int(queued_tokens) - 1
    )
    remaining_positions = (
        effective_context - int(sequence_tokens) - int(queued_tokens) - 1
    )
    return max(
        0,
        min(int(desired_depth), remaining_output, remaining_positions),
    )


@contextmanager
def _request_output_scope(request: _HasMaxTokens) -> Iterator[_RequestOutputBudget]:
    """Bind output admission only while the upstream endpoint counts prompt."""
    budget = _RequestOutputBudget(
        request=request,
        requested_max_tokens=request.max_tokens,
    )
    token = _REQUEST_OUTPUT_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _REQUEST_OUTPUT_BUDGET.reset(token)


def _record_prompt_tokens(prompt_tokens: int, *, context_window: int) -> None:
    """Write the safe output ceiling directly onto this concrete request."""
    budget = _REQUEST_OUTPUT_BUDGET.get()
    if budget is None:
        raise RuntimeError("completion request is missing its output-budget scope")
    budget.max_prompt_tokens = max(
        int(budget.max_prompt_tokens),
        int(prompt_tokens),
    )
    budget.request.max_tokens = _bounded_max_tokens(
        budget.requested_max_tokens,
        MAX_OUTPUT_TOKENS,
        prompt_tokens=budget.max_prompt_tokens,
        context_window=context_window,
    )


def _install_total_context_guard(server_module: Any, context_window: int) -> None:
    """Bind prompt validation to the explicit request output limit."""
    active_context = int(context_window)
    if active_context not in ALLOWED_CONTEXT_WINDOWS:
        raise RuntimeError("request guard context must be 32768 or native 262144")
    server_module._qwen_secure_context_window = active_context
    if getattr(server_module, "_qwen_secure_total_context_guard", False):
        return
    upstream_validate = server_module.validate_context_window

    def validate_total_context(
        num_prompt_tokens: int, model_id: str | None = None
    ) -> None:
        active_context = int(server_module._qwen_secure_context_window)
        upstream_validate(num_prompt_tokens, model_id)
        _validate_prompt_budget(
            num_prompt_tokens,
            context_window=active_context,
        )
        _record_prompt_tokens(
            num_prompt_tokens,
            context_window=active_context,
        )

    server_module.validate_context_window = validate_total_context
    server_module._qwen_secure_total_context_guard = True


def _install_request_rebinding_guard(server_module: Any) -> None:
    """Keep output admission attached if upstream replaces a chat request."""
    name = "_preprocess_markitdown_files_for_llm"
    if getattr(server_module, "_qwen_secure_request_rebinding_guard", False):
        expected = getattr(
            server_module, "_qwen_secure_request_rebinding_function", None
        )
        if getattr(server_module, name, None) is not expected:
            raise RuntimeError("request rebinding guard identity drifted")
        return

    upstream_preprocess = getattr(server_module, name)

    async def preprocess_with_output_budget(request: Any) -> Any:
        result = await upstream_preprocess(request)
        if result is request:
            return result
        budget = _REQUEST_OUTPUT_BUDGET.get()
        if budget is None or budget.request is not request:
            raise RuntimeError(
                "upstream replaced a completion request outside its budget scope"
            )
        # Preserve any ceiling already established if upstream ever moves the
        # copy after prompt validation. In today's flow validation follows the
        # copy, and rebinding makes that validation mutate the object actually
        # consumed by sampling/generation.
        result.max_tokens = request.max_tokens
        budget.request = result
        return result

    setattr(server_module, name, preprocess_with_output_budget)
    server_module._qwen_secure_request_rebinding_function = (
        preprocess_with_output_budget
    )
    server_module._qwen_secure_request_rebinding_guard = True


def _install_mtp_position_guard(
    context_window: int,
    *,
    mtp_batch: Any | None = None,
) -> None:
    """Keep every target/MTP forward inside the active positional window."""
    if mtp_batch is None:
        from omlx.patches.mlx_lm_mtp import batch_generator as mtp_batch

    active_context = int(context_window)
    if active_context not in ALLOWED_CONTEXT_WINDOWS:
        raise RuntimeError("MTP guard context must be 32768 or native 262144")
    mtp_batch._qwen_secure_context_window = active_context
    if getattr(mtp_batch, "_qwen_secure_position_guard", False):
        expected = getattr(mtp_batch, "_qwen_secure_guarded_functions", None)
        names = (
            "_call_backbone",
            "_post_init_mtp",
            "_chain_next_drafts",
            "_run_verify_cycle_chain",
            "_materialize_mtp_boundary_emit",
            "_prepare_mtp_state_for_next",
            "_mtp_next",
            "_prepare_mtp_batch_state_for_next",
            "_mtp_batch_next",
            "_feed_next_main_to_standard",
            "_park_mtp_to_standard",
            "_handoff_mtp_for_late_join",
            "_reconcile_mtp_to_standard",
            "_reconcile_mtp_batch_to_standard",
        )
        if (
            not isinstance(expected, dict)
            or any(getattr(mtp_batch, name, None) is not expected.get(name) for name in names)
        ):
            raise RuntimeError("MTP position guard identity drifted after installation")
        return
    if getattr(mtp_batch, "_omlx_mtp_patched", False) is False:
        # The batch patch is normally installed during model load. Applying it
        # here makes the safety wrappers independent of that ordering.
        if not mtp_batch.apply():
            raise RuntimeError("cannot install the MTP batch position guard")

    original_call_backbone = mtp_batch._call_backbone
    original_post_init_mtp = mtp_batch._post_init_mtp
    original_chain_next_drafts = mtp_batch._chain_next_drafts
    original_verify_cycle_chain = mtp_batch._run_verify_cycle_chain
    original_materialize_boundary = mtp_batch._materialize_mtp_boundary_emit
    original_prepare_single = mtp_batch._prepare_mtp_state_for_next
    original_mtp_next = mtp_batch._mtp_next
    original_prepare_batch = mtp_batch._prepare_mtp_batch_state_for_next
    original_mtp_batch_next = mtp_batch._mtp_batch_next
    original_feed_standard = mtp_batch._feed_next_main_to_standard
    original_park_standard = mtp_batch._park_mtp_to_standard
    original_late_join_handoff = mtp_batch._handoff_mtp_for_late_join
    original_reconcile_single = mtp_batch._reconcile_mtp_to_standard
    original_reconcile_batch = mtp_batch._reconcile_mtp_batch_to_standard

    def _abort_recoverable_fallback(call: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return call(*args, **kwargs)
        except mtp_batch._MtpStepFallback as exc:
            # The pinned runtime catches this type inside GenerationBatch.next
            # and resumes ordinary decoding. Once an MTP dispatch has begun,
            # upstream cannot prove that target/head caches, token processors,
            # queue state, and RNG are untouched, so never permit that catch.
            raise _MtpSafetyViolation("MTP dispatch requested unsafe fallback") from exc

    def guarded_prepare_single(gen_batch: Any) -> Any:
        return _abort_recoverable_fallback(original_prepare_single, gen_batch)

    def guarded_mtp_next(gen_batch: Any, state: Any) -> Any:
        return _abort_recoverable_fallback(original_mtp_next, gen_batch, state)

    def guarded_prepare_batch(gen_batch: Any) -> Any:
        return _abort_recoverable_fallback(original_prepare_batch, gen_batch)

    def guarded_mtp_batch_next(gen_batch: Any, state: Any) -> Any:
        return _abort_recoverable_fallback(original_mtp_batch_next, gen_batch, state)

    def _require_mtp_handoff(call: Any, *args: Any) -> bool:
        try:
            handed_off = call(*args)
        except Exception as exc:
            raise _MtpSafetyViolation("MTP standard handoff raised") from exc
        if handed_off is not True:
            raise _MtpSafetyViolation("MTP standard handoff failed")
        return True

    def guarded_feed_standard(gen_batch: Any, state: Any) -> bool:
        return _require_mtp_handoff(original_feed_standard, gen_batch, state)

    def guarded_park_standard(gen_batch: Any, state: Any) -> bool:
        return _require_mtp_handoff(original_park_standard, gen_batch, state)

    def guarded_late_join_handoff(gen_batch: Any, state: Any) -> bool:
        return _require_mtp_handoff(original_late_join_handoff, gen_batch, state)

    def guarded_reconcile_single(gen_batch: Any, state: Any) -> bool:
        try:
            reconciled = original_reconcile_single(gen_batch, state)
        except Exception as exc:
            raise _MtpSafetyViolation("MTP singleton reconciliation raised") from exc
        if reconciled is not True:
            raise _MtpSafetyViolation("MTP singleton reconciliation failed")
        return True

    def guarded_reconcile_batch(gen_batch: Any) -> bool:
        try:
            reconciled = original_reconcile_batch(gen_batch)
        except Exception as exc:
            raise _MtpSafetyViolation("MTP batch reconciliation raised") from exc
        if reconciled is not True:
            raise _MtpSafetyViolation("MTP batch reconciliation failed")
        return True

    def guarded_call_backbone(
        model: Any,
        inputs: Any,
        prompt_cache: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        cache_position = _max_cache_position(prompt_cache)
        input_tokens = int(inputs.shape[1])
        active_context = min(
            int(mtp_batch._qwen_secure_context_window),
            NATIVE_CONTEXT_WINDOW,
        )
        if cache_position is None:
            raise _MtpSafetyViolation(
                "MTP target cache position is unavailable"
            )
        if int(cache_position) + input_tokens > active_context:
            raise _MtpSafetyViolation(
                "MTP target forward would exceed the active position budget"
            )
        result = original_call_backbone(
            model,
            inputs,
            prompt_cache,
            *args,
            **kwargs,
        )
        final_position = _max_cache_position(prompt_cache)
        if final_position is None or int(final_position) > active_context:
            raise _MtpSafetyViolation(
                "MTP target forward violated the active position budget"
            )
        return result

    def guarded_post_init_mtp(gen_batch: Any) -> None:
        # MTP initialization confirms two output tokens and folds the second
        # into the head history. With only one slot left, use the ordinary
        # decoder so neither cache speculates beyond the admitted sequence.
        remaining_output = int(gen_batch.max_tokens[0]) - int(
            gen_batch._num_tokens[0]
        )
        active_context = min(
            int(mtp_batch._qwen_secure_context_window),
            NATIVE_CONTEXT_WINDOW,
        )
        cache_position = _max_cache_position(gen_batch.prompt_cache)
        if cache_position is None:
            raise _MtpSafetyViolation(
                "MTP target cache position is unavailable during initialization"
            )
        remaining_positions = active_context - int(cache_position)
        if min(remaining_output, remaining_positions) < 2:
            # Prompt priming may have built a large head cache during prefill;
            # no MTP state will consume it on this one-token standard path.
            mtp_batch._prompt_priming.drop_ctx(gen_batch.model)
            return
        original_post_init_mtp(gen_batch)
        state = getattr(gen_batch, "_omlx_mtp_state", None)
        if state is not None:
            head_position = _max_cache_position(state.mtp_cache)
            if (
                head_position is None
                or int(head_position) > active_context
                or int(state.hist_offset) > active_context
            ):
                raise _MtpSafetyViolation(
                    "MTP head initialization exceeded the active position budget"
                )

    def guarded_chain_next_drafts(
        gen_batch: Any,
        state: Any,
        hidden_rows: Any,
        committed: Any,
        prev_buf: Any,
    ) -> None:
        controller = state.controller
        desired = controller.cur if controller is not None else state.depth
        pending_materialized = int(
            getattr(state, "_qwen_secure_pending_materialized_token", 0)
        )
        safe_depth = _bounded_mtp_draft_depth(
            desired,
            sequence_tokens=len(gen_batch.tokens[0]),
            emitted_tokens=int(gen_batch._num_tokens[0]),
            queued_tokens=len(state.queue) + pending_materialized,
            max_output_tokens=int(gen_batch.max_tokens[0]),
            context_window=int(mtp_batch._qwen_secure_context_window),
        )
        # The head cache can be independently primed to the prompt boundary.
        # This fold first appends every committed row, then a depth-k chain can
        # append k-1 more rows. Bound k by the remaining head positions after
        # accounting for the committed fold.
        active_context = min(
            int(mtp_batch._qwen_secure_context_window),
            NATIVE_CONTEXT_WINDOW,
        )
        committed_count = int(committed.shape[0])
        actual_head_position = _max_cache_position(state.mtp_cache)
        if actual_head_position is None:
            raise _MtpSafetyViolation(
                "MTP head cache position is unavailable"
            )
        # Boundary materialization can call this routine a second time while
        # an earlier speculative head chain is still present. Use the real
        # cache offset (and conservatively the logical history if larger).
        head_position = max(int(actual_head_position), int(state.hist_offset))
        if head_position + committed_count > active_context:
            raise _MtpSafetyViolation(
                "MTP head fold would exceed the active position budget"
            )
        head_room_after_fold = (
            active_context - head_position - committed_count
        )
        max_head_depth = max(0, head_room_after_fold + 1)
        safe_depth = min(safe_depth, max_head_depth)
        if controller is not None:
            saved_depth = controller.cur
            controller.cur = safe_depth
        else:
            saved_depth = state.depth
            state.depth = safe_depth
        try:
            original_chain_next_drafts(
                gen_batch,
                state,
                hidden_rows,
                committed,
                prev_buf,
            )
            actual_depth = int(state.drafts.shape[0]) if state.drafts is not None else 0
            final_head_position = _max_cache_position(state.mtp_cache)
            if actual_depth != safe_depth:
                raise _MtpSafetyViolation(
                    "MTP drafter ignored the context-limited depth"
                )
            if (
                final_head_position is None
                or int(final_head_position) > active_context
                or int(state.hist_offset) > active_context
            ):
                raise _MtpSafetyViolation(
                    "MTP head forward violated the active position budget"
                )
        finally:
            if controller is not None:
                controller.cur = saved_depth
            else:
                state.depth = saved_depth

    def guarded_verify_cycle_chain(gen_batch: Any, state: Any) -> None:
        draft_count = int(state.drafts.shape[0]) if state.drafts is not None else 0
        # The verify forward itself covers next_main + drafts. The final
        # sampled token is not forwarded until a later cycle, but it can be
        # emitted immediately, so reserve it in both positional/output checks.
        projected_position = len(gen_batch.tokens[0]) + draft_count + 1
        remaining_output = int(gen_batch.max_tokens[0]) - int(
            gen_batch._num_tokens[0]
        )
        active_context = min(
            int(mtp_batch._qwen_secure_context_window),
            NATIVE_CONTEXT_WINDOW,
        )
        cache_position = _max_cache_position(gen_batch.prompt_cache)
        if (
            projected_position > active_context
            or draft_count + 1 > remaining_output
            or cache_position is None
            or int(cache_position) + draft_count + 1 > active_context
        ):
            raise _MtpSafetyViolation(
                "MTP verify would exceed the active position/output budget"
            )
        original_verify_cycle_chain(gen_batch, state)
        final_target_position = _max_cache_position(gen_batch.prompt_cache)
        final_head_position = _max_cache_position(state.mtp_cache)
        if (
            final_target_position is None
            or int(final_target_position) > active_context
            or final_head_position is None
            or int(final_head_position) > active_context
        ):
            raise _MtpSafetyViolation(
                "MTP verify cycle violated the active cache-position budget"
            )

    def guarded_materialize_boundary(gen_batch: Any, state: Any) -> None:
        active_context = min(
            int(mtp_batch._qwen_secure_context_window),
            NATIVE_CONTEXT_WINDOW,
        )
        remaining_output = int(gen_batch.max_tokens[0]) - int(
            gen_batch._num_tokens[0]
        )
        cache_position = _max_cache_position(gen_batch.prompt_cache)
        if (
            len(gen_batch.tokens[0]) + 1 > active_context
            or len(state.queue) + 1 > remaining_output
            or cache_position is None
            or int(cache_position) + 1 > active_context
        ):
            # The optimization would append an extra confirmed token. Skipping
            # it preserves correctness; normal MTP queue draining finishes the
            # admitted request without that paged-boundary snapshot shortcut.
            return
        state._qwen_secure_pending_materialized_token = 1
        try:
            # Replace, rather than stack onto, the speculative head chain built
            # by the ordinary verify commit just before this optimization.
            mtp_batch._mtp_head_trim_to(state.mtp_cache, state.hist_offset)
            trimmed_head_position = _max_cache_position(state.mtp_cache)
            if (
                trimmed_head_position is None
                or int(trimmed_head_position) != int(state.hist_offset)
            ):
                raise _MtpSafetyViolation(
                    "MTP boundary head trim did not reach committed history"
                )
            original_materialize_boundary(gen_batch, state)
            final_target_position = _max_cache_position(gen_batch.prompt_cache)
            final_head_position = _max_cache_position(state.mtp_cache)
            if (
                final_target_position is None
                or int(final_target_position) > active_context
                or final_head_position is None
                or int(final_head_position) > active_context
            ):
                raise _MtpSafetyViolation(
                    "MTP boundary materialization violated the position budget"
                )
        finally:
            try:
                delattr(state, "_qwen_secure_pending_materialized_token")
            except AttributeError:
                pass

    mtp_batch._call_backbone = guarded_call_backbone
    mtp_batch._post_init_mtp = guarded_post_init_mtp
    mtp_batch._chain_next_drafts = guarded_chain_next_drafts
    mtp_batch._run_verify_cycle_chain = guarded_verify_cycle_chain
    mtp_batch._materialize_mtp_boundary_emit = guarded_materialize_boundary
    mtp_batch._prepare_mtp_state_for_next = guarded_prepare_single
    mtp_batch._mtp_next = guarded_mtp_next
    mtp_batch._prepare_mtp_batch_state_for_next = guarded_prepare_batch
    mtp_batch._mtp_batch_next = guarded_mtp_batch_next
    mtp_batch._feed_next_main_to_standard = guarded_feed_standard
    mtp_batch._park_mtp_to_standard = guarded_park_standard
    mtp_batch._handoff_mtp_for_late_join = guarded_late_join_handoff
    mtp_batch._reconcile_mtp_to_standard = guarded_reconcile_single
    mtp_batch._reconcile_mtp_batch_to_standard = guarded_reconcile_batch
    mtp_batch._qwen_secure_guarded_functions = {
        "_call_backbone": guarded_call_backbone,
        "_post_init_mtp": guarded_post_init_mtp,
        "_chain_next_drafts": guarded_chain_next_drafts,
        "_run_verify_cycle_chain": guarded_verify_cycle_chain,
        "_materialize_mtp_boundary_emit": guarded_materialize_boundary,
        "_prepare_mtp_state_for_next": guarded_prepare_single,
        "_mtp_next": guarded_mtp_next,
        "_prepare_mtp_batch_state_for_next": guarded_prepare_batch,
        "_mtp_batch_next": guarded_mtp_batch_next,
        "_feed_next_main_to_standard": guarded_feed_standard,
        "_park_mtp_to_standard": guarded_park_standard,
        "_handoff_mtp_for_late_join": guarded_late_join_handoff,
        "_reconcile_mtp_to_standard": guarded_reconcile_single,
        "_reconcile_mtp_batch_to_standard": guarded_reconcile_batch,
    }
    mtp_batch._qwen_secure_position_guard = True


def build_app() -> FastAPI:
    if os.environ.get("OMLX_SECURE_ENTRYPOINT") != "1":
        raise RuntimeError("secure entrypoint marker is missing")
    from omlx.logging_config import configure_file_logging
    import omlx.server as server_module
    from omlx.server import _server_state, app as upstream_app
    from omlx.server import init_server
    from omlx.settings import burst_decode_env, init_settings

    settings = init_settings(base_path=STATE)
    settings.auth.api_key = (STATE / "api-key").read_text(encoding="utf-8").strip()
    settings.auth.secret_key = (STATE / "secret-key").read_text(encoding="utf-8").strip()
    if not settings.auth.api_key or not settings.auth.secret_key:
        raise RuntimeError("owner-only API/session secret files must be non-empty")
    if os.environ.get("QWEN_OMLX_BENCHMARK_NO_CACHE") == "1":
        settings.cache.enabled = False
        print("benchmark: oMLX prefix/SSD cache disabled", flush=True)

    # No exposed route may mutate configuration, and even an upstream lifecycle
    # regression must not serialize the in-memory secrets into settings.json.
    def refuse_persistence() -> None:
        raise RuntimeError("settings persistence is disabled in ornith-omlx")

    settings.save = refuse_persistence  # type: ignore[method-assign]
    errors = settings.validate()
    if errors:
        raise RuntimeError("; ".join(errors))
    if settings.server.host != "127.0.0.1" or settings.server.port != 8086:
        raise RuntimeError("secure profile must bind to 127.0.0.1:8086")
    if settings.mcp.config_path or settings.mcp.expose_tools:
        raise RuntimeError("MCP must be disabled")
    if settings.integrations.markitdown_enabled or settings.integrations.markitdown_expose_model:
        raise RuntimeError("MarkItDown must be disabled")
    if settings.server.distributed_inference_enabled:
        raise RuntimeError("distributed inference must be disabled")
    active_context_window = int(settings.sampling.max_context_window)
    if active_context_window not in ALLOWED_CONTEXT_WINDOWS:
        raise RuntimeError("active context must be 32768 or the native 262144")
    if int(settings.sampling.max_context_window_policy or 0) != active_context_window:
        raise RuntimeError("context policy must match the active context")
    if settings.sampling.max_tokens != MAX_OUTPUT_TOKENS:
        raise RuntimeError("configured output default must remain 8192 tokens")

    # The upstream release validates prompt length and generation length
    # separately and treats a client-provided max_tokens as higher priority than
    # the configured value. Local route wrappers bind a safe value directly to
    # each request before any deferred response body starts; speculative MTP
    # depth then consumes only real output and positional headroom.
    _install_total_context_guard(server_module, active_context_window)
    _install_request_rebinding_guard(server_module)
    _install_mtp_position_guard(active_context_window)

    for key, value in burst_decode_env(settings.server.burst_decode_mode).items():
        os.environ[key] = value

    level = getattr(logging, settings.server.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger("omlx").setLevel(level)
    configure_file_logging(
        log_dir=settings.logging.get_log_dir(settings.base_path),
        level=settings.server.log_level,
        include_request_id=True,
        retention_days=settings.logging.retention_days,
    )

    scheduler_config = settings.to_scheduler_config()
    if settings.cache.enabled:
        scheduler_config.paged_ssd_cache_dir = str((STATE / "cache").resolve())
        scheduler_config.paged_ssd_cache_max_size = (
            settings.cache.get_ssd_cache_max_size_bytes(STATE)
        )
        scheduler_config.hot_cache_max_size = settings.cache.get_hot_cache_max_size_bytes()
    else:
        scheduler_config.paged_ssd_cache_dir = None
        scheduler_config.paged_ssd_cache_max_size = 0
        scheduler_config.hot_cache_max_size = 0
    total_mem = mx.device_info().get("memory_size", 0)
    if total_mem > 0:
        mx.set_cache_limit(total_mem)

    init_server(
        model_dirs=[str(MODEL_ROOT.resolve())],
        scheduler_config=scheduler_config,
        api_key=settings.auth.api_key,
        global_settings=settings,
    )
    # Downloader/uploader/quantizer helpers are initialized internally by the
    # upstream server, but no route can reach them. Drop the references anyway
    # so the experiment retains only inference-serving capabilities.
    _server_state.hf_downloader = None
    _server_state.ms_downloader = None
    _server_state.hf_uploader = None
    _server_state.oq_manager = None

    inference_routes = {
        ("POST", "/v1/completions"),
        ("POST", "/v1/chat/completions"),
    }
    passthrough_routes = ALLOWED - inference_routes
    selected = []
    for route in upstream_app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if path and any((method, path) in passthrough_routes for method in methods):
            selected.append(route)

    facade = FastAPI(
        title="ornith-omlx isolated inference API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        routes=selected,
        lifespan=server_module.lifespan,
        # Route isolation must not discard upstream's typed API errors. In
        # particular, memory-guard rejections need their structured HTTP 400
        # body rather than becoming a generic facade 500.
        exception_handlers=dict(upstream_app.exception_handlers),
    )

    @facade.post("/v1/completions")
    async def create_bounded_completion(
        request: CompletionRequest,
        http_request: FastAPIRequest,
        verified: bool = Depends(server_module.verify_api_key),
    ) -> Any:
        with _request_output_scope(request):
            return await server_module.create_completion(
                request,
                http_request,
                verified,
            )

    @facade.post("/v1/chat/completions")
    async def create_bounded_chat_completion(
        request: ChatCompletionRequest,
        http_request: FastAPIRequest,
        verified: bool = Depends(server_module.verify_api_key),
    ) -> Any:
        with _request_output_scope(request):
            return await server_module.create_chat_completion(
                request,
                http_request,
                verified,
            )

    found = [
        (method, route.path)
        for route in facade.routes
        if getattr(route, "path", None)
        for method in (getattr(route, "methods", None) or set())
    ]
    if set(found) != ALLOWED or len(found) != len(ALLOWED):
        raise RuntimeError(
            "secure route allowlist mismatch or duplicate: "
            f"expected={sorted(ALLOWED)}, found={sorted(found)}"
        )
    return facade


def main() -> None:
    expected_home = (STATE / "home").resolve()
    if Path.home().resolve() != expected_home:
        raise RuntimeError(f"runtime HOME must be isolated at {expected_home}")
    app = build_app()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=8086,
        log_level="info",
        access_log=False,
        reset_contextvars=True,
    )
    socket = config.bind_socket()
    try:
        uvicorn.Server(config).run(sockets=[socket])
    finally:
        socket.close()


if __name__ == "__main__":
    main()
