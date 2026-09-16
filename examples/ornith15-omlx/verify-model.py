#!/usr/bin/env python3
"""Validate the pinned local oMLX experiment without loading model weights."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "model"
STATE = ROOT / "state"
EXPECTED_REVISION = "f6012213916a7df42640539c1df7cd031b2569fb"
EXPECTED_WHEEL = (
    "omlx-0.6.3rc1-cp312-cp312-macosx_15_0_universal2.whl",
    37_616_059,
    "7010ff68df48d38f17dde034fd6f3c2dd6c6c872bed29d42513506de4734362c",
)
EXPECTED_RUNTIME = {
    "omlx": "0.6.3rc1",
    "mlx": "0.32.0",
    "mlx-lm": "0.31.3",
    "mlx-metal": "0.32.0",
}
EXPECTED_MODEL_FILES = {
    ".gitattributes": 1570,
    "README.md": 2873,
    "chat_template.jinja": 16289,
    "chat_template.jinja.bak": 7593,
    "config.json": 22031,
    "merges.txt": 3353259,
    "model-00001-of-00002.safetensors": 5487680957,
    "model-00002-of-00002.safetensors": 734787610,
    "model.safetensors.index.json": 121214,
    "model.safetensors.index.json.combined-bak": 121049,
    "oq_imatrix_report.json": 17030,
    "preprocessor_config.json": 390,
    "processor_config.json": 1191,
    "tokenizer.json": 12807982,
    "tokenizer_config.json": 16710,
    "vocab.json": 6722759,
}
EXPECTED_SHARDS = {
    "model-00001-of-00002.safetensors": "44f3760a45f2cbc8209b82d04490e0c5f9bb70b0361e2dc121ae545f8d598cb4",
    "model-00002-of-00002.safetensors": "eaaee7cc2e131419c94d1ab85201bbac8e6b7d09b610663853251d8ed8696847",
}
# Git blob SHA-1 for ordinary Hub files; SHA-256 for LFS objects (tokenizer).
EXPECTED_METADATA_IDS = {
    ".gitattributes": ("git", "52373fe24473b1aa44333d318f578ae6bf04b49b"),
    "README.md": ("git", "a7ddfa3fe2f81c123e2f90c8a03fbb598647d185"),
    "chat_template.jinja": ("git", "81df6b833cf8dbce37eb97e797dd078fa604cf51"),
    "chat_template.jinja.bak": ("git", "f8cbff56ca4ff72471230af0dc9b286922be082f"),
    "config.json": ("git", "4b1fa6b8311c944eb6b60d66f5f405876750d9f9"),
    "merges.txt": ("git", "a494e019ca1502219fd0128658b979e5f05ae8e8"),
    "model-00001-of-00002.safetensors": ("sha256", "44f3760a45f2cbc8209b82d04490e0c5f9bb70b0361e2dc121ae545f8d598cb4"),
    "model-00002-of-00002.safetensors": ("sha256", "eaaee7cc2e131419c94d1ab85201bbac8e6b7d09b610663853251d8ed8696847"),
    "model.safetensors.index.json": ("git", "e4d81cf63fe2cc90b8e81b8db5827ff2325efbcb"),
    "model.safetensors.index.json.combined-bak": ("git", "dfc63653888602072a2432c33e56762668e5ea37"),
    "oq_imatrix_report.json": ("git", "94bc328b0513b6e4b19192a18a3029868cd3107b"),
    "preprocessor_config.json": ("git", "2ea84a437d448ff71b08df68fdd949d5cc4ebb64"),
    "processor_config.json": ("git", "33818c7f9e991ad735fd240209f4fa73e6c28c50"),
    "tokenizer.json": ("sha256", "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42"),
    "tokenizer_config.json": ("git", "eda48d3e75a8e59a8479ee4ec8b37f76e711d9c1"),
    "vocab.json": ("git", "0aa0ce0658d60ac4a5d609f4eadb0e8e43514176"),
}

OWNER_ONLY_FILES = (
    "settings.json",
    "model_settings.json",
    "api-key",
    "auth-header",
    "secret-key",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    digest.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"validation failed: {message}")


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot parse {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"{path} must contain a JSON object")
    return value


def require_owner_only(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        fail(f"required regular file missing: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        fail(f"{path} is not owner-only (mode {mode:04o})")


def validate_runtime(quick: bool) -> None:
    import zipfile

    wheel_name, wheel_size, wheel_digest = EXPECTED_WHEEL
    wheel = ROOT / "runtime" / wheel_name
    if not wheel.is_file() or wheel.stat().st_size != wheel_size:
        fail("pinned oMLX wheel is missing or has the wrong size")
    if not quick and sha256(wheel) != wheel_digest:
        fail("pinned oMLX wheel SHA-256 mismatch")
    critical_installed_sources = (
        "omlx/server.py",
        "omlx/patches/mlx_lm_mtp/batch_generator.py",
        "omlx/patches/mlx_lm_mtp/prompt_priming.py",
        "omlx/patches/mlx_lm_mtp/qwen35_model.py",
    )
    site_packages = ROOT / "runtime/venv/lib/python3.12/site-packages"
    try:
        with zipfile.ZipFile(wheel) as archive:
            for relative in critical_installed_sources:
                installed = site_packages / relative
                if not installed.is_file() or installed.read_bytes() != archive.read(relative):
                    fail(f"installed critical runtime source differs from pinned wheel: {relative}")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        fail(f"cannot authenticate installed critical runtime sources: {exc}")
    for package, expected in EXPECTED_RUNTIME.items():
        try:
            actual = version(package)
        except Exception as exc:
            fail(f"cannot read installed {package} version: {exc}")
        if actual != expected:
            fail(f"installed {package}={actual!r}, expected {expected!r}")


def validate_checkpoint(quick: bool) -> None:
    revision_file = ROOT / "MODEL_REVISION"
    if not revision_file.is_file() or revision_file.read_text().strip() != EXPECTED_REVISION:
        fail("pinned Hugging Face revision mismatch")

    actual_files = {path.name for path in MODEL.iterdir() if path.is_file()}
    expected_files = set(EXPECTED_MODEL_FILES)
    if actual_files != expected_files:
        fail(
            "unexpected checkpoint file set: "
            f"missing={sorted(expected_files - actual_files)}, "
            f"extra={sorted(actual_files - expected_files)}"
        )
    for name, expected_size in EXPECTED_MODEL_FILES.items():
        path = MODEL / name
        if path.is_symlink() or path.stat().st_size != expected_size:
            fail(f"{name}: expected a {expected_size}-byte regular payload")

    config = load_json(MODEL / "config.json")
    if config.get("model_type") != "qwen3_5":
        fail(f"unexpected model_type={config.get('model_type')!r}")
    if config.get("model_file") or config.get("auto_map"):
        fail("checkpoint requests custom/remote Python code")
    text_config = config.get("text_config") or {}
    if text_config.get("model_type") != "qwen3_5_text":
        fail("unexpected text model type")
    if int(text_config.get("max_position_embeddings", 0)) != 262_144:
        fail("checkpoint no longer declares the native 262144-token context")
    rope = text_config.get("rope_parameters") or {}
    if rope.get("type") != "default" or int(rope.get("rope_theta", 0)) != 10_000_000:
        fail("checkpoint default RoPE type/theta changed")
    if float(text_config.get("partial_rotary_factor", 0.0)) != 0.25:
        fail("checkpoint partial rotary factor changed")
    if rope.get("mrope_interleaved") is not True or rope.get("mrope_section") != [11, 11, 10]:
        fail("checkpoint MRoPE metadata changed")
    tokenizer_config = load_json(MODEL / "tokenizer_config.json")
    if int(tokenizer_config.get("model_max_length", 0)) != 262_144:
        fail("tokenizer no longer declares the native 262144-token context")
    mtp_layers = config.get("mtp_num_hidden_layers", text_config.get("mtp_num_hidden_layers", 0))
    if int(mtp_layers) != 1:
        fail("embedded MTP head is not declared")
    if not config.get("vision_config"):
        fail("source checkpoint no longer declares vision capabilities")
    quant = config.get("quantization") or config.get("quantization_config") or {}
    if quant.get("mode") != "affine" or int(quant.get("bits", 0)) != 4 or int(quant.get("group_size", 0)) != 64:
        fail("unexpected base quantization")
    overrides = {k: v for k, v in quant.items() if isinstance(v, dict)}
    if len(overrides) != 72:
        fail(f"expected 72 lifted (5-bit) tensor overrides, found {len(overrides)}")
    if any(
        v.get("mode") != "affine" or int(v.get("bits", 0)) != 5 or int(v.get("group_size", 0)) != 64
        for v in overrides.values()
    ):
        fail("a lifted tensor override is not 5-bit affine g64")

    index = load_json(MODEL / "model.safetensors.index.json")
    if int((index.get("metadata") or {}).get("total_size", 0)) != 6_222_468_567:
        fail("unexpected indexed model payload size")
    weight_map = index.get("weight_map") or {}
    if len(weight_map) != 1289:
        fail(f"expected 1289 indexed tensors, found {len(weight_map)}")
    mtp_keys = [key for key in weight_map if key.startswith("language_model.mtp.")]
    if len(mtp_keys) != 29:
        fail(f"expected 29 embedded MTP tensors, found {len(mtp_keys)}")
    indexed_shards = set(weight_map.values())
    if indexed_shards != set(EXPECTED_SHARDS):
        fail(f"unexpected tensor-index shards: {sorted(indexed_shards)}")

    for name, digest in EXPECTED_SHARDS.items():
        path = MODEL / name
        if not quick:
            if sha256(path) != digest:
                fail(f"{name}: SHA-256 mismatch")
            print(f"{name}: size and SHA-256 OK")
        else:
            print(f"{name}: size OK")
    if not quick:
        for name, (kind, expected) in EXPECTED_METADATA_IDS.items():
            path = MODEL / name
            actual = sha256(path) if kind == "sha256" else git_blob_sha1(path)
            if actual != expected:
                fail(f"{name}: pinned {kind} identity mismatch")
        print(f"checkpoint metadata: {len(EXPECTED_METADATA_IDS)} pinned identities OK")


def validate_total_context_guard() -> None:
    # Exercise the facade helpers in a clean module state; calling this after
    # build_app in the same process would intentionally see its monkeypatches.
    try:
        from secure_server import (
            HTTPException,
            _MtpSafetyViolation,
            _REQUEST_OUTPUT_BUDGET,
            _bounded_max_tokens,
            _bounded_mtp_draft_depth,
            _install_mtp_position_guard,
            _install_request_rebinding_guard,
            _install_total_context_guard,
            _max_cache_position,
            _record_prompt_tokens,
            _request_output_scope,
            _validate_prompt_budget,
        )
    except Exception as exc:
        fail(f"cannot import native total-context guard: {exc}")

    passing_cases = (
        (None, 8_192, 0, 262_144, 8_192),
        (999_999, 999_999, 1_000, 262_144, 8_192),
        (8_192, 8_192, 245_760, 262_144, 8_192),
        (8_192, 8_192, 260_000, 262_144, 2_144),
        (1, 1, 262_143, 262_144, 1),
        (8_192, 8_192, 24_576, 32_768, 8_192),
        (8_192, 8_192, 30_000, 32_768, 2_768),
    )
    for requested, configured, prompt_tokens, context_window, expected in passing_cases:
        actual = _bounded_max_tokens(
            requested,
            configured,
            prompt_tokens=prompt_tokens,
            context_window=context_window,
        )
        if actual != expected:
            fail(
                "native total-context guard mismatch: "
                f"requested={requested}, prompt={prompt_tokens}, "
                f"context={context_window}, actual={actual}, expected={expected}"
            )

    for requested, prompt_tokens in ((0, 1), (1, 262_144), (8_192, 300_000)):
        try:
            _bounded_max_tokens(
                requested,
                8_192,
                prompt_tokens=prompt_tokens,
            )
        except HTTPException as exc:
            if exc.status_code != 400:
                fail("native total-context guard returned the wrong status")
        else:
            fail(
                "native total-context guard accepted an invalid budget: "
                f"requested={requested}, prompt={prompt_tokens}"
            )

    for prompt_tokens, context_window in ((262_144, 262_144), (32_768, 32_768)):
        try:
            _validate_prompt_budget(
                prompt_tokens,
                context_window=context_window,
            )
        except HTTPException as exc:
            if exc.status_code != 400:
                fail("prompt budget guard returned the wrong status")
        else:
            fail("prompt budget guard accepted a prompt with no output room")

    class ScalarOffset:
        def __init__(self, offset):
            self.offset = offset

    class CacheContainer:
        def __init__(self, caches):
            self.caches = caches

    class BatchKVCache:
        def __init__(self, offset, buffered):
            self.offset = offset
            self._idx = buffered

    class BatchRotatingKVCache:
        def __init__(self, offset, buffered, resident):
            self.offset = offset
            self._idx = buffered
            self._offset = resident

    mixed_cache = [
        ScalarOffset(100),
        CacheContainer([ScalarOffset(99), ScalarOffset(101)]),
    ]
    if _max_cache_position(mixed_cache) != 101:
        fail("MTP cache-position guard did not choose the greatest leaf offset")
    if _max_cache_position([BatchKVCache(object(), 102)]) != 102:
        fail("MTP cache-position guard ignored the exact BatchKVCache counter")
    if _max_cache_position([BatchRotatingKVCache(object(), 7, 8)]) is not None:
        fail("MTP cache-position guard trusted a rotating-cache resident counter")
    if _max_cache_position([]) is not None:
        fail("MTP cache-position guard accepted a cache without offsets")

    mtp_cases = (
        (3, 100, 0, 0, 8_192, 262_144, 3),
        (3, 262_140, 0, 2, 4, 262_144, 1),
        (3, 262_143, 0, 0, 1, 262_144, 0),
        (3, 32_764, 0, 2, 4, 32_768, 1),
        (3, 32_767, 0, 0, 1, 32_768, 0),
    )
    for desired, sequence, emitted, queued, maximum, context, expected in mtp_cases:
        actual = _bounded_mtp_draft_depth(
            desired,
            sequence_tokens=sequence,
            emitted_tokens=emitted,
            queued_tokens=queued,
            max_output_tokens=maximum,
            context_window=context,
        )
        if actual != expected:
            fail(
                "MTP position guard mismatch: "
                f"sequence={sequence}, queued={queued}, context={context}, "
                f"actual={actual}, expected={expected}"
            )

    # Exercise the real request-binding monkeypatch, including repeated prompt
    # validation (raw completion prompt lists), nesting, and exception cleanup.
    class FakeServer:
        @staticmethod
        def validate_context_window(num_prompt_tokens, model_id=None):
            return None

    class FakeRequest:
        def __init__(self, max_tokens):
            self.max_tokens = max_tokens

    fake = FakeServer()
    _install_total_context_guard(fake, 262_144)
    outer_request = FakeRequest(111)
    outer_token = _REQUEST_OUTPUT_BUDGET.set("outer-sentinel")
    try:
        request = FakeRequest(8_192)
        with _request_output_scope(request):
            fake.validate_context_window(1_000, "ornith15-omlx")
            if request.max_tokens != 8_192:
                fail("request output was unexpectedly reduced for a short prompt")
            fake.validate_context_window(260_000, "ornith15-omlx")
            if request.max_tokens != 2_144:
                fail("real request-binding monkeypatch missed the largest prompt")
            with _request_output_scope(outer_request):
                fake.validate_context_window(262_143, "ornith15-omlx")
                if outer_request.max_tokens != 1:
                    fail("nested request output scope did not bind its own limit")
            if _REQUEST_OUTPUT_BUDGET.get().request is not request:
                fail("nested request scope did not restore the outer request")
        wrapped_validate = fake.validate_context_window
        _install_total_context_guard(fake, 32_768)
        if fake.validate_context_window is not wrapped_validate:
            fail("total-context request guard wrapped itself twice")
        rollback_request = FakeRequest(8_192)
        with _request_output_scope(rollback_request):
            fake.validate_context_window(30_000, "ornith15-omlx")
        if rollback_request.max_tokens != 2_768:
            fail("total-context request guard is not rollback-aware")
        _install_total_context_guard(fake, 262_144)
    finally:
        if _REQUEST_OUTPUT_BUDGET.get() != "outer-sentinel":
            fail("request output scope did not restore exact prior state")
        _REQUEST_OUTPUT_BUDGET.reset(outer_token)

    request = FakeRequest(8_192)
    try:
        with _request_output_scope(request):
            fake.validate_context_window(260_000, "ornith15-omlx")
            raise RuntimeError("expected scope test")
    except RuntimeError as exc:
        if str(exc) != "expected scope test":
            raise
    if _REQUEST_OUTPUT_BUDGET.get() is not None:
        fail("request output scope leaked after an exception")

    try:
        _record_prompt_tokens(1, context_window=262_144)
    except RuntimeError:
        pass
    else:
        fail("prompt binding accepted validation outside an explicit request")

    # Deferred generation tasks must use the already-mutated request object,
    # even when deliberately created with an empty ContextVar context.
    import asyncio
    import contextvars

    async def read_bound_request_with_empty_context(request):
        async def child():
            return request.max_tokens, _REQUEST_OUTPUT_BUDGET.get()

        task = asyncio.create_task(child(), context=contextvars.Context())
        return await task

    request = FakeRequest(8_192)
    with _request_output_scope(request):
        fake.validate_context_window(260_000, "ornith15-omlx")
    bound, child_budget = asyncio.run(read_bound_request_with_empty_context(request))
    if bound != 2_144 or child_budget is not None:
        fail("deferred task still depends on inherited ContextVar state")

    # If upstream preprocessing creates a Pydantic-style replacement request,
    # prompt accounting must follow the object that sampling will consume.
    class FakeRebindingServer:
        @staticmethod
        def _preprocess_markitdown_files_for_llm(request):
            async def replace():
                return FakeRequest(request.max_tokens)

            return replace()

    rebinding_server = FakeRebindingServer()
    _install_request_rebinding_guard(rebinding_server)
    original_request = FakeRequest(8_192)

    async def exercise_rebinding():
        with _request_output_scope(original_request) as budget:
            replacement = await rebinding_server._preprocess_markitdown_files_for_llm(
                original_request
            )
            if budget.request is not replacement:
                raise AssertionError("request budget did not follow its replacement")
            _record_prompt_tokens(260_000, context_window=262_144)
            return replacement.max_tokens, original_request.max_tokens

    replacement_limit, original_limit = asyncio.run(exercise_rebinding())
    if replacement_limit != 2_144 or original_limit != 8_192:
        fail("replacement request did not receive the bounded output ceiling")
    wrapped_preprocess = rebinding_server._preprocess_markitdown_files_for_llm
    _install_request_rebinding_guard(rebinding_server)
    if rebinding_server._preprocess_markitdown_files_for_llm is not wrapped_preprocess:
        fail("request rebinding guard wrapped itself twice")

    # Install the actual MTP patch and assert that all risky primitives are
    # guarded. Re-installation must be idempotent (build_app may be probed).
    _install_mtp_position_guard(262_144)
    from omlx.patches.mlx_lm_mtp import batch_generator as mtp_batch

    guarded = (
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
    if not getattr(mtp_batch, "_qwen_secure_position_guard", False):
        fail("MTP position guard marker is missing")
    if any(getattr(mtp_batch, name).__module__ != "secure_server" for name in guarded):
        fail("one or more MTP forward/draft primitives remain unguarded")
    before = tuple(getattr(mtp_batch, name) for name in guarded)
    identities = getattr(mtp_batch, "_qwen_secure_guarded_functions", {})
    if any(identities.get(name) is not getattr(mtp_batch, name) for name in guarded):
        fail("MTP position guard did not publish verifiable wrapper identities")
    _install_mtp_position_guard(32_768)
    after = tuple(getattr(mtp_batch, name) for name in guarded)
    if before != after or mtp_batch._qwen_secure_context_window != 32_768:
        fail("MTP position guard is not idempotent or rollback-aware")

    # Primitive behavior must hold in the documented 32768 rollback mode too.
    try:
        mtp_batch._call_backbone(
            None,
            type("RollbackInputs", (), {"shape": (1, 2)})(),
            [ScalarOffset(32_767)],
        )
    except _MtpSafetyViolation:
        pass
    else:
        fail("MTP target guard accepted a rollback-window overflow")

    # Simulate post-install monkeypatch drift and ensure a restart probe fails
    # closed instead of trusting the boolean marker.
    saved_verify = mtp_batch._run_verify_cycle_chain
    mtp_batch._run_verify_cycle_chain = lambda *args, **kwargs: None
    try:
        try:
            _install_mtp_position_guard(32_768)
        except RuntimeError:
            pass
        else:
            fail("MTP position guard accepted wrapper identity drift")
    finally:
        mtp_batch._run_verify_cycle_chain = saved_verify
    _install_mtp_position_guard(262_144)

    # Lightweight primitive tests prove unsafe target/head positions stop
    # before an MLX forward; no model weights are loaded.
    from types import SimpleNamespace

    class SizedTokens:
        def __init__(self, length):
            self.length = length

        def __len__(self):
            return self.length

    class Inputs:
        shape = (1, 2)

    try:
        mtp_batch._call_backbone(None, Inputs(), [ScalarOffset(262_143)])
    except _MtpSafetyViolation:
        pass
    except mtp_batch._MtpStepFallback:
        fail("MTP target overflow remained a recoverable standard fallback")
    else:
        fail("MTP target forward guard accepted a native-window overflow")

    post_batch = SimpleNamespace(
        max_tokens=[1],
        _num_tokens=[0],
        prompt_cache=[ScalarOffset(262_143)],
        model=object(),
        tokens=[SizedTokens(262_143)],
    )
    mtp_batch._post_init_mtp(post_batch)
    if hasattr(post_batch, "_omlx_mtp_state"):
        fail("MTP initialized despite only one output/position remaining")

    verify_state = SimpleNamespace(
        drafts=SimpleNamespace(shape=(3,)),
        hist_offset=0,
    )
    verify_batch = SimpleNamespace(
        tokens=[SizedTokens(262_141)],
        max_tokens=[4],
        _num_tokens=[0],
        prompt_cache=[ScalarOffset(262_141)],
    )
    try:
        mtp_batch._run_verify_cycle_chain(verify_batch, verify_state)
    except _MtpSafetyViolation:
        pass
    except mtp_batch._MtpStepFallback:
        fail("MTP verify overflow remained a recoverable standard fallback")
    else:
        fail("MTP verify guard accepted a native-window overflow")

    head_state = SimpleNamespace(
        controller=SimpleNamespace(cur=3),
        depth=3,
        queue=[],
        hist_offset=262_140,
        mtp_cache=[ScalarOffset(262_143)],
    )
    head_batch = SimpleNamespace(
        tokens=[SizedTokens(262_140)],
        _num_tokens=[0],
        max_tokens=[4],
    )
    try:
        mtp_batch._chain_next_drafts(
            head_batch,
            head_state,
            None,
            SimpleNamespace(shape=(2,)),
            None,
        )
    except _MtpSafetyViolation:
        pass
    except mtp_batch._MtpStepFallback:
        fail("MTP head overflow remained a recoverable standard fallback")
    else:
        fail("MTP head-fold guard accepted a native-window overflow")

    # Exercise success and post-mutation failure paths through the exact guard
    # composition, without loading model weights or mutating the authenticated
    # upstream module. This prevents a precondition-only test from claiming
    # that postconditions, boundary trimming, or reconciliation are safe.
    def make_fake_mtp_module(
        *,
        call_backbone=lambda *args, **kwargs: None,
        chain_next=lambda *args, **kwargs: None,
        verify_cycle=lambda *args, **kwargs: None,
        materialize=lambda *args, **kwargs: None,
        reconcile=lambda *args, **kwargs: True,
        trim=lambda *args, **kwargs: None,
    ):
        return SimpleNamespace(
            _omlx_mtp_patched=True,
            _qwen_secure_position_guard=False,
            _call_backbone=call_backbone,
            _post_init_mtp=lambda *args, **kwargs: None,
            _chain_next_drafts=chain_next,
            _run_verify_cycle_chain=verify_cycle,
            _materialize_mtp_boundary_emit=materialize,
            _prepare_mtp_state_for_next=lambda *args, **kwargs: None,
            _mtp_next=lambda *args, **kwargs: None,
            _prepare_mtp_batch_state_for_next=lambda *args, **kwargs: None,
            _mtp_batch_next=lambda *args, **kwargs: None,
            _feed_next_main_to_standard=lambda *args, **kwargs: True,
            _park_mtp_to_standard=lambda *args, **kwargs: True,
            _handoff_mtp_for_late_join=lambda *args, **kwargs: True,
            _reconcile_mtp_to_standard=reconcile,
            _reconcile_mtp_batch_to_standard=reconcile,
            _prompt_priming=SimpleNamespace(drop_ctx=lambda model: None),
            _mtp_head_trim_to=trim,
        )

    backbone_result = object()

    def advancing_backbone(model, inputs, cache, *args, **kwargs):
        cache[0].offset += int(inputs.shape[1])
        return backbone_result

    fake_mtp = make_fake_mtp_module(call_backbone=advancing_backbone)
    _install_mtp_position_guard(262_144, mtp_batch=fake_mtp)
    success_cache = [ScalarOffset(262_140)]
    result = fake_mtp._call_backbone(
        None, SimpleNamespace(shape=(1, 2)), success_cache
    )
    if result is not backbone_result or success_cache[0].offset != 262_142:
        fail("MTP target success path changed a valid backbone forward")

    def over_advancing_backbone(model, inputs, cache, *args, **kwargs):
        cache[0].offset += int(inputs.shape[1]) + 1
        return None

    fake_mtp = make_fake_mtp_module(call_backbone=over_advancing_backbone)
    _install_mtp_position_guard(262_144, mtp_batch=fake_mtp)
    post_target_cache = [ScalarOffset(262_142)]
    try:
        fake_mtp._call_backbone(
            None, SimpleNamespace(shape=(1, 2)), post_target_cache
        )
    except _MtpSafetyViolation:
        if post_target_cache[0].offset != 262_145:
            fail("MTP target postcondition test did not mutate the cache")
    else:
        fail("MTP target postcondition failure did not abort decoding")

    observed_depths = []

    def valid_chain(gen_batch, state, hidden_rows, committed, prev_buf):
        depth = state.controller.cur if state.controller is not None else state.depth
        observed_depths.append(int(depth))
        committed_count = int(committed.shape[0])
        state.mtp_cache[0].offset += committed_count + max(0, int(depth) - 1)
        state.hist_offset += committed_count
        state.drafts = SimpleNamespace(shape=(int(depth),))

    fake_mtp = make_fake_mtp_module(chain_next=valid_chain)
    _install_mtp_position_guard(262_144, mtp_batch=fake_mtp)
    chain_state = SimpleNamespace(
        controller=SimpleNamespace(cur=3),
        depth=3,
        queue=[],
        hist_offset=262_140,
        mtp_cache=[ScalarOffset(262_140)],
    )
    chain_batch = SimpleNamespace(
        tokens=[SizedTokens(262_142)],
        _num_tokens=[0],
        max_tokens=[2],
    )
    fake_mtp._chain_next_drafts(
        chain_batch,
        chain_state,
        None,
        SimpleNamespace(shape=(1,)),
        None,
    )
    if (
        observed_depths != [1]
        or chain_state.controller.cur != 3
        or chain_state.drafts.shape != (1,)
        or chain_state.mtp_cache[0].offset != 262_141
    ):
        fail("MTP head success path did not apply and restore the safe depth")

    def wrong_depth_chain(gen_batch, state, hidden_rows, committed, prev_buf):
        depth = state.controller.cur if state.controller is not None else state.depth
        state.mtp_cache[0].offset += int(committed.shape[0])
        state.hist_offset += int(committed.shape[0])
        state.drafts = SimpleNamespace(shape=(int(depth) + 1,))

    fake_mtp = make_fake_mtp_module(chain_next=wrong_depth_chain)
    _install_mtp_position_guard(262_144, mtp_batch=fake_mtp)
    bad_chain_state = SimpleNamespace(
        controller=SimpleNamespace(cur=3),
        depth=3,
        queue=[],
        hist_offset=262_140,
        mtp_cache=[ScalarOffset(262_140)],
    )
    try:
        fake_mtp._chain_next_drafts(
            chain_batch,
            bad_chain_state,
            None,
            SimpleNamespace(shape=(1,)),
            None,
        )
    except _MtpSafetyViolation:
        if bad_chain_state.controller.cur != 3:
            fail("MTP depth controller was not restored after a hard failure")
    else:
        fail("MTP head postcondition failure did not abort decoding")

    def valid_verify(gen_batch, state):
        step = int(state.drafts.shape[0]) + 1
        gen_batch.prompt_cache[0].offset += step
        state.mtp_cache[0].offset += 1

    fake_mtp = make_fake_mtp_module(verify_cycle=valid_verify)
    _install_mtp_position_guard(262_144, mtp_batch=fake_mtp)
    success_verify_state = SimpleNamespace(
        drafts=SimpleNamespace(shape=(1,)),
        mtp_cache=[ScalarOffset(262_141)],
    )
    success_verify_batch = SimpleNamespace(
        tokens=[SizedTokens(262_142)],
        max_tokens=[2],
        _num_tokens=[0],
        prompt_cache=[ScalarOffset(262_142)],
    )
    fake_mtp._run_verify_cycle_chain(success_verify_batch, success_verify_state)
    if success_verify_batch.prompt_cache[0].offset != 262_144:
        fail("MTP verify success path rejected the exact native boundary")

    def invalid_verify(gen_batch, state):
        gen_batch.prompt_cache[0].offset += int(state.drafts.shape[0]) + 2

    fake_mtp = make_fake_mtp_module(verify_cycle=invalid_verify)
    _install_mtp_position_guard(262_144, mtp_batch=fake_mtp)
    invalid_verify_state = SimpleNamespace(
        drafts=SimpleNamespace(shape=(1,)),
        mtp_cache=[ScalarOffset(262_141)],
    )
    invalid_verify_batch = SimpleNamespace(
        tokens=[SizedTokens(262_142)],
        max_tokens=[2],
        _num_tokens=[0],
        prompt_cache=[ScalarOffset(262_142)],
    )
    try:
        fake_mtp._run_verify_cycle_chain(invalid_verify_batch, invalid_verify_state)
    except _MtpSafetyViolation:
        if invalid_verify_batch.prompt_cache[0].offset != 262_145:
            fail("MTP verify postcondition test did not mutate the target cache")
    else:
        fail("MTP verify postcondition failure did not abort decoding")

    boundary_events = []

    def trim_head(cache, offset):
        boundary_events.append("trim")
        for entry in cache:
            entry.offset = min(int(entry.offset), int(offset))

    def valid_materialize(gen_batch, state):
        if getattr(state, "_qwen_secure_pending_materialized_token", 0) != 1:
            raise AssertionError("boundary marker was not set before materialization")
        boundary_events.append("materialize")
        gen_batch.prompt_cache[0].offset += 1
        state.mtp_cache[0].offset += 1

    fake_mtp = make_fake_mtp_module(
        materialize=valid_materialize,
        trim=trim_head,
    )
    _install_mtp_position_guard(262_144, mtp_batch=fake_mtp)
    boundary_state = SimpleNamespace(
        queue=[object()],
        hist_offset=262_140,
        mtp_cache=[ScalarOffset(262_143)],
    )
    boundary_batch = SimpleNamespace(
        tokens=[SizedTokens(262_142)],
        max_tokens=[3],
        _num_tokens=[0],
        prompt_cache=[ScalarOffset(262_142)],
    )
    fake_mtp._materialize_mtp_boundary_emit(boundary_batch, boundary_state)
    if (
        boundary_events != ["trim", "materialize"]
        or boundary_state.mtp_cache[0].offset != 262_141
        or hasattr(boundary_state, "_qwen_secure_pending_materialized_token")
    ):
        fail("MTP boundary success path did not trim, materialize, and clean up")

    boundary_events.clear()
    skipped_state = SimpleNamespace(
        queue=[object()],
        hist_offset=262_143,
        mtp_cache=[ScalarOffset(262_143)],
    )
    skipped_batch = SimpleNamespace(
        tokens=[SizedTokens(262_144)],
        max_tokens=[1],
        _num_tokens=[0],
        prompt_cache=[ScalarOffset(262_143)],
    )
    fake_mtp._materialize_mtp_boundary_emit(skipped_batch, skipped_state)
    if boundary_events or hasattr(
        skipped_state, "_qwen_secure_pending_materialized_token"
    ):
        fail("MTP boundary optimization mutated state when it had no room")

    def ineffective_trim(cache, offset):
        boundary_events.append("ineffective-trim")

    fake_mtp = make_fake_mtp_module(
        materialize=valid_materialize,
        trim=ineffective_trim,
    )
    _install_mtp_position_guard(262_144, mtp_batch=fake_mtp)
    untrimmed_state = SimpleNamespace(
        queue=[object()],
        hist_offset=262_140,
        mtp_cache=[ScalarOffset(262_143)],
    )
    untrimmed_batch = SimpleNamespace(
        tokens=[SizedTokens(262_142)],
        max_tokens=[3],
        _num_tokens=[0],
        prompt_cache=[ScalarOffset(262_142)],
    )
    try:
        fake_mtp._materialize_mtp_boundary_emit(untrimmed_batch, untrimmed_state)
    except _MtpSafetyViolation:
        if boundary_events != ["ineffective-trim"]:
            fail("MTP boundary materialized after an ineffective head trim")
        if hasattr(untrimmed_state, "_qwen_secure_pending_materialized_token"):
            fail("MTP boundary marker leaked after an ineffective head trim")
    else:
        fail("MTP boundary accepted an ineffective head trim")

    boundary_events.clear()

    def invalid_materialize(gen_batch, state):
        boundary_events.append("invalid-materialize")
        gen_batch.prompt_cache[0].offset += 2

    fake_mtp = make_fake_mtp_module(
        materialize=invalid_materialize,
        trim=trim_head,
    )
    _install_mtp_position_guard(262_144, mtp_batch=fake_mtp)
    invalid_boundary_state = SimpleNamespace(
        queue=[object()],
        hist_offset=262_140,
        mtp_cache=[ScalarOffset(262_143)],
    )
    invalid_boundary_batch = SimpleNamespace(
        tokens=[SizedTokens(262_143)],
        max_tokens=[2],
        _num_tokens=[0],
        prompt_cache=[ScalarOffset(262_143)],
    )
    try:
        fake_mtp._materialize_mtp_boundary_emit(
            invalid_boundary_batch, invalid_boundary_state
        )
    except _MtpSafetyViolation:
        if hasattr(
            invalid_boundary_state, "_qwen_secure_pending_materialized_token"
        ):
            fail("MTP boundary marker leaked after a hard failure")
    else:
        fail("MTP boundary postcondition failure did not abort decoding")

    # The installed fallback catch ignores the reconcile return value. Its
    # wrapped seam must therefore raise on either False or an exception, and
    # only return after a proven successful rebuild.
    for original, should_pass in (
        (lambda *args, **kwargs: True, True),
        (lambda *args, **kwargs: False, False),
    ):
        fake_mtp = make_fake_mtp_module(reconcile=original)
        _install_mtp_position_guard(262_144, mtp_batch=fake_mtp)
        for name, args in (
            ("_reconcile_mtp_to_standard", (object(), object())),
            ("_reconcile_mtp_batch_to_standard", (object(),)),
        ):
            try:
                result = getattr(fake_mtp, name)(*args)
            except _MtpSafetyViolation:
                if should_pass:
                    fail(f"{name} rejected a successful reconciliation")
            else:
                if not should_pass or result is not True:
                    fail(f"{name} accepted an unproven reconciliation")

    # Upstream fallback exceptions must be converted before the pinned
    # GenerationBatch.next closure can catch them and resume ordinary decode.
    dispatch_names = (
        "_prepare_mtp_state_for_next",
        "_mtp_next",
        "_prepare_mtp_batch_state_for_next",
        "_mtp_batch_next",
    )
    for dispatch_name in dispatch_names:
        fake_mtp = make_fake_mtp_module()

        def clean_result(*args, **kwargs):
            return "clean"

        setattr(fake_mtp, dispatch_name, clean_result)
        _install_mtp_position_guard(262_144, mtp_batch=fake_mtp)
        args = (object(), object()) if dispatch_name in {
            "_mtp_next",
            "_mtp_batch_next",
        } else (object(),)
        if getattr(fake_mtp, dispatch_name)(*args) != "clean":
            fail(f"{dispatch_name} changed a successful MTP dispatch")

        fake_mtp = make_fake_mtp_module()

        def recoverable_failure(*args, _module=fake_mtp, **kwargs):
            raise _module._MtpStepFallback("synthetic fallback")

        fake_mtp._MtpStepFallback = type(
            "SyntheticMtpStepFallback", (RuntimeError,), {}
        )
        setattr(fake_mtp, dispatch_name, recoverable_failure)
        _install_mtp_position_guard(262_144, mtp_batch=fake_mtp)
        try:
            getattr(fake_mtp, dispatch_name)(*args)
        except _MtpSafetyViolation:
            pass
        except fake_mtp._MtpStepFallback:
            fail(f"{dispatch_name} leaked a recoverable fallback")
        else:
            fail(f"{dispatch_name} swallowed a recoverable fallback")

    # Exact handoffs are planned state transitions, but their pinned helpers
    # use Boolean failure and broad exception catches. Require literal success
    # at feed, park, and late-join seams so no response or later stock decode
    # can follow a swallowed post-forward mutation.
    handoff_names = (
        "_feed_next_main_to_standard",
        "_park_mtp_to_standard",
        "_handoff_mtp_for_late_join",
    )
    for handoff_name in handoff_names:
        for behavior, should_pass in (
            (lambda *args, **kwargs: True, True),
            (lambda *args, **kwargs: False, False),
        ):
            fake_mtp = make_fake_mtp_module()
            setattr(fake_mtp, handoff_name, behavior)
            _install_mtp_position_guard(262_144, mtp_batch=fake_mtp)
            try:
                result = getattr(fake_mtp, handoff_name)(object(), object())
            except _MtpSafetyViolation:
                if should_pass:
                    fail(f"{handoff_name} rejected a successful handoff")
            else:
                if not should_pass or result is not True:
                    fail(f"{handoff_name} accepted an unproven handoff")

        fake_mtp = make_fake_mtp_module()

        def raising_handoff(*args, **kwargs):
            raise ValueError("synthetic post-forward handoff failure")

        setattr(fake_mtp, handoff_name, raising_handoff)
        _install_mtp_position_guard(262_144, mtp_batch=fake_mtp)
        try:
            getattr(fake_mtp, handoff_name)(object(), object())
        except _MtpSafetyViolation:
            pass
        else:
            fail(f"{handoff_name} swallowed a handoff exception")

    def raising_reconcile(*args, **kwargs):
        raise ValueError("synthetic reconcile failure")

    fake_mtp = make_fake_mtp_module(reconcile=raising_reconcile)
    _install_mtp_position_guard(262_144, mtp_batch=fake_mtp)
    for name, args in (
        ("_reconcile_mtp_to_standard", (object(), object())),
        ("_reconcile_mtp_batch_to_standard", (object(),)),
    ):
        try:
            getattr(fake_mtp, name)(*args)
        except _MtpSafetyViolation:
            pass
        else:
            fail(f"{name} swallowed a reconciliation exception")


def validate_route_task_graph() -> None:
    """Exercise both local POST wrappers without loading model weights."""
    import asyncio
    import contextvars
    import json

    try:
        import httpx
        from fastapi.responses import StreamingResponse
        from omlx.exceptions import (
            InvalidRequestError,
            PrefillMemoryAbortedError,
            PrefillMemoryExceededError,
            SchedulerQueueFullError,
        )
        import omlx.server as server_module
        from secure_server import ALLOWED, _REQUEST_OUTPUT_BUDGET, build_app
    except Exception as exc:
        fail(f"cannot import ASGI route-regression dependencies: {exc}")

    previous_marker = os.environ.get("OMLX_SECURE_ENTRYPOINT")
    os.environ["OMLX_SECURE_ENTRYPOINT"] = "1"
    try:
        app = build_app()
    finally:
        if previous_marker is None:
            os.environ.pop("OMLX_SECURE_ENTRYPOINT", None)
        else:
            os.environ["OMLX_SECURE_ENTRYPOINT"] = previous_marker

    records = []
    active_context = int(
        (load_json(STATE / "settings.json").get("sampling") or {}).get(
            "max_context_window", 0
        )
    )
    near_prompt = active_context - 2_144
    if active_context not in {32_768, 262_144} or near_prompt <= 0:
        fail("ASGI regression received an unsupported active context")

    async def deferred(kind, request, prompt_tokens):
        async def child():
            return request.max_tokens, _REQUEST_OUTPUT_BUDGET.get()

        task = asyncio.create_task(child(), context=contextvars.Context())
        effective, inherited_budget = await task
        if inherited_budget is not None:
            raise AssertionError("deferred response inherited request budget")
        records.append((kind, bool(request.stream), prompt_tokens, effective))
        return effective

    async def fake_completion(request, http_request, verified):
        prompts = request.prompt if isinstance(request.prompt, list) else [request.prompt]
        for prompt in prompts:
            server_module.validate_context_window(int(prompt), request.model)
        if any(int(prompt) == -1 for prompt in prompts):
            raise RuntimeError("synthetic failure")
        if any(int(prompt) == -2 for prompt in prompts):
            raise PrefillMemoryExceededError(
                "synthetic prefill ceiling",
                estimated_bytes=12_345,
                limit_bytes=10_000,
            )
        if any(int(prompt) == -3 for prompt in prompts):
            raise PrefillMemoryAbortedError(
                "synthetic mid-prefill abort",
                estimated_bytes=12_346,
                limit_bytes=10_000,
            )
        if any(int(prompt) == -4 for prompt in prompts):
            raise InvalidRequestError("synthetic invalid prompt", field="prompt")
        if any(int(prompt) == -5 for prompt in prompts):
            raise SchedulerQueueFullError(2, 2)
        prompt_tokens = max(map(int, prompts))

        async def body():
            effective = await deferred("completion", request, prompt_tokens)
            yield json.dumps({"effective": effective}).encode()

        return StreamingResponse(body(), media_type="application/json")

    async def fake_chat(request, http_request, verified):
        prompt_tokens = int(request.messages[-1].content)
        server_module.validate_context_window(prompt_tokens, request.model)
        if prompt_tokens == -1:
            raise RuntimeError("synthetic failure")
        if prompt_tokens == -2:
            raise PrefillMemoryExceededError(
                "synthetic prefill ceiling",
                estimated_bytes=12_345,
                limit_bytes=10_000,
            )

        async def body():
            effective = await deferred("chat", request, prompt_tokens)
            yield json.dumps({"effective": effective}).encode()

        return StreamingResponse(body(), media_type="application/json")

    server_module.create_completion = fake_completion
    server_module.create_chat_completion = fake_chat
    key = (STATE / "api-key").read_text(encoding="utf-8").strip()
    headers = {"Authorization": f"Bearer {key}"}

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://secure-facade.test",
        ) as client:
            async def post(path, body, expected=200):
                response = await client.post(path, headers=headers, json=body)
                if response.status_code != expected:
                    raise AssertionError(
                        f"{path}: expected {expected}, got {response.status_code}: "
                        f"{response.text}"
                    )
                return response

            for path, base in (
                (
                    "/v1/completions",
                    {"model": "ornith15-omlx", "prompt": str(near_prompt)},
                ),
                (
                    "/v1/chat/completions",
                    {
                        "model": "ornith15-omlx",
                        "messages": [
                            {"role": "user", "content": str(near_prompt)}
                        ],
                    },
                ),
            ):
                for stream in (False, True):
                    response = await post(
                        path,
                        {**base, "max_tokens": 8_192, "stream": stream},
                    )
                    if response.json()["effective"] != 2_144:
                        raise AssertionError("near-window request was not clamped")

            alias = await post(
                "/v1/chat/completions",
                {
                    "model": "ornith15-omlx",
                    "messages": [{"role": "user", "content": "100"}],
                    "max_completion_tokens": 999_999,
                    "stream": True,
                },
            )
            if alias.json()["effective"] != 8_192:
                raise AssertionError("chat max_completion_tokens alias escaped the cap")

            prompt_list = await post(
                "/v1/completions",
                {
                    "model": "ornith15-omlx",
                    "prompt": ["100", str(near_prompt)],
                    "max_tokens": 8_192,
                },
            )
            if prompt_list.json()["effective"] != 2_144:
                raise AssertionError("raw prompt-list maximum was not enforced")

            near, short = await asyncio.gather(
                post(
                    "/v1/completions",
                    {
                        "model": "ornith15-omlx",
                        "prompt": str(near_prompt),
                        "max_tokens": 8_192,
                        "stream": True,
                    },
                ),
                post(
                    "/v1/chat/completions",
                    {
                        "model": "ornith15-omlx",
                        "messages": [{"role": "user", "content": "100"}],
                        "max_tokens": 8_192,
                    },
                ),
            )
            if near.json()["effective"] != 2_144 or short.json()["effective"] != 8_192:
                raise AssertionError("concurrent request budgets crossed")

            before = len(records)
            exact_completion = await post(
                "/v1/completions",
                {
                    "model": "ornith15-omlx",
                    "prompt": str(active_context),
                    "max_tokens": 1,
                },
                expected=400,
            )
            exact_chat = await post(
                "/v1/chat/completions",
                {
                    "model": "ornith15-omlx",
                    "messages": [
                        {"role": "user", "content": str(active_context)}
                    ],
                    "max_tokens": 1,
                },
                expected=400,
            )
            for response in (exact_completion, exact_chat):
                payload = response.json()
                if (
                    "detail" in payload
                    or (payload.get("error") or {}).get("type")
                    != "invalid_request_error"
                    or "Prompt leaves no room" not in (
                        (payload.get("error") or {}).get("message") or ""
                    )
                ):
                    raise AssertionError(
                        "context rejection lost the upstream OpenAI error shape"
                    )
            if len(records) != before:
                raise AssertionError("exact-window request started deferred generation")

            failed = await client.post(
                "/v1/completions",
                headers=headers,
                json={"model": "ornith15-omlx", "prompt": "-1", "max_tokens": 8_192},
            )
            if failed.status_code != 500:
                raise AssertionError("synthetic endpoint failure did not surface")
            failed_payload = failed.json()
            if (
                (failed_payload.get("error") or {}).get("type") != "server_error"
                or "synthetic failure" in failed.text
            ):
                raise AssertionError(
                    "generic facade failure lost the upstream redacted OpenAI shape"
                )
            after_failure = await post(
                "/v1/completions",
                {"model": "ornith15-omlx", "prompt": "100", "max_tokens": 8_192},
            )
            if after_failure.json()["effective"] != 8_192:
                raise AssertionError("failed request contaminated its successor")

            malformed = await client.post(
                "/v1/completions",
                headers=headers,
                json={"model": "ornith15-omlx", "prompt": "100", "max_tokens": "bad"},
            )
            malformed_payload = malformed.json()
            if (
                malformed.status_code != 422
                or (malformed_payload.get("error") or {}).get("type")
                != "invalid_request_error"
                or (malformed_payload.get("error") or {}).get("param")
                != "max_tokens"
            ):
                raise AssertionError("facade lost the upstream validation handler")

            invalid_request = await post(
                "/v1/completions",
                {"model": "ornith15-omlx", "prompt": "-4", "max_tokens": 1},
                expected=400,
            )
            if (invalid_request.json().get("error") or {}).get("param") != "prompt":
                raise AssertionError("facade lost InvalidRequestError field mapping")

            queue_full = await post(
                "/v1/completions",
                {"model": "ornith15-omlx", "prompt": "-5", "max_tokens": 1},
                expected=503,
            )
            if queue_full.headers.get("Retry-After") != "1":
                raise AssertionError("facade lost SchedulerQueueFull retry policy")

            aborted = await post(
                "/v1/completions",
                {"model": "ornith15-omlx", "prompt": "-3", "max_tokens": 1},
                expected=400,
            )
            aborted_error = aborted.json().get("error") or {}
            if (
                aborted_error.get("code") != "prefill_memory_aborted"
                or aborted_error.get("omlx_code") != "prefill_memory_aborted"
                or "aborted this request mid-prefill" not in aborted_error.get("message", "")
            ):
                raise AssertionError("facade lost PrefillMemoryAbortedError mapping")

            for path, body in (
                (
                    "/v1/completions",
                    {"model": "ornith15-omlx", "prompt": "-2", "max_tokens": 1},
                ),
                (
                    "/v1/chat/completions",
                    {
                        "model": "ornith15-omlx",
                        "messages": [{"role": "user", "content": "-2"}],
                        "max_tokens": 1,
                    },
                ),
            ):
                memory_error = await post(path, body, expected=400)
                payload = memory_error.json()
                if (
                    payload.get("type") != "error"
                    or (payload.get("error") or {}).get("code")
                    != "prefill_memory_exceeded"
                    or (payload.get("error") or {}).get("estimated_bytes")
                    != 12_345
                    or (payload.get("error") or {}).get("limit_bytes")
                    != 10_000
                ):
                    raise AssertionError(
                        "secure facade did not preserve the upstream prefill-memory handler"
                    )

            unauthorized = await client.post(
                "/v1/completions",
                json={"model": "ornith15-omlx", "prompt": "100", "max_tokens": 1},
            )
            if unauthorized.status_code not in (401, 403):
                raise AssertionError("local completion wrapper bypassed API auth")

    # The facade must inherit every upstream exception mapping by identity;
    # otherwise future typed engine failures silently regress to generic 500s.
    import omlx.server as upstream_server

    for exc_type, handler in upstream_server.app.exception_handlers.items():
        if app.exception_handlers.get(exc_type) is not handler:
            fail(
                "secure facade did not preserve upstream handler for "
                f"{getattr(exc_type, '__name__', exc_type)!s}"
            )
    # Prompt bodies can contain credentials/private data; deliberately omit the
    # optional TRACE request-body logger and browser CORS from this loopback,
    # server-to-server facade.
    if app.user_middleware:
        fail("secure loopback facade unexpectedly inherited upstream middleware")

    try:
        asyncio.run(exercise())
    except Exception as exc:
        fail(f"ASGI request-budget regression failed: {exc}")

    found = [
        (method, route.path)
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
    ]
    if set(found) != ALLOWED or len(found) != len(ALLOWED):
        fail("facade route allowlist is missing, duplicated, or expanded")
    if len(records) != 9:
        fail(f"expected 9 deferred route cases, observed {len(records)}")


def validate_isolation() -> None:
    state_mode = stat.S_IMODE(STATE.stat().st_mode) if STATE.is_dir() else -1
    if state_mode < 0 or state_mode & 0o077:
        fail(f"state directory is missing or not owner-only (mode {state_mode:04o})")
    for name in OWNER_ONLY_FILES:
        require_owner_only(STATE / name)
    private_home = STATE / "home"
    if private_home.exists():
        home_mode = stat.S_IMODE(private_home.stat().st_mode)
        if not private_home.is_dir() or home_mode & 0o077:
            fail(f"private runtime HOME is not owner-only (mode {home_mode:04o})")
    if not (STATE / "api-key").read_text().strip() or not (STATE / "secret-key").read_text().strip():
        fail("API/session secret is empty")
    auth_header = (STATE / "auth-header").read_text().strip()
    if not auth_header.startswith("Authorization: Bearer "):
        fail("auth-header is malformed")
    if auth_header.removeprefix("Authorization: Bearer ") != (STATE / "api-key").read_text().strip():
        fail("auth-header does not match api-key")

    sandbox = ROOT / "sandbox.sb"
    sandbox_text = sandbox.read_text(encoding="utf-8") if sandbox.is_file() else ""
    if "(deny network-outbound)" not in sandbox_text or "(allow default)" not in sandbox_text:
        fail("outbound network sandbox is missing or malformed")
    secure_entrypoint = ROOT / "secure_server.py"
    secure_text = secure_entrypoint.read_text(encoding="utf-8") if secure_entrypoint.is_file() else ""
    required_route_literals = (
        '("GET", "/health")',
        '("GET", "/api/status")',
        '("GET", "/v1/models")',
        '("GET", "/v1/models/status")',
        '("POST", "/v1/completions")',
        '("POST", "/v1/chat/completions")',
    )
    if not all(item in secure_text for item in required_route_literals):
        fail("secure API route allowlist is missing")
    required_context_guard_literals = (
        "NATIVE_CONTEXT_WINDOW = 262_144",
        "ALLOWED_CONTEXT_WINDOWS = frozenset({32_768, NATIVE_CONTEXT_WINDOW})",
        "MAX_OUTPUT_TOKENS = 8_192",
        "def _validate_prompt_budget(",
        "def _max_cache_position(",
        "def _bounded_mtp_draft_depth(",
        "def _request_output_scope(",
        "_REQUEST_OUTPUT_BUDGET.reset(token)",
        "def _record_prompt_tokens(",
        "budget.request.max_tokens = _bounded_max_tokens(",
        "def _install_total_context_guard(",
        "def _install_request_rebinding_guard(",
        "def _install_mtp_position_guard(",
        "mtp_batch._mtp_head_trim_to(state.mtp_cache, state.hist_offset)",
        "_qwen_secure_guarded_functions",
        "routes=selected",
        "lifespan=server_module.lifespan",
        "exception_handlers=dict(upstream_app.exception_handlers)",
        '"MTP target forward violated the active position budget"',
        '"MTP head forward violated the active position budget"',
        '"MTP verify cycle violated the active cache-position budget"',
        "server_module.validate_context_window = validate_total_context",
        "async def create_bounded_completion(",
        "async def create_bounded_chat_completion(",
        "reset_contextvars=True",
        "effective_context - int(prompt_tokens)",
    )
    if not all(item in secure_text for item in required_context_guard_literals):
        fail("native total-context/output guard is missing")
    for legacy_guard in (
        "_PROMPT_TOKEN_COUNT",
        "server_module.get_sampling_params =",
        "_PromptBudgetScopeMiddleware",
    ):
        if legacy_guard in secure_text:
            fail(f"legacy streaming ContextVar handshake remains: {legacy_guard}")
    for forbidden in ('"/admin"', '"/v1/web', '"/v1/mcp', '"/v1/models/{model_id}/load"'):
        if forbidden in secure_text:
            fail(f"secure API entrypoint includes forbidden route {forbidden}")

    settings = load_json(STATE / "settings.json")
    server = settings.get("server") or {}
    model = settings.get("model") or {}
    scheduler = settings.get("scheduler") or {}
    memory = settings.get("memory") or {}
    cache = settings.get("cache") or {}
    auth = settings.get("auth") or {}
    mcp = settings.get("mcp") or {}
    integrations = settings.get("integrations") or {}
    network = settings.get("network") or {}
    if server.get("host") != "127.0.0.1" or int(server.get("port", 0)) != 8086:
        fail("server must be fixed to 127.0.0.1:8086")
    if server.get("server_aliases") != ["127.0.0.1", "localhost"]:
        fail("fixed loopback aliases are not configured")
    if server.get("distributed_inference_enabled") is not False:
        fail("distributed inference is not disabled")
    if int(scheduler.get("max_concurrent_requests", 0)) != 1:
        fail("benchmark profile must allow exactly one concurrent request")
    if memory.get("prefill_memory_guard") is not True or memory.get("memory_guard_tier") != "safe":
        fail("safe prefill memory guard is not enabled")
    if cache.get("enabled") is not True or cache.get("hot_cache_only") is not False:
        fail("paged SSD cache must be enabled without hot-cache-only mode")
    cache_size = cache.get("ssd_cache_max_size")
    if cache_size not in {"20GB", "40GB"} or str(cache.get("hot_cache_max_size")) != "0":
        fail("cache limits must remain 20GB/40GB SSD and zero reserved hot cache")
    if auth.get("skip_api_key_verification") is not False:
        fail("API key verification is disabled")
    if auth.get("secret_key") != "environment-managed-by-ornith-omlx" or auth.get("api_key"):
        fail("settings.json contains or requests persistent real auth secrets")
    if mcp.get("config_path") is not None or mcp.get("expose_tools") is not False:
        fail("MCP is not fully disabled")
    if integrations.get("markitdown_enabled") is not False or integrations.get("markitdown_expose_model") is not False:
        fail("MarkItDown is not disabled")
    if integrations.get("web_search_provider") != "ddgs_custom" or integrations.get("web_search_ddgs_backends"):
        fail("web search is not configured fail-closed")
    if any(network.get(key) for key in ("http_proxy", "https_proxy", "ca_bundle")):
        fail("persistent outbound network/proxy settings are present")

    expected_model_dir = ROOT / "models"
    configured_model_dirs = model.get("model_dirs")
    configured_model_dir = model.get("model_dir")
    try:
        configured_paths = [Path(item) for item in configured_model_dirs]
        configured_primary = Path(configured_model_dir)
        paths_match_isolated_dir = (
            len(configured_paths) == 1
            and configured_paths[0].is_absolute()
            and configured_primary.is_absolute()
            and configured_paths[0].samefile(expected_model_dir)
            and configured_primary.samefile(expected_model_dir)
        )
    except (OSError, TypeError, ValueError):
        paths_match_isolated_dir = False
    if not paths_match_isolated_dir:
        fail("model discovery escaped the isolated profile")
    link = ROOT / "models" / "ornith15-omlx"
    if not link.is_symlink() or link.resolve() != MODEL.resolve():
        fail("isolated model alias does not resolve to the pinned checkpoint")

    model_settings = load_json(STATE / "model_settings.json")
    models = model_settings.get("models") or {}
    if set(models) != {"ornith15-omlx"}:
        fail(f"unexpected persisted model settings: {sorted(models)}")
    profile = models["ornith15-omlx"]
    sampling = settings.get("sampling") or {}
    context_values = {
        int(sampling.get("max_context_window", 0)),
        int(sampling.get("max_context_window_policy", 0)),
        int(profile.get("max_context_window", 0)),
    }
    if len(context_values) != 1:
        fail("global, policy, and per-model context windows must match")
    effective_context = next(iter(context_values))
    if effective_context not in {32_768, 262_144}:
        fail("effective context window must be either rollback 32768 or native 262144")
    if effective_context == 262_144 and cache_size != "40GB":
        fail("native 262144 context requires the 40GB SSD cache policy")
    if int(sampling.get("max_tokens", 0)) != 8192 or int(profile.get("max_tokens", 0)) != 8192:
        fail("generation output limit must remain fixed to 8192 tokens")
    required_false = (
        "trust_remote_code",
        "turboquant_kv_enabled",
        "qwen35_ane_prefill_enabled",
        "specprefill_enabled",
        "dflash_enabled",
        "vlm_mtp_enabled",
    )
    if any(profile.get(key) is not False for key in required_false):
        fail("one or more forbidden model acceleration/code paths are enabled")
    if profile.get("mtp_enabled") is not True or int(profile.get("mtp_num_draft_tokens", 0)) != 3:
        fail("Lightning MTP depth 1..3 is not enabled")
    if profile.get("model_type_override") != "llm":
        fail("checkpoint is not forced through the text-only engine")
    if profile.get("model_alias") != "ornith15-omlx" or profile.get("is_pinned") is not True:
        fail("model identity/pinning mismatch")

    # Avoid accepting hostile inherited overrides when the launcher is invoked
    # manually. The launcher itself sets only the explicit safe values.
    allowed = {
        "OMLX_BASE_PATH",
        "OMLX_SECURE_ENTRYPOINT",
        "OMLX_BONJOUR",
        "OMLX_NAX",
        "OMLX_QWEN35_QMM_NAX",
        "OMLX_QWEN35_ANE_PREFILL",
        "QWEN_OMLX_BENCHMARK_NO_CACHE",
    }
    inherited = sorted(name for name in os.environ if name.startswith("OMLX_") and name not in allowed)
    if inherited:
        fail(f"unexpected inherited oMLX overrides: {', '.join(inherited)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="skip full wheel/shard SHA-256 reads")
    args = parser.parse_args()

    validate_runtime(args.quick)
    validate_checkpoint(args.quick)
    validate_isolation()
    validate_total_context_guard()
    validate_route_task_graph()
    mode = "quick structural" if args.quick else "full cryptographic"
    print(f"experiment valid ({mode}); revision={EXPECTED_REVISION}; mtp_tensors=29; outbound=denied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
