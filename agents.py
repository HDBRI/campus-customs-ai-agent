"""Campus Customs agent - PydanticAI entry point.

Usage (`python agent.py ...` works the same way):
    python agents.py --image "data/test_images/image_01_true.jpeg"   # saves output/identify_product_single.json
    python agents.py --eval      # all test images, check vs _true/_false, save list to output/identify_product.json
    python agents.py --video "data/videos/ad_humble.mp4" --profile "profiles/profile_student.json"
                                 # saves output/ad_effectiveness.json
"""

from __future__ import annotations

import argparse
import asyncio
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import TypeAdapter
from pydantic_ai import CallToolsNode, ModelRequestNode, ToolOutput
from pydantic_ai.messages import RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.usage import UsageLimits

import tools
from models import (
    AdEffectiveness, AdVideoAnalysis, AudioFeatures, AuditEntry, AuditToolCall, AuditToolResult, CustomerProfile, ProductIdentification, ProductsInVideo, VideoFrames,
)

IdentificationList = TypeAdapter(list[ProductIdentification])

HERE = Path(__file__).resolve().parent
OUTPUT_PATH = HERE / "output" / "identify_product.json"  # --eval: list of all test images
SINGLE_OUTPUT_PATH = HERE / "output" / "identify_product_single.json"  # --image: one result
AD_OUTPUT_PATH = HERE / "output" / "ad_effectiveness.json"  # --video + --profile
SYSTEM_PROMPT = (HERE / "prompts" / "prompt.md").read_text(encoding="utf-8")

async def judge_ad_for_customer(video_path: str, profile_path: str) -> AdEffectiveness:
    """Score how effective the ad is at getting this customer to shop at Campus Customs. Call this last.

    Its return value becomes the agent's final answer directly.

    Args:
        video_path: Path to the video, absolute or relative to the HW3 folder.
        profile_path: Path to the customer profile JSON.
    """
    return await tools.judge_ad_for_customer(video_path, profile_path)


agent = tools.Agent(
    tools.get_model(),
    output_type=[
        ProductIdentification,
        # Output function: the judge's AdEffectiveness is returned as-is, so the model never retypes
        # the large JSON (in testing, that retype timed out on every attempt).
        ToolOutput(judge_ad_for_customer, name="judge_ad_for_customer"),
    ],
    instructions=SYSTEM_PROMPT,
)


# --- ability 1: product identification ---------------------------------------------------------


@agent.tool_plain
async def identify_product(image_path: str) -> ProductIdentification:
    """Check whether a Campus Customs product appears in the image at image_path, and which one.

    Args:
        image_path: Path to the photo, absolute or relative to the HW3 folder.
    """
    return await tools.identify_product(image_path)


# --- ability 2: ad effectiveness for a customer ------------------------------------------------


@agent.tool_plain
def load_customer_profile(profile_path: str) -> CustomerProfile:
    """Load and validate a customer profile JSON file.

    Args:
        profile_path: Path to the profile JSON, absolute or relative to the HW3 folder.
    """
    return tools.load_customer_profile(profile_path)


@agent.tool_plain
async def sample_video_frames(video_path: str) -> VideoFrames:
    """Extract up to 10 evenly spaced frames from the video (local, no AI) and report duration, size and audio.

    Args:
        video_path: Path to the video, absolute or relative to the HW3 folder.
    """
    return await tools.sample_video_frames(video_path)


@agent.tool_plain
async def analyze_audio_track(video_path: str) -> AudioFeatures:
    """Measure the ad's soundtrack locally (loudness, silence, tempo, bass). It can't hear lyrics or name the song.

    Args:
        video_path: Path to the video, absolute or relative to the HW3 folder.
    """
    return await tools.analyze_audio_track(video_path)


@agent.tool_plain
async def analyze_ad_video(video_path: str) -> AdVideoAnalysis:
    """Describe what the ad shows: hook, scenes, on-screen text, tone, references, branding and call to action.

    Args:
        video_path: Path to the video, absolute or relative to the HW3 folder.
    """
    return await tools.analyze_ad_video(video_path)


@agent.tool_plain
async def find_products_in_video(video_path: str) -> ProductsInVideo:
    """Identify which Campus Customs catalogue products appear in the ad (checks up to 3 key frames).

    Call analyze_ad_video first so the clearest frames are checked.

    Args:
        video_path: Path to the video, absolute or relative to the HW3 folder.
    """
    return await tools.find_products_in_video(video_path)




# --- running ------------------------------------------------------------------------------------


# --- audit trail ------------------------------------------------------------------------------------

# Hard caps per agent run. A normal run needs 2 model requests (image) or 4 (ad) and 1-5 tool calls;
# the caps stop a confused agent from looping and running up cost.
MAX_MODEL_REQUESTS = 10
MAX_TOOL_CALLS = 12
RUN_LIMITS = UsageLimits(request_limit=MAX_MODEL_REQUESTS, tool_calls_limit=MAX_TOOL_CALLS)

AUDIT_PATH = HERE / "output" / "audit_trail.json"
AuditList = TypeAdapter(list[AuditEntry])
_audit_lock = asyncio.Lock()  # --eval runs agents concurrently in one process


def _short(value: object, limit: int = 240) -> str:
    """Key fields of a tool result, not the whole object (and never image data)."""
    if isinstance(value, ProductIdentification):
        text = (f"present={value.product_present} id={value.product_id} conf={value.confidence:.2f}"
                + (f" error={value.error}" if value.error else ""))
    elif isinstance(value, AdEffectiveness):
        text = f"{value.verdict} {value.overall_score}/100 purchase_likelihood={value.purchase_likelihood:.2f}"
    elif isinstance(value, AdVideoAnalysis):
        text = f"summary: {value.summary}"
    elif isinstance(value, ProductsInVideo):
        text = f"products={value.product_ids} possible={value.possible_alternatives}"
    elif isinstance(value, CustomerProfile):
        text = f"{value.name} ({value.customer_type})"
    elif isinstance(value, VideoFrames):
        text = f"{len(value.frames)} frames, {value.duration_s}s, audio={value.has_audio}"
    elif isinstance(value, AudioFeatures):
        text = value.summary
    else:
        text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _short_args(args: object, limit: int = 600) -> object:
    """Tool arguments as sent; very long ones (e.g. a final answer echoed as arguments) are truncated."""
    text = args if isinstance(args, str) else None
    if text is None:
        return args
    return text if len(text) <= limit else text[: limit - 3] + "..."


async def _append_audit(entry: AuditEntry) -> None:
    """Append one entry. The file stays a valid JSON list; earlier runs are never wiped."""
    async with _audit_lock:
        entries: list[AuditEntry] = []
        if AUDIT_PATH.exists() and AUDIT_PATH.stat().st_size:
            entries = AuditList.validate_json(AUDIT_PATH.read_bytes())
        entries.append(entry)
        AUDIT_PATH.parent.mkdir(exist_ok=True)
        tmp = AUDIT_PATH.with_suffix(".tmp")
        tmp.write_bytes(AuditList.dump_json(entries, indent=2))
        tmp.replace(AUDIT_PATH)  # atomic swap, so a crash can't leave a half-written file


async def run_with_audit(user_text: str):
    """Run the agent step by step, appending an AuditEntry after every loop iteration."""
    run_id = uuid.uuid4().hex[:12]
    start = time.perf_counter()
    step = 0

    def entry(**fields) -> AuditEntry:
        nonlocal step
        e = AuditEntry(timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"), run_id=run_id,
                       step=step, duration_s=round(time.perf_counter() - start, 2), **fields)
        step += 1
        return e

    await _append_audit(entry(kind="request", action_summary="Run started.", user_request=user_text))
    try:
        async with agent.iter(user_text, usage_limits=RUN_LIMITS) as run:
            async for node in run:
                if isinstance(node, CallToolsNode):  # the model just answered
                    resp = node.model_response
                    calls = [p for p in resp.parts if isinstance(p, ToolCallPart)]
                    text = " ".join(p.content for p in resp.parts if isinstance(p, TextPart)).strip()  # visible text only
                    names = ", ".join(c.tool_name for c in calls)
                    await _append_audit(entry(
                        kind="model_response",
                        action_summary=f"Model chose to call: {names}." if calls else "Model replied without calling a tool.",
                        model_text=text[:500] or None,
                        tool_calls=[AuditToolCall(tool_name=c.tool_name, tool_call_id=c.tool_call_id, args=_short_args(c.args)) for c in calls],
                        stop_reason=resp.finish_reason, model_name=resp.model_name,
                        input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
                    ))
                elif isinstance(node, ModelRequestNode):  # tool results going back to the model
                    returns = [p for p in node.request.parts if isinstance(p, ToolReturnPart)]
                    retries = [p for p in node.request.parts if isinstance(p, RetryPromptPart)]
                    if returns or retries:
                        results = [AuditToolResult(tool_name=p.tool_name, tool_call_id=p.tool_call_id, ok=True,
                                                   summary=_short(p.content)) for p in returns]
                        results += [AuditToolResult(tool_name=p.tool_name or "?", tool_call_id=p.tool_call_id, ok=False,
                                                    summary=_short(p.content)) for p in retries]
                        await _append_audit(entry(
                            kind="tool_results",
                            action_summary=f"{len(results)} tool result(s) returned to the model.",
                            tool_results=results,
                        ))
        output = run.result.output
        await _append_audit(entry(
            kind="final_output", action_summary=f"Run finished with a {type(output).__name__}.",
            tool_results=[AuditToolResult(tool_name="final_output", ok=True, summary=_short(output))],
            stop_reason="final_output", input_tokens=run.usage.input_tokens, output_tokens=run.usage.output_tokens,
        ))
        return run.result
    except Exception as exc:
        await _append_audit(entry(kind="error", action_summary="Run failed.", stop_reason=f"error: {type(exc).__name__}",
                                  model_text=_short(str(exc), 500)))
        raise


async def run_agent(user_text: str) -> ProductIdentification | AdEffectiveness:
    return (await run_with_audit(user_text)).output


def as_request(image_path: str) -> str:
    return f"Does a Campus Customs product appear in {image_path}? If so, which one?"


def as_ad_request(video_path: str, profile_path: str) -> str:
    return (f"How effective would the ad video {video_path} be at convincing the customer in {profile_path} "
            "to shop at Campus Customs?")


def print_result(r: ProductIdentification) -> None:
    verdict = f"YES - {r.product_title} ({r.product_id})" if r.product_id else ("YES - can't tell which" if r.product_present else "NO")
    print(f"\n{r.image_path}\n  {verdict}  confidence={r.confidence:.2f}")
    if r.alternatives:
        print(f"  alternatives: {', '.join(r.alternatives)}")
    print(f"  evidence: {'; '.join(r.evidence)}")
    print(f"  reasoning: {r.reasoning}")
    print(f"  shortlist ({len(r.candidates_checked)}): {', '.join(c.product_id for c in r.candidates_checked)}")


def print_ad_result(r: AdEffectiveness) -> None:
    print(f"\n{r.video_path}  x  {r.customer_name} ({r.profile_path})")
    print(f"  {r.verdict.upper()}  overall={r.overall_score}/100  purchase_likelihood={r.purchase_likelihood:.2f}  confidence={r.confidence:.2f}")
    for d in r.dimensions:
        print(f"  {d.name:<18} {d.score:>2}/10  {d.rationale}")
    print(f"  products featured: {', '.join(r.products_featured) or 'none identified'}")
    print(f"  reasoning: {r.reasoning}")


async def evaluate(trace_dir: Path | None = None) -> None:
    """Run every test image concurrently, score against the filename, save all outputs."""
    images = sorted((HERE / "data" / "test_images").glob("*.jp*g"))

    async def timed(path: Path):
        t = time.perf_counter()
        run = await run_with_audit(as_request(path.relative_to(HERE).as_posix()))
        return run, time.perf_counter() - t

    start = time.perf_counter()
    runs = await asyncio.gather(*(timed(p) for p in images))
    correct = 0
    for path, (run, secs) in zip(images, runs):
        r = run.output
        expected = path.stem.endswith("_true")
        ok = r.error is None and r.product_present == expected
        correct += ok
        print_result(r)
        print(f"  expected present={expected} -> {'CORRECT' if ok else 'WRONG'}  ({secs:.1f}s)")
        if trace_dir:  # full message history: tool calls, tool returns, final output
            trace_dir.mkdir(parents=True, exist_ok=True)
            (trace_dir / f"{path.stem}.json").write_bytes(run.all_messages_json())
    print(f"\n{correct}/{len(images)} correct in {time.perf_counter() - start:.1f}s")

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_bytes(IdentificationList.dump_json([run.output for run, _ in runs], indent=2))
    print(f"Saved {len(runs)} results to {OUTPUT_PATH.relative_to(HERE).as_posix()}")


def save(result: ProductIdentification | AdEffectiveness, path: Path) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(f"\nSaved to {path.relative_to(HERE).as_posix()}")


AdResultList = TypeAdapter(list[AdEffectiveness])


def save_ad_result(result: AdEffectiveness) -> None:
    """Keep one result per (video, profile) in output/ad_effectiveness.json, so runs for different profiles add up."""
    existing: list[AdEffectiveness] = []
    if AD_OUTPUT_PATH.exists():
        raw = AD_OUTPUT_PATH.read_bytes()
        try:
            existing = AdResultList.validate_json(raw)
        except ValueError:  # older single-object file
            existing = [AdEffectiveness.model_validate_json(raw)]
    kept = [r for r in existing if (r.video_path, r.profile_path) != (result.video_path, result.profile_path)]
    AD_OUTPUT_PATH.parent.mkdir(exist_ok=True)
    AD_OUTPUT_PATH.write_bytes(AdResultList.dump_json([*kept, result], indent=2))
    print(f"\nSaved to {AD_OUTPUT_PATH.relative_to(HERE).as_posix()} ({len(kept) + 1} result(s))")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", help="photo to check for a Campus Customs product")
    parser.add_argument("--eval", action="store_true", help="run every image in data/test_images, save all results")
    parser.add_argument("--trace", type=Path, help="with --eval: folder to save each run's full message history")
    parser.add_argument("--video", help="ad video to judge (use with --profile)")
    parser.add_argument("--profile", help="customer profile JSON (use with --video)")
    args = parser.parse_args()

    if args.eval:
        asyncio.run(evaluate(args.trace))
    elif args.video or args.profile:
        if not (args.video and args.profile):
            parser.error("--video and --profile must be used together")
        start = time.perf_counter()
        result = asyncio.run(run_agent(as_ad_request(args.video, args.profile)))
        if not isinstance(result, AdEffectiveness):
            raise SystemExit(f"Agent returned {type(result).__name__} instead of AdEffectiveness")
        print_ad_result(result)
        print(f"  ({time.perf_counter() - start:.1f}s)")
        save_ad_result(result)
    elif args.image:
        result = asyncio.run(run_agent(as_request(args.image)))
        if not isinstance(result, ProductIdentification):
            raise SystemExit(f"Agent returned {type(result).__name__} instead of ProductIdentification")
        print_result(result)
        save(result, SINGLE_OUTPUT_PATH)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
