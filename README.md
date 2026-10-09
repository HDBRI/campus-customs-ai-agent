# Campus Customs AI Agent: Product Recognition & Ad Effectiveness

An AI agent for **Campus Customs**, a Yale apparel brand, that answers two commerce questions from images and video:

1. **"Is one of our products in this photo, and which one?"** Identifies the exact catalogue product a person is wearing.
2. **"How well would this ad video convince *this* customer to buy?"** Scores a short-form ad for a specific customer profile and explains why.

Built by Ria Vijh in Yale SOM's *AI Foundations for Managers* (MGT 409), Fall 2026.

## Results

| Ability | Result |
|---|---|
| **Product identification** | **4/4** test photos correct, including telling apart two near-identical navy "YALE BULLDOGS" long-sleeves and rejecting a lookalike navy tee (it was Balenciaga) |
| **Ad effectiveness** | Same ad scored **57/100 for a student** and **40/100 for a parent**. Both lose most points on brand clarity and call to action |
| **Catalogue** | 102 products turned into structured, searchable entries from product photos |

## How it works

**Product identification (2 AI calls per photo).** The agent describes the clothing in the photo using the catalogue's own vocabulary, shortlists the 10 closest products locally (keyword and attribute scoring, no AI), then checks only those 10 visually in a single call. It never compares the photo against the whole catalogue one product at a time.

**Ad effectiveness (about 10 AI calls per ad).** The agent samples frames from the video, measures the soundtrack, analyzes the hook, scenes, branding and call to action, finds which catalogue products appear, and then has three AI judges score the ad on six dimensions for the given customer: attention, profile relevance, product appeal, brand clarity, persuasion, and tone fit. The median score on each dimension is used.

**Guardrails.** Every output is a validated, typed result (Pydantic). Code, not the model, sets IDs, scores and verdicts so they can't be made up. Every step is logged to an append-only audit trail.

**Stack:** Python, PydanticAI, OpenAI API (via Portkey), ffmpeg.

## What to read

| File | What's in it |
|---|---|
| [`output/harness.md`](output/harness.md) | Full system write-up: tools, data types, safety rules, limits, and the build log |
| [`output/agent_evaluation.md`](output/agent_evaluation.md) | Honest evaluation: what worked, what didn't, and how to improve it |
| [`output/ad_effectiveness.json`](output/ad_effectiveness.json) | Ad scores and reasoning for each customer profile |
| [`output/identify_product.json`](output/identify_product.json) | Product identification results on the 4 test photos |
| [`profiles/`](profiles/) | The two customer profiles (student, parent) |
| [`agents.py`](agents.py), [`tools.py`](tools.py), [`models.py`](models.py), [`prompts/prompt.md`](prompts/prompt.md) | The agent, its tools, its data types, and its system prompt |
| [`AI_prompts.md`](AI_prompts.md) | Log of the prompts used to build it |

## Run it locally

**Prerequisites:** Python 3.11+, ffmpeg, and a Portkey API key.

```bash
pip install -r requirements.txt
cp .env.example .env        # then set PORTKEY_API_KEY
```

Add the course data (not in the repo, see [`data/README.md`](data/README.md)), then:

```bash
python agent.py --image "data/test_images/image_03_true.jpeg"
python agent.py --eval
python agent.py --video "data/videos/ad_humble.mp4" --profile "profiles/profile_student.json"
```

## Not in the repo, on purpose
- `.env` (API keys): use `.env.example` as the template.
- Product photos, test images and the ad video: course-provided data.
