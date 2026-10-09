"""Tools and helpers for the Campus Customs agent.

Product identification is a three-stage pipeline, so we never compare the query
photo against all 102 catalogue images one by one:

1. describe_photo   - one vision call turns the query photo into GarmentObservations,
                      using the same vocabulary as the catalogue.
2. shortlist        - local BM25 + attribute scoring against catalogue.json. No API
                      calls, runs in milliseconds, returns the top MAX_CANDIDATES.
3. verify_shortlist - one vision call that sees the query photo plus at most 10
                      candidate product photos and picks the match (or none).

Ad effectiveness (video + customer profile) adds five tools:

- load_customer_profile  - validate a profile JSON into a CustomerProfile.
- sample_video_frames    - ffmpeg pulls evenly spaced frames locally (no AI call).
- analyze_ad_video       - one vision call over <= 10 frames -> AdVideoAnalysis.
- find_products_in_video - runs identify_product on up to 3 key frames, concurrently.
- judge_ad_for_customer  - one call scores the ad against the profile -> AdEffectiveness.
"""

from __future__ import annotations

import asyncio
import math
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from models import (
    AdEffectiveness, AdJudgement, AdVideoAnalysis, AudioFeatures, Catalogue, CatalogueEntry, CandidateProduct,
    CustomerProfile, GarmentObservation, MatchVerdict, ProductIdentification, ProductsInVideo,
    QueryPhotoAnalysis, VideoFrame, VideoFrames,
)

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
load_dotenv(HERE.parent / ".env")

MODEL_NAME = os.getenv("AI_MODEL", "gpt-5.6-luna")

def _load_safety_rules() -> str:
    """The safety section of prompts/prompt.md, shared with every vision sub-agent so one copy governs all image calls."""
    text = (HERE / "prompts" / "prompt.md").read_text(encoding="utf-8")
    m = re.search(r"^## Safety rules.*?(?=^## )", text, flags=re.S | re.M)
    return m.group(0).strip() if m else ""


SAFETY_RULES = _load_safety_rules()
CATALOGUE_PATH = HERE / "catalogue.json"
MAX_CANDIDATES = 10  # hard cap on product images per vision call
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}

DESCRIBE_INSTRUCTIONS = """You look at photos of people and list the tops or outerwear they're wearing
(t-shirts, long-sleeves, crewnecks, hoodies, zips, fleeces, jackets). For each, record exactly
what is visible: garment type, colors, every readable word printed on it (exactly as written,
even if partly hidden, e.g. 'Y_LE'), graphics or crests, where the design sits, and any brand.
Ignore signs, backgrounds and other objects. If nobody is wearing a top, return no garments."""

VERIFY_INSTRUCTIONS = """You decide whether a Campus Customs catalogue product appears in a query photo.
You're given the query photo, then up to 10 candidate product photos, each labelled with its product ID.
- A product is present only if a garment in the photo matches a candidate's garment type, color, and
  printed text or graphic. Similar generic clothing or another brand's logo is NOT a match.
- Text may be partly hidden by arms, folds or angle; judge the visible letters and layout.
- If the photo clearly shows a catalogue design but two candidates can't be told apart, set
  product_present=true, product_id=null, and list them in alternatives.
- product_id must be one of the given candidate IDs, or null.
- confidence is a real probability that your verdict is correct; don't default to 0.5."""


# --- model / catalogue -------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_model() -> OpenAIChatModel:
    key = os.getenv("PORTKEY_API_KEY")
    if not key:
        raise RuntimeError("PORTKEY_API_KEY is missing from HW3/.env or the repository-root .env")
    client = AsyncOpenAI(api_key=key, base_url=os.getenv("PORTKEY_BASE_URL", "https://api.portkey.ai/v1"),
                         default_headers={"x-portkey-provider": os.getenv("PORTKEY_PROVIDER", "openai")},
                         timeout=120, max_retries=2)  # fail instead of hanging forever on a stuck request
    return OpenAIChatModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


@lru_cache(maxsize=1)
def load_catalogue() -> dict[str, CatalogueEntry]:
    if not CATALOGUE_PATH.exists():
        raise RuntimeError("catalogue.json not found - run build_catalogue.py first")
    catalogue = Catalogue.model_validate_json(CATALOGUE_PATH.read_text(encoding="utf-8"))
    return {e.product_id: e for e in catalogue.entries}


def load_image(path: str | Path) -> BinaryContent:
    path = Path(path)
    if not path.is_absolute():
        path = HERE / path
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")
    return BinaryContent(data=path.read_bytes(), media_type=IMAGE_TYPES.get(path.suffix.lower(), "image/jpeg"))


# --- stage 1: describe the query photo -----------------------------------------------------


@lru_cache(maxsize=1)
def _describe_agent() -> Agent[None, QueryPhotoAnalysis]:
    return Agent(get_model(), output_type=QueryPhotoAnalysis, instructions=[DESCRIBE_INSTRUCTIONS, SAFETY_RULES])


async def describe_photo(image_path: str | Path) -> QueryPhotoAnalysis:
    result = await _describe_agent().run(["Describe the garments worn in this photo.", load_image(image_path)])
    return result.output


# --- stage 2: local retrieval --------------------------------------------------------------

STOPWORDS = {"a", "an", "and", "the", "of", "on", "in", "with", "at", "to", "is", "its", "it", "for", "by", "as"}
GARMENT_FAMILY = {
    "t-shirt": "light", "long-sleeve": "light",
    "crewneck": "sweat", "hoodie": "sweat", "sweater": "sweat", "mockneck": "sweat",
    "quarter-zip": "zip", "full-zip": "zip", "fleece-jacket": "zip", "jacket": "zip",
}
COLOR_FAMILY = {
    "navy": "blue", "blue": "blue", "royal": "blue", "grey": "grey", "gray": "grey", "heather": "grey",
    "charcoal": "grey", "silver": "grey", "white": "white", "ivory": "white", "cream": "white",
    "black": "black", "red": "red", "maroon": "red", "green": "green", "olive": "green",
}


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS and len(t) > 1]


def color_family(color: str) -> str | None:
    return next((fam for word, fam in COLOR_FAMILY.items() if word in color.lower()), None)


class _BM25:
    """Tiny BM25 index so we don't need an embeddings endpoint."""

    def __init__(self, docs: dict[str, list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.docs, self.k1, self.b = docs, k1, b
        self.tf = {pid: Counter(toks) for pid, toks in docs.items()}
        self.avg_len = sum(len(t) for t in docs.values()) / max(len(docs), 1)
        df = Counter(tok for toks in docs.values() for tok in set(toks))
        n = len(docs)
        self.idf = {tok: math.log(1 + (n - d + 0.5) / (d + 0.5)) for tok, d in df.items()}

    def score(self, query: list[str], pid: str) -> float:
        tf, length = self.tf[pid], len(self.docs[pid])
        total = 0.0
        for tok in set(query):
            if tok in tf:
                f = tf[tok]
                total += self.idf[tok] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / self.avg_len))
        return total


@lru_cache(maxsize=1)
def _indexes() -> tuple[_BM25, _BM25]:
    cat = load_catalogue()
    full = _BM25({pid: tokenize(e.search_text + " " + pid.replace("-", " ")) for pid, e in cat.items()})
    text = _BM25({pid: tokenize(" ".join(e.printed_text + e.graphics)) for pid, e in cat.items()})
    return full, text


def score_product(obs: GarmentObservation, entry: CatalogueEntry) -> float:
    full, text = _indexes()
    query_all = tokenize(" ".join([obs.description, obs.garment_type, obs.primary_color, *obs.secondary_colors,
                                   *obs.printed_text, *obs.graphics, obs.brand or ""]))
    query_text = tokenize(" ".join(obs.printed_text + obs.graphics))
    score = full.score(query_all, entry.product_id) + 2.0 * text.score(query_text, entry.product_id)

    # Structural agreement: cheap to see in a photo, and a strong filter.
    if obs.garment_type == entry.garment_type:
        score += 3.0
    elif GARMENT_FAMILY.get(obs.garment_type) == GARMENT_FAMILY.get(entry.garment_type):
        score += 1.0
    if color_family(obs.primary_color) and color_family(obs.primary_color) == color_family(entry.primary_color):
        score += 1.5
    if obs.has_hood != entry.has_hood:
        score -= 2.0
    if obs.has_zipper != entry.has_zipper:
        score -= 2.0
    if obs.sleeve_length != entry.sleeve_length and "none" not in (obs.sleeve_length, entry.sleeve_length):
        score -= 1.0
    return score


def shortlist(analysis: QueryPhotoAnalysis, k: int = MAX_CANDIDATES) -> list[CandidateProduct]:
    """Best-scoring catalogue products across all garments in the photo, capped at k."""
    cat = load_catalogue()
    best: dict[str, float] = {}
    for obs in analysis.garments:
        for pid, entry in cat.items():
            s = score_product(obs, entry)
            best[pid] = max(best.get(pid, float("-inf")), s)
    top = sorted(best.items(), key=lambda kv: kv[1], reverse=True)[: min(k, MAX_CANDIDATES)]
    return [CandidateProduct(product_id=pid, title=cat[pid].title, retrieval_score=round(s, 2)) for pid, s in top]


# --- stage 3: visual verification --------------------------------------------------------------


@lru_cache(maxsize=1)
def _verify_agent() -> Agent[None, MatchVerdict]:
    return Agent(get_model(), output_type=MatchVerdict, instructions=[VERIFY_INSTRUCTIONS, SAFETY_RULES])


def _candidate_parts(candidates: list[CandidateProduct]) -> list[str | BinaryContent]:
    cat = load_catalogue()
    parts: list[str | BinaryContent] = []
    for i, c in enumerate(candidates, 1):
        e = cat[c.product_id]
        label = (f"Candidate {i} - product_id: {e.product_id}\nTitle: {e.title}\n"
                 f"Text on garment: {', '.join(e.printed_text) or 'none'} | Graphics: {', '.join(e.graphics) or 'none'}")
        if e.source == "manual":
            # The API rejects this product photo, so send its written description instead.
            parts.append(f"{label}\n(Photo unavailable. Description: {e.description})")
        else:
            parts += [label, load_image(e.image_path)]
    return parts


async def verify_shortlist(image_path: str | Path, candidates: list[CandidateProduct]) -> MatchVerdict:
    assert len(candidates) <= MAX_CANDIDATES
    prompt = ["QUERY PHOTO:", load_image(image_path), "CANDIDATE PRODUCTS:", *_candidate_parts(candidates),
              "Does any garment in the query photo match one of these candidates?"]
    result = await _verify_agent().run(prompt)
    return result.output


# --- the tool --------------------------------------------------------------------------------


async def identify_product(image_path: str) -> ProductIdentification:
    """Decide whether a Campus Customs product appears in the image, and which one."""
    candidates: list[CandidateProduct] = []
    try:
        analysis = await describe_photo(image_path)
        if not analysis.garments:
            return ProductIdentification(
                image_path=image_path, product_present=False, confidence=0.9,
                reasoning=f"No tops or outerwear visible. Scene: {analysis.scene_summary}",
            )
        candidates = shortlist(analysis)
        verdict = await verify_shortlist(image_path, candidates)
    except ModelHTTPError as exc:
        # Report the failure honestly instead of guessing a verdict.
        return ProductIdentification(
            image_path=image_path, product_present=False, confidence=0.0, candidates_checked=candidates,
            reasoning="The vision model could not analyse this request, so no verdict was made.",
            error=f"{exc.status_code}: {exc.body.get('code') if isinstance(exc.body, dict) else exc.body}",
        )

    cat = load_catalogue()
    ids = {c.product_id for c in candidates}
    product_id = verdict.product_id if verdict.product_id in ids else None  # never trust an ID we didn't offer
    return ProductIdentification(
        image_path=image_path,
        product_present=verdict.product_present,
        product_id=product_id if verdict.product_present else None,
        product_title=cat[product_id].title if product_id and verdict.product_present else None,
        confidence=verdict.confidence,
        alternatives=[a for a in verdict.alternatives if a in ids and a != product_id],
        evidence=verdict.evidence,
        reasoning=verdict.reasoning,
        candidates_checked=candidates,
    )


# --- ad effectiveness: video + customer profile -----------------------------------------------

FRAMES_DIR = HERE / "frames"
MAX_VIDEO_FRAMES = 10  # same per-call image cap as identification
MAX_PRODUCT_FRAMES = 3
DIMENSION_NAMES = ["attention", "profile_relevance", "product_appeal", "brand_clarity", "persuasion", "tone_fit"]

JUDGE_RUNS = 3  # independent judge samples, combined by median, to steady the scores

ANALYZE_INSTRUCTIONS = """You are an advertising analyst reviewing an ad for Campus Customs, a store selling Yale apparel.
You get evenly spaced frames from the video, labelled with frame index and timestamp, plus measured audio
features (loudness, tempo, bass). You cannot hear the audio: never quote lyrics or dialogue, and describe the
sound only as far as the measurements support. Record on-screen text exactly. For cultural references (music
videos, songs, memes, trends), combine the staging, poses and framing with the audio measurements AND the video's
filename, which often names the reference. Say how confident you are in each reference. Be precise about whether
the Campus Customs store itself is named or shown, versus only Yale branding."""

JUDGE_INSTRUCTIONS = """You judge how effective an ad would be at getting ONE specific customer to shop at Campus Customs,
a store selling Yale apparel. You get the customer's profile, an analysis of the ad, the catalogue products
identified in it, and a few key frames. Score each of these six dimensions from 1 to 10, exactly once each:
- attention: would this person stop scrolling and watch?
- profile_relevance: does it reflect their identity, interests and world?
- product_appeal: would they want the products shown (style, fit with taste and budget)?
- brand_clarity: after watching, would they know it is Campus Customs and where to buy?
- persuasion: does it give them a reason and a way to act now (offer, call to action, urgency)?
- tone_fit: does the tone match their values and avoid their dislikes?
Tie every rationale to specific moments and specific profile traits. Use the whole scale; a 9-10 must be earned.
You get measured audio features but cannot hear the audio: weigh the soundtrack only as far as the analysis and
measurements support, and say so where it matters (e.g. a likely song reference for a music fan).
purchase_likelihood is a real probability. Recommendations must be concrete edits to this ad for this person.
Refer to the customer by name, or as they/them unless the profile states their pronouns. Describe people in the ad
by role (e.g. 'the lead performer') rather than guessing their gender."""


def _resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else HERE / path


def _rel(path: Path) -> str:
    try:
        return path.relative_to(HERE).as_posix()
    except ValueError:
        return path.as_posix()


def load_customer_profile(profile_path: str) -> CustomerProfile:
    path = _resolve(profile_path)
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {path}")
    return CustomerProfile.model_validate_json(path.read_text(encoding="utf-8"))


async def _ffmpeg(*args: str) -> str:
    """Run the ffmpeg bundled with imageio-ffmpeg (no system install needed); return stderr."""
    import imageio_ffmpeg

    proc = await asyncio.create_subprocess_exec(
        imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    return err.decode("utf-8", "replace")


# Per-process caches: the agent calls several tools on the same video, so each step runs once.
_frame_cache: dict[str, VideoFrames] = {}
_audio_cache: dict[str, AudioFeatures] = {}
_analysis_cache: dict[str, AdVideoAnalysis] = {}
_products_cache: dict[str, ProductsInVideo] = {}


async def analyze_audio_track(video_path: str) -> AudioFeatures:
    """Measure the soundtrack locally (ffmpeg decode + numpy): loudness, silence, tempo and bass. No AI call."""
    import imageio_ffmpeg
    import numpy as np

    path = _resolve(video_path)
    key = _rel(path)
    if key in _audio_cache:
        return _audio_cache[key]
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {path}")

    sr = 22050
    proc = await asyncio.create_subprocess_exec(
        imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    raw, _ = await proc.communicate()
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if x.size < sr // 2:
        result = AudioFeatures(has_audio=False, summary="No usable audio track.")
        _audio_cache[key] = result
        return result

    def dbfs(v: np.ndarray) -> np.ndarray:
        return 20 * np.log10(np.maximum(v, 1e-6))

    # Loudness in 50 ms windows.
    win = sr // 20
    frames = x[: x.size // win * win].reshape(-1, win)
    rms_db = dbfs(np.sqrt((frames ** 2).mean(axis=1)))
    silence = float((rms_db < -45).mean())

    # Tempo: autocorrelation of the onset envelope (positive energy changes) over 60-180 BPM.
    hop = 512
    env_frames = x[: x.size // hop * hop].reshape(-1, hop)
    energy = np.log1p(100 * (env_frames ** 2).sum(axis=1))
    onset = np.maximum(np.diff(energy), 0)
    onset -= onset.mean()
    ac = np.correlate(onset, onset, mode="full")[onset.size - 1:]
    fps = sr / hop
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 60)
    tempo = strength = None
    if ac[0] > 0 and hi < ac.size:
        lag = lo + int(np.argmax(ac[lo:hi]))
        tempo, strength = round(60 * fps / lag, 1), round(float(np.clip(ac[lag] / ac[0], 0, 1)), 2)

    # Bass share of spectral energy.
    spec = np.abs(np.fft.rfft(x)) ** 2
    freqs = np.fft.rfftfreq(x.size, 1 / sr)
    bass = float(spec[freqs < 150].sum() / max(spec.sum(), 1e-12))

    mean_db, peak_db = float(rms_db.mean()), float(dbfs(np.abs(x).max()))
    beat = ("a steady beat" if strength and strength >= 0.3 else
            "a weak or irregular beat" if strength and strength >= 0.15 else "no clear beat")
    summary = (f"Audio is {'mostly silent' if silence > 0.6 else 'present through most of the ad'} "
               f"(mean {mean_db:.0f} dBFS, {silence:.0%} near-silent), with {beat}"
               f"{f' around {tempo:.0f} BPM (could be half or double time)' if tempo else ''}, and "
               f"{'heavy' if bass > 0.35 else 'moderate' if bass > 0.15 else 'light'} bass ({bass:.0%} of energy below 150 Hz). "
               "Measurements only: lyrics, voiceover and the song itself are not identified.")
    result = AudioFeatures(
        has_audio=True, mean_loudness_dbfs=round(mean_db, 1), peak_loudness_dbfs=round(peak_db, 1),
        silence_ratio=round(silence, 2), tempo_bpm=tempo, tempo_strength=strength,
        bass_energy_ratio=round(bass, 2), summary=summary,
    )
    _audio_cache[key] = result
    return result


async def sample_video_frames(video_path: str, n_frames: int = MAX_VIDEO_FRAMES) -> VideoFrames:
    """Evenly spaced frames, extracted in parallel with ffmpeg and saved under frames/<video>/."""
    path = _resolve(video_path)
    n = max(1, min(n_frames, MAX_VIDEO_FRAMES))
    key = f"{path}:{n}"
    if key in _frame_cache:
        return _frame_cache[key]
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {path}")

    info = await _ffmpeg("-i", str(path))  # with no output file, ffmpeg just prints stream info
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
    size = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", info)
    if not dur:
        raise RuntimeError(f"Could not read video duration: {path.name}")
    duration = int(dur[1]) * 3600 + int(dur[2]) * 60 + float(dur[3])

    times = [round(duration * (i + 0.5) / n, 2) for i in range(n)]  # segment midpoints skip black first/last frames
    out_dir = FRAMES_DIR / path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = [out_dir / f"frame_{i:02d}_{t:05.2f}s.jpg" for i, t in enumerate(times)]
    await asyncio.gather(*(
        _ffmpeg("-y", "-loglevel", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                "-vf", "scale=960:-2", "-q:v", "3", str(target))
        for t, target in zip(times, targets)
    ))
    frames = [VideoFrame(index=i, timestamp_s=t, path=_rel(p)) for i, (t, p) in enumerate(zip(times, targets)) if p.exists()]
    result = VideoFrames(
        video_path=_rel(path), duration_s=round(duration, 2),
        width=int(size[1]) if size else 0, height=int(size[2]) if size else 0,
        has_audio="Audio:" in info, frames=frames,
    )
    _frame_cache[key] = result
    return result


def _frame_parts(frames: list[VideoFrame]) -> list[str | BinaryContent]:
    parts: list[str | BinaryContent] = []
    for f in frames[:MAX_VIDEO_FRAMES]:
        parts += [f"Frame {f.index} at {f.timestamp_s:.1f}s:", load_image(f.path)]
    return parts


@lru_cache(maxsize=1)
def _analyze_agent() -> Agent[None, AdVideoAnalysis]:
    return Agent(get_model(), output_type=AdVideoAnalysis, instructions=[ANALYZE_INSTRUCTIONS, SAFETY_RULES])


async def analyze_ad_video(video_path: str) -> AdVideoAnalysis:
    """Describe the ad's content, hook, tone and branding from up to 10 frames in one vision call."""
    key = _rel(_resolve(video_path))
    if key in _analysis_cache:
        return _analysis_cache[key]
    vf, audio = await asyncio.gather(sample_video_frames(video_path), analyze_audio_track(video_path))
    prompt = [f"Ad video filename: {Path(video_path).name} ({vf.duration_s:.1f}s, {vf.width}x{vf.height}).",
              f"Measured audio: {audio.summary}",
              *_frame_parts(vf.frames), "Analyse this ad."]
    result = await _analyze_agent().run(prompt)
    _analysis_cache[key] = result.output
    return result.output


def merge_lookalikes(sightings: list[ProductIdentification]) -> tuple[list[str], list[str]]:
    """Collapse IDs that different frames picked for what is probably the same garment.

    Two sighted IDs are linked when one sighting lists the other as a lookalike alternative.
    Each linked group keeps the ID with the most confidence-weighted votes; the rest become
    possible alternatives. Unlinked IDs (e.g. different people's clothes) are all kept.
    """
    votes: dict[str, float] = {}
    for s in sightings:
        if s.product_present and s.product_id:
            votes[s.product_id] = votes.get(s.product_id, 0.0) + s.confidence
    parent = {pid: pid for pid in votes}

    def find(p: str) -> str:
        while parent[p] != p:
            p = parent[p]
        return p

    for s in sightings:
        if s.product_id in votes:
            for alt in s.alternatives:
                if alt in votes:
                    parent[find(alt)] = find(s.product_id)

    groups: dict[str, list[str]] = {}
    for pid in votes:
        groups.setdefault(find(pid), []).append(pid)
    kept, alternatives = [], []
    for members in groups.values():
        members.sort(key=lambda p: votes[p], reverse=True)
        kept.append(members[0])
        alternatives += members[1:]
    kept.sort(key=lambda p: votes[p], reverse=True)
    return kept, alternatives


async def find_products_in_video(video_path: str) -> ProductsInVideo:
    """Run the identify pipeline on up to 3 key frames concurrently and collect catalogue products."""
    key = _rel(_resolve(video_path))
    if key in _products_cache:
        return _products_cache[key]
    vf = await sample_video_frames(video_path)
    analysis = _analysis_cache.get(key)
    picks = [i for i in (analysis.best_product_frame_indices if analysis else []) if 0 <= i < len(vf.frames)]
    if not picks:  # no analysis yet: spread the picks across the video
        last = len(vf.frames) - 1
        picks = [round(k * last / (MAX_PRODUCT_FRAMES - 1)) for k in range(MAX_PRODUCT_FRAMES)]
    picks = list(dict.fromkeys(picks))[:MAX_PRODUCT_FRAMES]
    sightings = await asyncio.gather(*(identify_product(vf.frames[i].path) for i in picks))
    ids, alternatives = merge_lookalikes(list(sightings))
    result = ProductsInVideo(video_path=vf.video_path, sightings=list(sightings), product_ids=ids,
                             possible_alternatives=alternatives)
    _products_cache[key] = result
    return result


@lru_cache(maxsize=1)
def _judge_agent() -> Agent[None, AdJudgement]:
    return Agent(get_model(), output_type=AdJudgement, instructions=[JUDGE_INSTRUCTIONS, SAFETY_RULES])


def _verdict(score: int) -> str:
    return "very effective" if score >= 80 else "effective" if score >= 65 else "mixed" if score >= 45 else "ineffective"


async def judge_ad_for_customer(video_path: str, profile_path: str) -> AdEffectiveness:
    """Score the ad for this customer. Reuses cached frames, analysis and products; computes any that are missing."""
    import statistics

    profile = load_customer_profile(profile_path)
    vf, audio = await asyncio.gather(sample_video_frames(video_path), analyze_audio_track(video_path))
    analysis = await analyze_ad_video(video_path)
    products = await find_products_in_video(video_path)

    cat = load_catalogue()
    product_lines = [f"- {pid}: {cat[pid].title} ({cat[pid].garment_type}, {cat[pid].primary_color})" for pid in products.product_ids]
    product_lines += [f"- possibly {pid} instead (lookalike): {cat[pid].title}" for pid in products.possible_alternatives]
    key_frames = [vf.frames[i] for i in analysis.best_product_frame_indices if 0 <= i < len(vf.frames)][:3] or vf.frames[:1]
    prompt = [
        "CUSTOMER PROFILE:\n" + profile.model_dump_json(indent=2),
        "AD ANALYSIS:\n" + analysis.model_dump_json(indent=2),
        "MEASURED AUDIO:\n" + audio.model_dump_json(indent=2),
        "CATALOGUE PRODUCTS IDENTIFIED IN THE AD:\n" + ("\n".join(product_lines) or "- none identified"),
        "KEY FRAMES:", *_frame_parts(key_frames),
        "Judge how effective this ad is at getting this customer to shop at Campus Customs.",
    ]

    # Several independent judges, run concurrently. The run label makes each request distinct, so
    # Portkey's cache can't replay one answer three times.
    async def one_run(k: int) -> AdJudgement | None:
        try:
            return (await _judge_agent().run([*prompt, f"(Independent judge run {k + 1} of {JUDGE_RUNS}.)"])).output
        except Exception:
            return None

    judgements = [j for j in await asyncio.gather(*(one_run(k) for k in range(JUDGE_RUNS))) if j]
    if not judgements:
        raise RuntimeError("Every judge run failed; no score was produced.")

    def scores(j: AdJudgement) -> dict[str, int]:
        return {d.name: d.score for d in j.dimensions}

    # Median score per dimension; the wording comes from the run closest to those medians.
    medians = {n: round(statistics.median(scores(j)[n] for j in judgements if n in scores(j)))
               for n in DIMENSION_NAMES if any(n in scores(j) for j in judgements)}
    rep = min(judgements, key=lambda j: sum(abs(scores(j).get(n, medians[n]) - m) for n, m in medians.items()))
    rep_dims = {d.name: d for d in rep.dimensions}
    fallback = {d.name: d for j in judgements for d in j.dimensions}
    dims = [(rep_dims.get(n) or fallback[n]).model_copy(update={"score": medians[n]}) for n in DIMENSION_NAMES if n in medians]

    overall = round(sum(d.score for d in dims) / len(dims) * 10) if dims else 0
    run_overalls = [round(sum(scores(j).values()) / max(len(scores(j)), 1) * 10) for j in judgements]

    limitations = [f"Judged from {len(vf.frames)} sampled frames, not continuous video."]
    if audio.has_audio:
        limitations.append("Soundtrack judged from measured features only (loudness, tempo, bass); lyrics, "
                           "voiceover and the song itself could not be heard, because the model endpoint accepts only text and images.")
    if len(judgements) < JUDGE_RUNS:
        limitations.append(f"Only {len(judgements)} of {JUDGE_RUNS} judge runs succeeded.")
    if len(dims) < len(DIMENSION_NAMES):
        limitations.append(f"Judges omitted dimensions: {sorted(set(DIMENSION_NAMES) - set(medians))}.")
    limitations += [f"Product check failed on {s.image_path}: {s.error}" for s in products.sightings if s.error]

    return AdEffectiveness(
        video_path=vf.video_path, profile_path=_rel(_resolve(profile_path)), customer_name=profile.name,
        overall_score=overall, verdict=_verdict(overall),
        purchase_likelihood=round(statistics.median(j.purchase_likelihood for j in judgements), 2),
        dimensions=dims, products_featured=products.product_ids, possible_products=products.possible_alternatives,
        audio=audio, judge_runs=len(judgements), overall_score_range=[min(run_overalls), max(run_overalls)],
        resonates_with=rep.resonates_with, falls_flat_on=rep.falls_flat_on, key_moments=rep.key_moments,
        recommendations=rep.recommendations, reasoning=rep.reasoning,
        confidence=round(statistics.median(j.confidence for j in judgements), 2), limitations=limitations,
    )
