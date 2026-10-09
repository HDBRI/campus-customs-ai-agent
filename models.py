"""Pydantic models for the HW3 product catalogue and the Campus Customs agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GarmentType = Literal[
    "t-shirt", "long-sleeve", "crewneck", "hoodie", "quarter-zip",
    "full-zip", "fleece-jacket", "jacket", "mockneck", "sweater", "other",
]


class ProductAttributes(BaseModel):
    """What the vision model extracts from one product photo."""

    title: str = Field(description="Short shop-style product name, e.g. 'Navy Yale Dad Crewneck'.")
    description: str = Field(description="2-3 sentence visual description: garment, colors, graphics, text, placement.")
    garment_type: GarmentType
    primary_color: str = Field(description="Main fabric color in plain words, e.g. 'navy', 'heather grey'.")
    secondary_colors: list[str] = Field(default_factory=list, description="Colors of print, trim, or accents.")
    printed_text: list[str] = Field(default_factory=list, description="Every word or phrase visible on the garment, exactly as written.")
    graphics: list[str] = Field(default_factory=list, description="Logos or images, e.g. 'bulldog', 'Yale shield', 'crossed oars'.")
    graphic_placement: Literal["left-chest", "full-front", "sleeve", "back", "multiple", "none"]
    print_style: str = Field(description="How the design is applied, e.g. 'screen print', 'embroidered', 'felt appliqué', 'distressed vintage'.")
    affiliation: str | None = Field(None, description="Specific Yale college, school, or group named, e.g. 'Saybrook College', 'School of Management'.")
    sport: str | None = Field(None, description="Sport referenced, if any.")
    family_role: str | None = Field(None, description="Family word printed, e.g. 'Dad', 'Grandma', if any.")
    brand: str | None = Field(None, description="Maker brand if visible or obvious, e.g. 'Champion', 'Under Armour'.")
    has_hood: bool
    has_zipper: bool
    sleeve_length: Literal["short", "long", "none"]
    style_keywords: list[str] = Field(default_factory=list, description="3-6 tags like 'vintage', 'athletic', 'minimal', 'bold'.")


class CatalogueEntry(ProductAttributes):
    """One catalogue row: model-extracted attributes plus file metadata."""

    product_id: str = Field(description="Filename stem, used as the stable ID.")
    image_path: str = Field(description="Path to the photo, relative to HW3/.")
    search_text: str = Field(description="All text fields joined, for embedding or keyword matching.")
    source: Literal["model", "manual"] = Field("model", description="'manual' = written by hand because the API refused the image.")

    @classmethod
    def from_attributes(cls, attrs: ProductAttributes, product_id: str, image_path: str,
                        source: Literal["model", "manual"] = "model") -> CatalogueEntry:
        parts = [
            attrs.title, attrs.description, attrs.garment_type, attrs.primary_color,
            *attrs.secondary_colors, *attrs.printed_text, *attrs.graphics,
            attrs.graphic_placement, attrs.print_style, attrs.affiliation or "",
            attrs.sport or "", attrs.family_role or "", attrs.brand or "", *attrs.style_keywords,
        ]
        return cls(
            **attrs.model_dump(),
            product_id=product_id,
            image_path=image_path,
            source=source,
            search_text=" | ".join(p for p in parts if p),
        )


class Catalogue(BaseModel):
    model: str
    entries: list[CatalogueEntry]


# --- Campus Customs agent: product identification -------------------------------------


class GarmentObservation(BaseModel):
    """One upper-body garment seen in a query photo, described in catalogue terms."""

    description: str = Field(description="1-2 sentences: garment, colors, graphics, text and where it sits.")
    garment_type: GarmentType
    primary_color: str
    secondary_colors: list[str] = Field(default_factory=list)
    printed_text: list[str] = Field(default_factory=list, description="Readable text on the garment, exactly as seen.")
    graphics: list[str] = Field(default_factory=list)
    graphic_placement: Literal["left-chest", "full-front", "sleeve", "back", "multiple", "none"]
    brand: str | None = None
    has_hood: bool
    has_zipper: bool
    sleeve_length: Literal["short", "long", "none"]
    visibility: Literal["clear", "partial", "poor"] = Field(description="How well the design can be seen.")


class QueryPhotoAnalysis(BaseModel):
    """Stage 1 output: what is worn in the query photo."""

    scene_summary: str
    garments: list[GarmentObservation] = Field(default_factory=list, description="Visible tops/outerwear, most prominent first.")


class CandidateProduct(BaseModel):
    """A catalogue product shortlisted by local retrieval (stage 2)."""

    product_id: str
    title: str
    retrieval_score: float


class MatchVerdict(BaseModel):
    """Stage 3 output from the vision model comparing the photo with the shortlist."""

    product_present: bool = Field(description="True if any garment in the photo is one of the candidate products.")
    product_id: str | None = Field(None, description="Candidate ID of the match; null if absent or if it can't be told apart.")
    confidence: float = Field(ge=0, le=1, description="Probability the verdict is correct.")
    alternatives: list[str] = Field(default_factory=list, description="Other candidate IDs that are also plausible.")
    evidence: list[str] = Field(default_factory=list, description="Concrete visual cues: text, graphics, color, cut.")
    reasoning: str


class ProductIdentification(BaseModel):
    """Final answer for 'does a Campus Customs product appear in this image, and which one?'."""

    image_path: str
    product_present: bool
    product_id: str | None = Field(None, description="Catalogue ID of the identified product, if we can tell which one.")
    product_title: str | None = None
    confidence: float = Field(ge=0, le=1)
    alternatives: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    reasoning: str
    candidates_checked: list[CandidateProduct] = Field(default_factory=list, description="Shortlist shown to the vision model (max 10).")
    error: str | None = Field(None, description="Set if the photo couldn't be analysed (e.g. the API refused it); the verdict is then unknown.")


# --- Campus Customs agent: ad video + customer profile ----------------------------------


class Budget(BaseModel):
    typical_min_usd: int = Field(ge=0)
    typical_max_usd: int = Field(ge=0)
    price_sensitivity: Literal["low", "medium", "high"]
    notes: str | None = Field(None, description="e.g. 'waits for sales', 'will splurge on gifts'.")


class MediaHabits(BaseModel):
    platforms: list[str] = Field(description="Where they'd actually see an ad, most-used first.")
    content_formats: list[str] = Field(description="e.g. 'short vertical video', 'email newsletter'.")
    attention_span: Literal["seconds", "under a minute", "a few minutes"] = Field(
        description="How long an ad has before they scroll past.")
    watches_with_sound: bool = Field(description="False if they usually watch muted (captions matter).")


class CustomerProfile(BaseModel):
    """Everything about a customer that decides whether a Campus Customs ad resonates.

    Shape used for profiles/*.json. Unknown keys are rejected, so typos in a profile file fail loudly.
    """

    model_config = ConfigDict(extra="forbid")

    # Who they are
    name: str
    customer_type: Literal["student", "parent", "alumni", "staff", "visitor"]
    pronouns: str | None = Field(None, description="So the judge never has to guess.")
    age: int | None = Field(None, ge=0)
    hometown: str | None = None
    yale_connection: str = Field(description="Their specific tie to Yale: school, college, class year, or child's.")
    life_stage: str = Field(description="e.g. 'sophomore, first year living off the meal plan', 'parent of a first-year'.")

    # What they'd buy
    preferred_garments: list[GarmentType] = Field(default_factory=list, description="Catalogue garment types they wear.")
    style_preferences: list[str] = Field(default_factory=list)
    color_preferences: list[str] = Field(default_factory=list)
    already_owns: list[str] = Field(default_factory=list, description="Yale merch they have, so ads for more of it matter less.")
    wishlist: list[str] = Field(default_factory=list, description="Specific things they want and haven't found.")
    purchase_occasions: list[str] = Field(default_factory=list, description="Moments that trigger a purchase: The Game, gifts, move-in.")
    budget: Budget

    # How they shop and what persuades them
    shopping_channels: list[str] = Field(default_factory=list, description="e.g. 'phone, online', 'in person on campus visits'.")
    decision_factors: list[str] = Field(default_factory=list, description="What decides a purchase, most important first.")
    media_habits: MediaHabits

    # What resonates emotionally
    interests: list[str] = Field(default_factory=list)
    cultural_references: list[str] = Field(default_factory=list, description="Music, shows, trends they'd recognise in an ad.")
    values: list[str] = Field(default_factory=list)
    tone_that_works: list[str] = Field(default_factory=list, description="Ad tones that land with them.")
    turn_offs: list[str] = Field(default_factory=list, description="Things that make them scroll past or distrust an ad.")
    notes: str | None = None


class VideoFrame(BaseModel):
    index: int
    timestamp_s: float
    path: str = Field(description="Saved JPEG, relative to HW3/.")


class VideoFrames(BaseModel):
    """Local, deterministic sampling of a video (no AI call)."""

    video_path: str
    duration_s: float
    width: int
    height: int
    has_audio: bool
    frames: list[VideoFrame]


class AudioFeatures(BaseModel):
    """Local signal measurements of the soundtrack (ffmpeg + numpy, no AI call).

    The model endpoint can't take audio, so this is what the judge knows about the sound.
    """

    has_audio: bool
    mean_loudness_dbfs: float | None = None
    peak_loudness_dbfs: float | None = None
    silence_ratio: float | None = Field(None, description="Share of 50 ms windows quieter than -45 dBFS.")
    tempo_bpm: float | None = Field(None, description="Estimated beat tempo; may be half or double the true tempo.")
    tempo_strength: float | None = Field(None, description="0-1: how regular the beat is (low = speech, ambience or no steady beat).")
    bass_energy_ratio: float | None = Field(None, description="Share of spectral energy below 150 Hz.")
    summary: str = Field(description="Plain-language reading of the numbers, including what they can't tell us.")


class AdScene(BaseModel):
    timestamp_s: float
    description: str


class AdVideoAnalysis(BaseModel):
    """What the ad shows and says, from sampled frames (one vision call, max 10 frames)."""

    summary: str = Field(description="2-3 sentences: what happens in the ad.")
    hook: str = Field(description="What grabs attention in the first 1-2 seconds.")
    scenes: list[AdScene]
    on_screen_text: list[str] = Field(default_factory=list, description="Captions, titles, logos, URLs, exactly as shown.")
    tone: list[str] = Field(description="e.g. 'confident', 'humorous', 'gritty', 'aspirational'.")
    pacing: str
    cultural_references: list[str] = Field(default_factory=list, description="Songs, music videos, memes or trends it references.")
    people_and_setting: str
    merchandise_shown: list[str] = Field(default_factory=list, description="Apparel visible, described in catalogue terms.")
    brand_visibility: str = Field(description="Is Campus Customs (the store) named, shown, or linked? Or only Yale?")
    call_to_action: str | None = Field(None, description="Explicit ask (shop now, URL, discount); null if none.")
    production_quality: str
    best_product_frame_indices: list[int] = Field(default_factory=list, description="Up to 3 frame indices where apparel is clearest.")


class ProductsInVideo(BaseModel):
    """Catalogue products found by running identify_product on key frames."""

    video_path: str
    sightings: list[ProductIdentification]
    product_ids: list[str] = Field(description="Catalogue IDs identified across the checked frames, lookalikes merged.")
    possible_alternatives: list[str] = Field(
        default_factory=list,
        description="IDs some frame picked but that another sighting lists as a lookalike: probably the same garment.")


DimensionName = Literal[
    "attention", "profile_relevance", "product_appeal", "brand_clarity", "persuasion", "tone_fit",
]


class ScoreDimension(BaseModel):
    name: DimensionName
    score: int = Field(ge=1, le=10)
    rationale: str = Field(description="One or two sentences tied to specific frames and profile traits.")


class KeyMoment(BaseModel):
    timestamp_s: float
    note: str = Field(description="Why this moment helps or hurts with this customer.")


class AdJudgement(BaseModel):
    """The judge model's raw assessment; code turns it into AdEffectiveness."""

    dimensions: list[ScoreDimension] = Field(description="Exactly one entry for each of the six dimensions.")
    purchase_likelihood: float = Field(ge=0, le=1, description="Probability this customer shops at Campus Customs after seeing the ad.")
    resonates_with: list[str] = Field(description="Profile traits the ad connects with, and how.")
    falls_flat_on: list[str] = Field(description="Profile traits or needs the ad misses or works against.")
    key_moments: list[KeyMoment] = Field(default_factory=list)
    recommendations: list[str] = Field(description="Concrete changes that would make this ad work better for this customer.")
    reasoning: str
    confidence: float = Field(ge=0, le=1, description="How sure the judge is in its own assessment.")


class AdEffectiveness(BaseModel):
    """Final answer for 'how well would this video convince this customer to shop at Campus Customs?'."""

    video_path: str
    profile_path: str
    customer_name: str
    overall_score: int = Field(ge=0, le=100, description="Mean of the six (median-across-runs) dimension scores, scaled to 100; computed in code.")
    verdict: Literal["very effective", "effective", "mixed", "ineffective"]
    purchase_likelihood: float = Field(ge=0, le=1)
    dimensions: list[ScoreDimension]
    products_featured: list[str] = Field(default_factory=list, description="Catalogue IDs identified in the ad.")
    possible_products: list[str] = Field(default_factory=list, description="Lookalike IDs that may be the same garment as one above.")
    audio: AudioFeatures | None = Field(None, description="Measured soundtrack features the judge was given.")
    judge_runs: int = Field(1, description="Independent judge samples combined into this result.")
    overall_score_range: list[int] = Field(default_factory=list, description="[min, max] overall score across judge runs.")
    resonates_with: list[str]
    falls_flat_on: list[str]
    key_moments: list[KeyMoment] = Field(default_factory=list)
    recommendations: list[str]
    reasoning: str
    confidence: float = Field(ge=0, le=1)
    limitations: list[str] = Field(default_factory=list, description="What the judgement could not consider, e.g. audio.")


# --- Campus Customs agent: audit trail ---------------------------------------------------


class AuditToolCall(BaseModel):
    tool_name: str
    tool_call_id: str | None = None
    args: dict | str | None = Field(None, description="Arguments as sent (paths, not image data).")


class AuditToolResult(BaseModel):
    tool_name: str
    tool_call_id: str | None = None
    ok: bool
    summary: str = Field(description="Short, human-readable result (key fields only, truncated).")


class AuditEntry(BaseModel):
    """One step of one agent run, appended to output/audit_trail.json as the agent runs.

    Records what the agent visibly did and why it stopped. Hidden model reasoning is never stored.
    """

    timestamp: str = Field(description="UTC time the step finished, ISO 8601.")
    run_id: str = Field(description="Groups all steps of one agent run.")
    step: int = Field(description="0-based position of this step within the run.")
    kind: Literal["request", "model_response", "tool_results", "final_output", "error"]
    action_summary: str = Field(description="What happened in this step, in one plain sentence (no hidden reasoning).")
    user_request: str | None = Field(None, description="The request that started the run (first step only).")
    model_text: str | None = Field(None, description="Any visible text the model wrote, truncated.")
    tool_calls: list[AuditToolCall] = Field(default_factory=list)
    tool_results: list[AuditToolResult] = Field(default_factory=list)
    stop_reason: str | None = Field(None, description="Model finish reason (e.g. 'tool_call', 'stop') or how the run ended.")
    model_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_s: float | None = Field(None, description="Seconds since the run started.")
