# Campus Customs Agent: Harness

This document has two parts:
- **Part A** explains the whole system for a manager: what it does, its tools, data types, safety rules and limits.
- **Part B** is the build log. It records how each piece was built, problem by problem, with measurements and design decisions.

---

# Part A: System overview

## What the system does

Campus Customs sells Yale apparel. The agent answers two business questions from media:

1. **"Is one of our products in this photo, and which one?"** (product identification)
2. **"How well would this ad video convince *this* customer to shop with us?"** (ad effectiveness for a customer profile)

It's a single **PydanticAI agent** (`agents.py`) on **`gpt-5.6-luna`** (OpenAI via Portkey). It reads one system prompt (`prompts/prompt.md`), calls tools from `tools.py`, and always returns a **validated, structured result** (types in `models.py`) instead of free text. Every run is logged step by step to `output/audit_trail.json`.

```
photo / video + profile
        │
        ▼
  PydanticAI agent  ── system prompt: prompts/prompt.md (safety rules + abilities)
        │  calls tools (tools.py), capped at 10 model requests / 12 tool calls per run
        ▼
  structured result (models.py) ──► output/*.json
        │
        └──► every step appended to output/audit_trail.json
```

## How to run it

| Command | Output |
|---|---|
| `python build_catalogue.py` | `catalogue.json`: one entry per product photo (run once, or when products change) |
| `python agent.py --image "data/test_images/image_03_true.jpeg"` | `output/identify_product_single.json` |
| `python agent.py --eval` | `output/identify_product.json`: all 4 test images, scored against their filenames |
| `python agent.py --video "data/videos/ad_humble.mp4" --profile "profiles/profile_student.json"` | Adds or replaces that pair in `output/ad_effectiveness.json` |
| `python build_profiles.py` | `profiles/profile_student.json`, `profiles/profile_parent.json` |

`agent.py` is an alias for `agents.py`. All runs append to `output/audit_trail.json`.

## Abilities

| Ability | Input | Output type | Headline result on our data |
|---|---|---|---|
| **1. Identify a product in an image** | image path | `ProductIdentification` | **4/4** test images correct, including telling apart two near-identical navy "YALE BULLDOGS" long-sleeves |
| **2. Judge an ad for a customer** | video path + profile JSON | `AdEffectiveness` | `ad_humble.mp4`: **student 57/100 (mixed)**, **parent 40/100 (ineffective)**. Both fail on brand clarity and call to action. |
| Supporting: catalogue builder | `data/products/*.jpg` | `Catalogue` | 102 products (99 by AI, 3 written by hand after the content filter refused them) |
| Supporting: safety + audit | every run | `AuditEntry` | Every agent step logged, append-only |

## Tools the agent uses

All tool logic lives in `tools.py`. `agents.py` registers each tool with a docstring the model reads.

| Tool | Ability | What it does | AI calls |
|---|---|---|---|
| `identify_product` | 1 | Describes the garments in the photo, shortlists the 10 closest catalogue products locally, then checks them visually against the photo in one call. | 2 |
| `load_customer_profile` | 2 | Reads a profile JSON and validates it into a `CustomerProfile`. | 0 |
| `sample_video_frames` | 2 | Pulls 10 evenly spaced frames with ffmpeg, plus duration, resolution and audio presence. | 0 |
| `analyze_audio_track` | 2 | Measures the soundtrack locally (loudness, silence, tempo, bass). It can't hear lyrics. | 0 |
| `analyze_ad_video` | 2 | One vision call over the frames + audio measurements + filename: hook, scenes, text, tone, references, branding, call to action. | 1 |
| `find_products_in_video` | 2 | Runs `identify_product` on the 3 clearest frames at the same time, and merges lookalikes into one product. | 6 (3 frames × 2) |
| `judge_ad_for_customer` | 2 | Three judges score the ad on 6 dimensions for this customer, with the median taken for each. **An output function:** its result *is* the agent's answer. | 3 |

Internal helpers (not agent tools): `describe_photo`, `shortlist` (BM25 + attribute scoring), `verify_shortlist`, `merge_lookalikes`, `load_catalogue`, `load_image`.

**Typical cost per request:**
- **Image:** 2 vision calls + 2 agent calls.
- **Ad:** about 10 vision/judge calls + 4 agent calls. Frames, audio, analysis and products are computed once per video and reused.

## Data types (`models.py`)

Every AI output is a Pydantic model, so results are validated and always have the same shape. One rule throughout: **the model fills in what it observes or judges, and code fills in IDs, paths, scores, verdicts and limitations**, so those can never be made up. The field-by-field reasoning is in Part B.

| Type | Used for | Why its fields |
|---|---|---|
| `ProductAttributes` | What the vision model extracts from one product photo | Garment type, colors, exact printed text, graphics, placement, affiliation, sport, family word, hood/zip/sleeves: the cues that tell similar Yale items apart in a photo |
| `CatalogueEntry` | One catalogue row = attributes + `product_id`, `image_path`, `search_text`, `source` | Stable ID and path are set by code; `search_text` is ready for keyword search; `source` marks the 3 hand-written entries |
| `Catalogue` | The whole `catalogue.json` | Model name + entries |
| `GarmentObservation`, `QueryPhotoAnalysis` | Step 1 of identification: what's worn in the query photo | **Same vocabulary as the catalogue**, so the local shortlist can compare like with like |
| `CandidateProduct` | One shortlisted product (ID, title, score) | Shows which 10 products the checker saw |
| `MatchVerdict` | The checker model's raw answer | Kept separate so the model can't set fields code controls |
| **`ProductIdentification`** | **Ability 1 result** | `product_present` separate from `product_id` (it can be "yes, but can't tell which"); `confidence`; `alternatives`; `evidence`; `candidates_checked`; `error` so a refusal is "no verdict", not a false "no" |
| `CustomerProfile` (+ `Budget`, `MediaHabits`) | A customer persona in `profiles/*.json` | Who they are, what they'd buy, how they shop, what resonates. Each group feeds a scoring dimension. Unknown keys are rejected. |
| `VideoFrame`, `VideoFrames` | Sampled frames and video metadata | Timestamps let every judgement point to a moment |
| `AudioFeatures` | Measured soundtrack | The only audio signal available; includes a plain summary of what it *can't* tell us |
| `AdScene`, `AdVideoAnalysis` | What the ad shows | Hook, scenes, on-screen text, tone, references, branding, call to action: what an ad needs to succeed |
| `ProductsInVideo` | Catalogue products in the ad | Reuses `ProductIdentification` for each frame; `possible_alternatives` holds merged lookalikes |
| `ScoreDimension`, `KeyMoment`, `AdJudgement` | One judge's raw scoring | Six fixed dimensions (attention, profile_relevance, product_appeal, brand_clarity, persuasion, tone_fit), each 1–10 with a rationale |
| **`AdEffectiveness`** | **Ability 2 result** | `overall_score` and `verdict` **computed in code**; `purchase_likelihood` separate from the score; what resonates / falls flat; recommendations; `judge_runs` + `overall_score_range` show stability; `limitations` written by code |
| `AuditEntry` (+ `AuditToolCall`, `AuditToolResult`) | One step of one run in the audit trail | Time, run/step, a visible action summary, tool args + short result, stop reason, tokens. **No hidden reasoning, no image data.** |

## Safety rules (summary)

The full text is at the top of `prompts/prompt.md`. It's loaded by the main agent **and** added to every vision sub-agent (describe, verify, video analysis, judge), so it governs every call that sees an image.

- **Must:** look only at clothing, products, on-screen text, setting and ad content; describe people by role or clothing; treat photos and profiles as confidential, referring to them by path only; report refusals and unclear images instead of guessing; mark inferences as inferred.
- **Must not:**
  - identify or guess who anyone is, celebrities and influencers included
  - infer or comment on sensitive traits or bodies
  - claim someone endorsed Campus Customs
  - track or profile people across images
  - edit or re-encode an image to get around a content filter (refusals are reported, never worked around)
  - add personal details about people who may be minors
- **Enforced in code as well:**
  - product IDs the model returns are checked against the shortlist
  - the judge refers to customers by name or stated pronouns
  - the audit stores paths, not images, and never the model's hidden reasoning

## Specs and limits

| Limit | Value | Where | Why it matters |
|---|---|---|---|
| Model | `gpt-5.6-luna` via Portkey | `tools.py` | The course-required model; text + image input only (no audio, no embeddings) |
| **Max model requests per agent run** | **10** | `agents.py` `RUN_LIMITS` | Stops loops. Normal runs need 2 (image) or 4 (ad). |
| **Max tool calls per agent run** | **12** | `agents.py` `RUN_LIMITS` | Normal runs need 1–5 |
| API request timeout / retries | 120 s / 2 retries | `tools.get_model` | A stuck request fails instead of hanging (it once hung for about 7.5 minutes) |
| **Product images per vision call** | **≤ 10** | `MAX_CANDIDATES` | Keeps identification cheap no matter how big the catalogue is |
| Catalogue shortlist | top 10 by local BM25 + attribute score | `shortlist()` | No per-product AI calls |
| **Frames sampled per video** | **10**, evenly spaced (segment midpoints), 960 px wide | `MAX_VIDEO_FRAMES` | Enough to cover a short ad while staying within the 10-image limit |
| Frames checked for products | 3 (the clearest, picked by the analysis) | `MAX_PRODUCT_FRAMES` | 6 vision calls; background-crowd items can be missed |
| Audio | measured locally at 22.05 kHz mono; tempo searched in 60–180 BPM | `analyze_audio_track` | Free, but it can't recognise lyrics or the song |
| Judge runs per ad | 3, median per dimension | `JUDGE_RUNS` | Reduces score variation between runs (it was 60 vs 57 before) |
| Verdict thresholds | ≥80 very effective, ≥65 effective, ≥45 mixed, else ineffective | `_verdict()` | Same score always gives the same label |
| Catalogue build | 16 images in parallel, 3 retries with backoff, cached/resumable | `build_catalogue.py` | 99 images in about 25 s; reruns only process new ones |
| Audit truncation | args ≤ 600 chars, result summaries ≤ 240 chars | `agents.py` | Keeps the audit readable and free of large payloads |

## Known limitations (whole system)

- **No audio understanding.** Only loudness, tempo and bass are measured. Song references are inferred, partly from the filename.
- **Confidence scores run high** (0.94–0.99) on almost everything, so they don't separate easy cases from hard ones yet.
- **Identification retypes its answer.** The final step takes about 2,000 tokens and 146 s in the audited run. Ability 2 already avoids this with an output function; ability 1 should get the same fix.
- **The ad overall score is a plain average of the six dimensions.** A good-looking ad with no call to action still scores "mixed". The evaluation suggests capping the score when brand clarity or persuasion is very low.
- **Portkey caching** replays identical requests, so reruns aren't new samples unless the prompt changes.
- **The content filter is inconsistent.** It refuses 3 catalogue photos and occasionally a whole request. Refusals are reported, not worked around.
- **Small test set:** 4 test images and 1 ad. The results show the pipeline works; they don't prove it's accurate at scale.

For the full evaluation see `output/agent_evaluation.md`.

---

# Part B: Build log (problem by problem)

The sections below were written as each piece was built. They keep the measurements and design decisions from the time. Where a later problem changed something (e.g. `ad_effectiveness.json` becoming a list), the section notes it.

Problems 4 and 7 were evaluations, not builds. Their write-ups are in `output/agent_evaluation.md` (Part 1: the 4 test images; Part 2: the ad runs for both profiles).

## Problem 2: Build the product catalogue

`build_catalogue.py` sends each photo in `data/products/` to `gpt-5.6-luna` (through Portkey) using a PydanticAI `Agent`. It has `output_type=ProductAttributes`, so every reply comes back as a validated Pydantic object instead of free text. The results are written to `catalogue.json`.

### How we sped it up

1. **Concurrent async calls instead of a sequential loop.** Almost all of the time goes to waiting on the network while the model reads an image, not to local work. So the script starts one `asyncio` task per image and lets them wait at the same time. An `asyncio.Semaphore` limits how many requests are in flight at once (default 16, set with `--concurrency`), which keeps us from getting rate-limited.
2. **Results are handled as they finish.** `asyncio.as_completed` processes each result as soon as it arrives, so one slow image doesn't hold up the progress output or the checkpoints.
3. **Caching / resume.** Before it starts, the script loads `catalogue.json` and skips any product that's already in it. A rerun only processes new or failed images. Rerunning with all 99 cached finished in about 1 second. `--force` rebuilds everything.
4. **Checkpointing.** The catalogue is saved every 10 finished images. If the run crashes, finished work is kept and picked up on the next run.
5. **Smart retries.** Temporary errors like rate limits and timeouts get up to 3 attempts with exponential backoff (2s, 4s). Content-filter rejections are not retried, because the same image gets the same answer every time. Retrying just wasted about 6 seconds per blocked image.
6. **Structured output in one call.** Each image needs one model call, which returns every field at once. There's no separate call for "describe" and another for "extract".

**Measured:** same 20 images, cache off:

| Mode | Time |
|---|---|
| Sequential (`--concurrency 1`) | 9.2 s |
| Parallel (`--concurrency 16`) | 4.2 s |

That's about 2.2x faster on 20 images. The gap grows with more images, because the sequential time keeps growing with the number of images while the parallel version runs up to 16 at once. The full first run did 99 images in 24.9 s. That time includes the wasted retries on the blocked images, which were fixed afterwards.

### Fields in `models.py` and why

The model is split into two classes:

- `ProductAttributes`: what the vision model fills in
- `CatalogueEntry`: extends it with fields our code adds

That split keeps the model from making up IDs or file paths.

| Field | Why it's useful for matching |
|---|---|
| `title` | Human-readable name for results and reports. |
| `description` | Full visual summary. The best single field to embed or compare against a description of a test photo or video frame. |
| `garment_type` (fixed list) | The strongest first filter. A hoodie in a video can't match a t-shirt. A fixed list (`Literal`) stops variants like "sweatshirt" vs "crewneck" from splitting the same category. |
| `primary_color`, `secondary_colors` | Color is visible even in blurry, far-away video frames, where text isn't readable. |
| `printed_text` | The most specific signal. "SAYBROOK", "DAD" or "BOOLA BOOLA" tells apart items that otherwise look identical. Recorded exactly as written. |
| `graphics` | Logos and images (bulldog, shield, crest) that identify a product when the text is cut off or out of focus. |
| `graphic_placement` | Tells apart items that share a design, e.g. a small **left-chest** "Yale Baseball" vs a **full-front** baseball graphic. |
| `print_style` | Embroidered vs screen-print vs felt vs distressed vintage looks different up close. Useful for breaking ties. |
| `affiliation` | Residential college or professional school (Saybrook, SOM, Law...). Many products differ only by this. |
| `sport` | Many products are one design repeated per sport (tennis, golf, hockey hoodies). |
| `family_role` | Separates the Dad / Mom / Grandpa / Uncle / Aunt line, which is otherwise one design. |
| `brand` | Champion, Under Armour, Brooks Brothers, etc. The logo is sometimes visible and helps narrow the options. |
| `has_hood`, `has_zipper`, `sleeve_length` | Simple yes/no or short-list structural features that are easy to check in video frames, even with low detail. They also double-check `garment_type`. |
| `style_keywords` | Loose tags ("vintage", "athletic", "minimal") for fuzzy or semantic search. |
| `product_id` | Filename stem. A stable key for linking matches back to a product. |
| `image_path` | So a later step can load the reference photo to compare side by side. |
| `search_text` | Every text field joined into one string. Ready to embed or keyword-search in the matching step, without rebuilding it each time. |

The instructions tell the model to describe only what's visible, record text exactly, and trust the image over the filename. The filename is passed as a hint because it often contains the product name.

### Known issue: 3 images blocked by the content filter

`benjamin-franklin-t-shirt`, `berkeley-sweater-fleece-jacket` and `timothy-dwight-college-crewneck` are rejected by the Azure OpenAI content-safety filter (`content_policy_violation`). All three are ordinary grey garments with college crests, so these look like false positives. Tests showed the trigger is the image itself, not the filename. The script logs these three as failed rather than silently dropping them.

To complete the catalogue, these three entries were **written by hand** from the photos in `add_manual_entries.py`. They're validated against the same `ProductAttributes` model and marked with `source: "manual"` in `catalogue.json`, so anyone can tell them apart from the 99 `source: "model"` entries. The catalogue now has **all 102** products. `build_catalogue.py` sees the manual entries as cached, so it won't send those images to the API again.

| Field | Why |
|---|---|
| `source` | `"model"` or `"manual"`. Records where each entry came from, for transparency. |

## Problem 3: Product identification agent

### Files

| File | Role |
|---|---|
| `prompts/prompt.md` | System prompt, loaded into the agent at startup. Later abilities will be added here. |
| `agents.py` | PydanticAI entry point. Builds the `Agent`, registers the `identify_product` tool, and handles the CLI. Since Problem 5, `output_type` also includes the ad-judge output function, and `agent.py` is an alias for it. |
| `tools.py` | The tool logic and helpers: loading the model and catalogue, the three pipeline stages, and the BM25 index. |
| `models.py` | Every structured type. The new ones are `GarmentObservation`, `QueryPhotoAnalysis`, `CandidateProduct`, `MatchVerdict` and `ProductIdentification`. |

Run it with:

```bash
python agents.py --image "data/test_images/image_03_true.jpeg"
```

This prints the verdict and saves the structured output to `output/identify_product_single.json`. `python agents.py --eval` runs all four test images, checks each one against the `_true` / `_false` in its filename, and saves all four results as a list to `output/identify_product.json` (Problem 4).

### How identification works

The agent reads the image path from the request and calls the `identify_product` tool. The tool runs three stages:

1. **Describe the photo (1 vision call).** The query photo alone goes to `gpt-5.6-luna`, which returns a `QueryPhotoAnalysis`: one `GarmentObservation` per top the person is wearing. It uses the **same vocabulary as the catalogue** (garment type, colors, printed text, graphics, placement, brand, hood/zip/sleeves). That's what makes the next step possible.
2. **Shortlist locally (0 API calls, milliseconds).** Each observation is scored against all 102 `catalogue.json` entries. The score adds up:
   - BM25 keyword relevance on the full `search_text`
   - a **2x-weighted** BM25 score on printed text and graphics only (the most telling signal)
   - bonuses when the garment type matches (+3, or +1 for the same family) and when the color family matches (+1.5)
   - penalties when hood (-2), zipper (-2) or sleeve length (-1) disagree

   The top **10** products become the shortlist.
3. **Verify visually (1 vision call).** A single call gets the query photo plus the shortlisted product photos, each labeled with its ID, title and printed text. It returns a `MatchVerdict`: is a product present, which one, confidence, lookalike alternatives, and evidence. The code then **checks the ID against the shortlist**. An ID we didn't offer is thrown out, so the model can't make up products. The code then builds the final `ProductIdentification`.

A photo with no tops returns "not present" right after stage 1, with no shortlist or second call.

### What we did to make it efficient

- **We never compare the photo against the catalogue one product at a time.** A naive approach would need 102 image-vs-image calls per query. We use **2 vision calls per photo, whatever the catalogue size.** The search step that grows with the catalogue runs locally in milliseconds.
- **Never more than 10 product images per call.** This is enforced in code: `MAX_CANDIDATES = 10`, `shortlist()` caps at it, and `verify_shortlist` asserts it.
- **Local BM25 instead of embeddings.** Portkey here only serves `gpt-5.6-luna` (an embeddings request returned `OperationNotSupported`). A small BM25 index needs no API, costs nothing, and is deterministic. The catalogue fields from Problem 2 are reused directly: `search_text` for keywords, and `garment_type` / `has_hood` / `has_zipper` / `sleeve_length` / `primary_color` as cheap structural filters.
- **Built once, reused.** The model client, catalogue, BM25 indexes and sub-agents are cached with `lru_cache`, so they're built once per process.
- **Concurrent test runs.** `--eval` runs all test images at the same time with `asyncio.gather`: **4/4 correct in 29.5 s** for all four together. A single `--image` run took about 37 s, most of it waiting on the model.
- **The 3 manual catalogue entries** (whose photos the API refuses) are sent as their written description instead of the photo. One blocked product image can't take down the whole comparison call.

### Results on the test images

| Image | Expected | Agent answer |
|---|---|---|
| `image_01_true` (grey "YALE UNIVERSITY DAD" tee) | present | `yale-dad-t-shirt`, 0.99 |
| `image_02_false` ("ESSENTIALS" hoodie) | not present | not present, 0.99 |
| `image_03_true` (navy "YALE BULLDOGS" long-sleeve) | present | `dry-zone-long-sleeve`, 0.98. Correctly ruled out the similar Under Armour `ua-mens-tech-l-s-2-0` (no UA logo, no arched outline lettering) |
| `image_04_false` ("Balenciaga" tee) | not present | not present, 0.99 |

The saved single-image example is `output/identify_product_single.json` (image 03). `output/identify_product.json` holds all four results from Problem 4.

### Fields in the identity model (`ProductIdentification`) and why

| Field | Why |
|---|---|
| `image_path` | Records which photo the verdict is for, so saved results and batch runs make sense on their own. |
| `product_present` | The core yes/no question: is *any* Campus Customs product in the photo? Kept separate from `product_id` because "yes, but can't tell which" is a valid answer. |
| `product_id` | Which catalogue product, as a stable ID that links back to `catalogue.json`. `null` when absent **or** when lookalikes can't be told apart. Checked against the shortlist so it's never made up. |
| `product_title` | Human-readable name, filled in from the catalogue by code (not the model), so it always matches the ID. |
| `confidence` | A probability from 0 to 1, so later steps can set a threshold (e.g. only act above 0.8). The prompt tells the model not to default to 0.5. |
| `alternatives` | Other plausible catalogue IDs, e.g. the Dad tee vs the Dad crewneck. Makes uncertainty visible instead of hiding it in one answer. Also filtered to the shortlist. |
| `evidence` | The specific visual cues behind the verdict (text read, graphic, color, cut). Makes the answer checkable and easy to debug. |
| `reasoning` | A short explanation in plain words, for the person reading the output. |
| `candidates_checked` | The shortlist of up to 10 (`CandidateProduct`: ID, title, retrieval score) the verifier saw. Shows the 10-image limit was respected, and helps tell a retrieval miss (right product not shortlisted) from a verification miss. |
| `error` | Set when the API refuses or fails on a request (e.g. an inconsistent `content_policy_violation`). The result then clearly says "no verdict" instead of a fake "not present". |

Supporting types: `GarmentObservation` / `QueryPhotoAnalysis` (stage 1) mirror the catalogue fields so the shortlist can compare like with like, and `visibility` records how readable the design was. `MatchVerdict` (stage 3) is the model's raw answer. It's kept separate from `ProductIdentification` so that fields our code controls (`image_path`, `product_title`, `candidates_checked`, `error`) are never generated by the model.

### Known limitations

- **Stage 1 misreads hurt retrieval.** On one run, the partly hidden "Y_LE BULLDOGS" on image 03 was read as "LIFE BUSINESS". Structure and color still put the right product at #1, and stage 3 sees the actual images, so it recovered.
- **The content filter is inconsistent.** The first `--eval` run had the comparison call rejected, and later identical runs passed. That's now reported through `error` instead of crashing the agent.
- **The final output goes through the agent.** The agent copies the tool result into its output, and the prompt tells it to keep the verdict unchanged.

## Problem 5: Ad video + customer profile ability

Run it with:

```bash
python agent.py --video "data/videos/ad_humble.mp4" --profile "profiles/profile_student.json"
```

This saves the structured result to `output/ad_effectiveness.json`. Since Problem 7, that file is a **list** with one `AdEffectiveness` per (video, profile) pair, so running the command for each profile adds to it instead of overwriting. `agent.py` is a two-line alias for `agents.py`, so `python agents.py ...` works the same way. The profile used is `profiles/profile_student.json`: Jordan Rivera, a Saybrook undergrad who likes hip-hop and streetwear, is on a tight budget, and dislikes ads that don't say where to buy.

### Tools we gave the agent for this job

| Tool | What it does |
|---|---|
| `load_customer_profile` | Reads the profile JSON and validates it into a `CustomerProfile`. |
| `sample_video_frames` | Uses ffmpeg locally (no AI) to pull 10 evenly spaced frames, plus duration, size and whether there's audio. |
| `analyze_audio_track` | Measures the soundtrack locally with ffmpeg and numpy: loudness, silence, tempo and bass. It can't hear lyrics. |
| `analyze_ad_video` | One vision call over ≤10 frames plus the audio measurements and filename: hook, scenes, text, tone, references, branding, call to action. |
| `find_products_in_video` | Runs the Problem 3 `identify_product` pipeline on the 3 clearest frames at once, then merges lookalikes into one product. |
| `judge_ad_for_customer` | Runs 3 judges at once to score the ad for *this* customer on 6 dimensions, using the median score for each. Its result is the agent's final answer. |

The agent calls them in the order the prompt asks for: profile and analysis in parallel, then products, then the judge. Runs take **22–49 s**, most of it the 3 judge calls and the analysis calls.

**Efficiency and reliability choices:**
- **Every video step runs once.** Frames, audio, analysis and product results are cached per video, so the judge reuses them instead of recomputing.
- **Frame extraction and audio measurement are free.** They run locally, in parallel, with no AI calls.
- **Every AI call stays within the same 10-image limit** as identification.
- **The judge is an output function.** `judge_ad_for_customer` is registered with PydanticAI's `ToolOutput`. In the first version, the agent had to retype the full `AdEffectiveness` JSON as its final answer, and that request **timed out 3 times in a row** (about 450 s) after the tools had finished in 7.5 s. Now the judge's result is returned as-is. This is the "make the tool's result the final answer" fix suggested in `agent_evaluation.md`.
- **Three judges, combined by median.** The judge runs 3 times at once, and each dimension uses the median score. The wording comes from the run closest to those medians, and `overall_score_range` shows the spread (57–57 in the saved run, 57–60 in the one before). Each run is labeled, so Portkey's cache can't replay one answer three times.
- **Requests have a time limit.** Every API request has a 120 s timeout and 2 retries, so a stuck request fails instead of hanging forever.

### Fields in the ad-effectiveness model (`AdEffectiveness`) and why

| Field | Why |
|---|---|
| `video_path`, `profile_path`, `customer_name` | Record which ad was judged for which person. The same ad gets different scores for different customers, so a score means nothing without them. |
| `overall_score` (0–100) | One headline number for ranking ads or customers. **Computed in code** as the mean of the 6 median dimension scores × 10, so it always matches the breakdown. The model can't give a 90 while the parts average 5. |
| `verdict` | A plain-words label (very effective / effective / mixed / ineffective), **derived from the score** with fixed thresholds (80 / 65 / 45), so it's consistent across runs. |
| `purchase_likelihood` (0–1) | The business question itself: will this person actually shop? Kept separate from the score because an ad can be great to watch and still not convert, which is exactly what happened here (score 57, likelihood 0.18). Median across judges. |
| `dimensions` (6 × `ScoreDimension`: name, 1–10 score, rationale) | Breaks "effective" into the steps an ad has to win: **attention** (stop scrolling), **profile_relevance** (is it about me?), **product_appeal** (do I want it?), **brand_clarity** (do I know it's Campus Customs and where to buy?), **persuasion** (reason and way to act now), **tone_fit** (matches values and dislikes). Each rationale must cite moments in the ad and profile traits. The names are a fixed list, and each dimension appears exactly once, in a fixed order. |
| `products_featured` | Catalogue IDs found in the ad, with lookalikes merged. Links the ad to real products we sell and checks whether the ad shows things this customer would buy. |
| `possible_products` | Lookalike IDs that some frame picked but that are probably the same garment as one above (here the Champion hoodie vs the basic YALE hoodie). The uncertainty stays visible instead of being counted as a second product. |
| `audio` (`AudioFeatures`) | The measured soundtrack the judges were given: loudness, silence, tempo, beat strength, bass share and a plain summary. Makes clear what the sound judgement is based on. |
| `judge_runs`, `overall_score_range` | How many judges were combined, and the lowest and highest overall scores among them. A narrow range (57–57 in the saved run) means the score is stable; a wide one means read it with caution. |
| `resonates_with` / `falls_flat_on` | Which profile traits the ad hits and misses. That's the "why" behind the score, in terms a marketer can act on. |
| `key_moments` (timestamp + note) | Pinpoints the seconds that help or hurt (e.g. the 8.6 s group shot), so editing suggestions point to specific moments. |
| `recommendations` | Concrete edits for *this* customer (e.g. an end card with the URL, a price, a Saybrook variant). The output is meant to improve the ad, not just grade it. |
| `reasoning` | A short summary a person can read without going through the table. |
| `confidence` (0–1) | How sure the judges are of their assessment (median). Separate from `purchase_likelihood`: a confident "unlikely to buy" is a useful answer. |
| `limitations` | Written by code, not the model. Records what the judgement couldn't consider: **10 frames rather than continuous video**, and a **soundtrack that was measured but not heard**. It also records any failed judge run, failed product check or missing dimension. |

Supporting types: `CustomerProfile` (expanded in Problem 6; see that section for its fields), `VideoFrame` / `VideoFrames`, `AudioFeatures`, `AdScene` / `AdVideoAnalysis`, `ProductsInVideo` (reuses `ProductIdentification` for each frame, plus `possible_alternatives`), `KeyMoment`, and `AdJudgement`. `AdJudgement` is each judge's raw output. It's kept separate from `AdEffectiveness` so the fields our code controls (score, verdict, products, audio, runs, limitations, paths) are never generated by the model.

### Result for `ad_humble.mp4` × Jordan (student)

**Mixed, 57/100 (3 judges: all 57), purchase likelihood 0.18.** Rerun with the Problem 6 student profile; an earlier run with the simpler profile scored 58 (57–60).

| Dimension | Score |
|---|---|
| attention | 8 |
| profile_relevance | 7 |
| product_appeal | 8 |
| brand_clarity | **2** |
| persuasion | **1** |
| tone_fit | 8 |

The ad is a strong fit for Jordan. It uses dark streetwear hoodies and group belonging, and it's a likely parody of Kendrick Lamar's "HUMBLE." for a hip-hop fan. But it **never names Campus Customs**, and has no price, URL or call to action for a phone shopper who waits for sales. The product shown is `basic-hoodie-big-yale`, with `champion-reverse-weave-hoodie-1` as a possible lookalike. The top recommendation is an end card: "Shop Campus Customs", a URL/QR code, and a price or sale.

### Fixes made after the first run

| Problem in first run | Fix |
|---|---|
| **No audio at all.** The endpoint can't take audio or transcribe (404), and the model only saw "hip-hop visual language" | `analyze_audio_track` measures the soundtrack locally: loud (−11 dBFS), 0% silent, heavy bass (86% of energy below 150 Hz), beat around 152 BPM. "HUMBLE." is about 76 BPM, and this kind of tempo estimate often doubles. The analysis now also treats the **filename** as a clue. Result: it identifies the **"HUMBLE."** reference, marked as *inferred, medium confidence*. |
| **The same hoodie counted as two products** (`champion-reverse-weave-hoodie-1` in 1 frame, `basic-hoodie-big-yale` in 2) | `merge_lookalikes`: when one sighting lists another sighted ID as a lookalike, they're treated as one garment. The ID with more confidence-weighted votes is kept, and the other moves to `possible_products`. Unrelated products (e.g. different people's clothes) are never merged. |
| **Scores varied from run to run** (60 vs 57) | 3 judges at once, with the median of each dimension. The spread is reported in `overall_score_range`. |
| The judge used "his" for Jordan, though the profile gives no pronouns | The judge is told to use the customer's name, or they/them, and to describe people in the ad by role. |

### Remaining limitations

- **The soundtrack is measured, not heard.** Lyrics, voiceover and the song itself can't be confirmed. The "HUMBLE." reference is inferred from the filename, the staging and the tempo.
- **The tempo can be off by half or double** (152 vs 76 BPM), and "beat strength" is weak (0.15) for music with heavy bass. The numbers support the story; they don't prove it.
- **Only 3 frames are checked for products**, so products worn only by people in the background crowd (other Yale crewnecks, a possible residential-college top) aren't identified.

## Problem 6: Student and parent profiles

The profile shape is `CustomerProfile` in `models.py`, with two small nested models: `Budget` and `MediaHabits`. `build_profiles.py` defines the two people as model instances and saves them. Building them in code means a wrong field name or value fails immediately, not halfway through an agent run.

```bash
python build_profiles.py   # writes profiles/profile_student.json and profiles/profile_parent.json
```

| File | Who |
|---|---|
| `profiles/profile_student.json` | **Jordan Rivera** (they/them, 20): Saybrook sophomore from San Antonio, first-gen, streetwear and hip-hop, tight budget, lives on TikTok/Reels. |
| `profiles/profile_parent.json` | **Maria Rivera** (she/her, 49): Jordan's mom, first in the family with a child at Yale, likes classic crest designs, buys gifts and "Yale Mom" pride items, on Facebook and email, usually watches **muted**. |

The two are from the same family on purpose. It shows the same ad can work for one person and fail for the other: an edgy hip-hop parody with no captions might land with Jordan and miss Maria entirely.

### Why these fields

The model rejects unknown keys (`extra="forbid"`), so a typo in a profile file fails loudly instead of being silently ignored. Fields are grouped by the question they answer for the ad judge:

**Who they are:** is the ad even talking to them?

| Field | Why it matters for an ad |
|---|---|
| `name`, `customer_type` (fixed list: student / parent / alumni / staff / visitor) | The basic audience split. Students and parents respond to completely different ads. |
| `pronouns` | So the judge never has to guess. The Problem 5 judge wrongly used "his" before this field existed. |
| `age`, `hometown` | Generational references and whether the person is on campus or far away (shipping matters for Maria). |
| `yale_connection` | The *specific* tie (Saybrook, Class of 2028, "parent of"). An ad showing their college or "Yale Mom" gear feels personal; generic "YALE" feels less so. |
| `life_stage` | Timing and emotion: a proud first-gen parent and a settled-in sophomore want different things. |

**What they'd buy:** would they want the product shown?

| Field | Why it matters for an ad |
|---|---|
| `preferred_garments` (uses the catalogue's `GarmentType` list) | Links directly to catalogue products, so "the ad shows a hoodie; Jordan wears hoodies" can be checked exactly. |
| `style_preferences`, `color_preferences` | Streetwear vs classic, navy vs loud prints. Decides whether the product *looks* right to them. |
| `already_owns`, `wishlist` | An ad for something they already have is weaker. An ad for something on their wishlist (Saybrook gear, a "Yale Mom" crewneck) is much stronger. |
| `purchase_occasions` | The Game, Family Weekend, gifts, commencement. An ad tied to one of these gives a reason to buy *now*. |
| `budget` (`Budget`: min/max USD, price sensitivity, notes) | Numbers instead of a vague phrase, so the judge can say "no price shown, and Jordan is highly price-sensitive." |

**How they shop and what persuades them:** would the ad actually lead to a purchase?

| Field | Why it matters for an ad |
|---|---|
| `shopping_channels` | Phone-online vs in person on campus visits. Decides whether a URL/QR or a store location is the right call to action. |
| `decision_factors` (most important first) | What closes the sale (price, quality, shipping, returns), so the judge can check whether the ad answers it. |
| `media_habits` (`MediaHabits`: platforms, formats, attention span, **watches with sound**) | Whether they'd even *see* the ad, how fast it must hook them, and whether sound or captions matter. An ad that depends on its song fails for Maria, who watches muted. |

**What resonates emotionally:** would the ad feel like it's for them?

| Field | Why it matters for an ad |
|---|---|
| `interests`, `cultural_references` | Whether they'd recognise and enjoy the ad's references. Kept general on purpose (e.g. "popular hip-hop artists", not the exact artist the test ad parodies), so the profile doesn't rig the result. |
| `values` | Authenticity and belonging vs family pride and hard work. The emotional reason to buy. |
| `tone_that_works`, `turn_offs` | The most direct signals for `tone_fit`: what makes them lean in, and what makes them scroll past or distrust the ad. |
| `notes` | Anything else useful, like "shares funny ads in the group chat" or "posts proud-parent photos". |

Each field maps onto one or more of the 6 scoring dimensions in `AdEffectiveness`:

| Dimension | Profile fields it draws on |
|---|---|
| attention | media habits |
| profile_relevance | connection, life stage, interests |
| product_appeal | garments, style, wishlist, budget |
| brand_clarity and persuasion | shopping channels, decision factors, occasions |
| tone_fit | values, tone, turn-offs |

`output/ad_effectiveness.json` (Problem 5) was rerun with this new student profile: 57/100, mixed, all 3 judges agreeing.

### Working faster

Earlier problems were slow for three reasons:
- **Many small edits, one at a time.** Now each change is planned first and made in a few batched steps.
- **Shell heredocs failed on apostrophes and had to be redone.** New files are now written directly.
- **Full AI runs were repeated as checks.** Slow model runs now happen only when the task needs fresh output; otherwise the check is a quick local one (like validating these profiles), which takes seconds.

## Problem 8: Safety rules and audit trail

*Since Problem 9, every run is also capped at 10 model requests and 12 tool calls (`RUN_LIMITS` in `agents.py`).*

### Safety rules

`prompts/prompt.md` now starts with **"Safety rules for images and video"**, before the abilities. The rules override everything else in the prompt.
- **Must:** look only at clothing, products, on-screen text, setting and ad content; describe people by role or clothing; treat images and profiles as confidential and refer to them by path only; report refusals and unclear images instead of guessing; mark inferences as inferred.
- **Must not:** identify or guess who anyone is (celebrities and influencers included); infer or comment on sensitive traits or bodies; claim someone endorsed Campus Customs; track or profile people across images; edit or re-encode images to get around a content filter; add personal details about people who may be minors.

The main agent loads the file as its system prompt. `tools.py` also pulls out the safety section (`SAFETY_RULES`) and adds it to the instructions of **every vision sub-agent**: describe, verify, video analysis and judge. Those sub-agents are the calls that actually see the photos, so the rules have to apply there too. There's one copy of the rules, in `prompt.md`, used everywhere.

### Audit trail

Every run of the agent appends to `output/audit_trail.json`: CLI `--image`, `--video` / `--profile` and `--eval`. `run_with_audit` in `agents.py` steps through the agent loop (`agent.iter`) and appends an `AuditEntry` after **each iteration**, while the run is still going. Earlier entries are never wiped. The file is re-read, extended and swapped in atomically, so a crash can't leave half-written JSON. A lock keeps concurrent `--eval` runs from overwriting each other.

**`AuditEntry` fields (in `models.py`) and why:**

| Field | Why |
|---|---|
| `timestamp`, `duration_s` | When each step happened, and how far into the run. Shows where time goes (see below). |
| `run_id`, `step` | Group the steps of one run and put them in order, even when runs overlap in `--eval`. |
| `kind` (request / model_response / tool_results / final_output / error) | What type of step it was, so you can filter (e.g. show only errors). |
| `action_summary` | One plain sentence about what the agent *visibly* did ("Model chose to call: identify_product"). It's written from the step's data, and **the model's hidden reasoning is never stored**. |
| `user_request` | The request that started the run (first step only), so every run can be traced back to what was asked. |
| `model_text` | Any visible text the model wrote, truncated. |
| `tool_calls` (name, call ID, args) | Exactly which tool ran with which arguments. Arguments are **file paths, never image data**, and very long ones are truncated. |
| `tool_results` (name, call ID, ok, short summary) | The key outcome of each tool (e.g. `present=True id=dry-zone-long-sleeve conf=0.98`) without dumping the whole object. `ok=false` marks retries and failures. |
| `stop_reason` | The model's finish reason (`tool_call`, `stop`...), or `final_output` / `error: <type>`. Shows why each step or run ended. |
| `model_name`, `input_tokens`, `output_tokens` | Cost and model version for each step. |

### Real data in the file

`output/audit_trail.json` holds **3 runs, 17 entries**:
- **1 image run that completed** (`image_03_true.jpeg` → `dry-zone-long-sleeve`, 0.98).
- **2 runs** (image 01 and the ad video with the student profile) that **crashed in my first version of the audit code**: it called `run.usage()`, but `usage` is a property, not a method. They were logged with `kind="error"` and are kept, because the trail is append-only. They show error logging working as intended, and the video run still records the full tool sequence: profile + analysis → products → judge.

**What the audit already showed:** in the completed image run, the tool returned its answer **8 s** into the run, but the run ended at **154 s**. The last step, where the agent retyped the whole `ProductIdentification` as its final answer, took **146 s and 2,132 output tokens**. That's the inefficiency flagged in `agent_evaluation.md` (Problem 4), now measured. The ad ability already avoids it with an output function (Problem 5); giving identification the same fix would cut image runs to about 10 s.
