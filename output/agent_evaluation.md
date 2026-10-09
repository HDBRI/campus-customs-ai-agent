# Agent Evaluation: Campus Customs "Is That Our Shirt?" Agent

**Test set:** the 4 photos in `data/test_images/`. The ground truth comes from each filename (`_true` = a Campus Customs product is in the photo).
**Command:** `python agents.py --eval`. The outputs are in `output/identify_product.json`: 4 entries, each validated against `ProductIdentification`.

## Scoreboard

| Image | What's in it | Truth | Agent said | Confidence | Verdict |
|---|---|---|---|---|---|
| `image_01_true` | Proud dad, thumbs up, grey "YALE UNIVERSITY DAD" tee, in front of the SOM sign | ✅ present | `yale-dad-t-shirt` | 0.99 | ✅ Correct, and the right product |
| `image_02_false` | Grey "ESSENTIALS" hoodie in a glass skybridge | ❌ absent | not present | 0.99 | ✅ Correct |
| `image_03_true` | Lecturer mid-wave, navy "YALE BULLDOGS" long-sleeve | ✅ present | `dry-zone-long-sleeve` | 0.98 | ✅ Correct, and the right product |
| `image_04_false` | Joyful woman under Gothic arches, navy tee with a tiny "Balenciaga" | ❌ absent | not present | 0.99 | ✅ Correct |

**4/4 on "is it there?", 2/2 on "which one?"** No false positives, no false negatives, and no made-up product IDs. On paper, a flawless report card. Now for what the report card leaves out.

## What went well

**1. It told the Dad tee apart from its whole family.** The shortlist for image 01 had the Dad t-shirt, the Dad crewneck and the Dad hoodie in the top 3. A lazy model sees "YALE DAD" and grabs the first one. Ours checked the sleeves and neckline and picked the **t-shirt**, noting "it is not a crewneck, hoodie, or any of the other Yale designs shown."

**2. It won the hardest round in the set.** Image 03 is the real test. The catalogue has two navy long-sleeves that both say "YALE BULLDOGS": the plain Sport-Tek `dry-zone-long-sleeve` and the Under Armour `ua-mens-tech-l-s-2-0`. The agent ruled out the Under Armour one for concrete reasons: "no Under Armour logo, outlined lettering, or diagonal stripe pattern is visible." I checked both product photos, and that's exactly the difference. This is where the design paid off: the cheap local shortlist put both lookalikes at #1 and #2, and the vision call did the fine-grained comparison.

**3. It doesn't fall for "navy tee = Yale tee".** Image 04 is a sneaky negative: a navy short-sleeve tee on a woman under Yale's Gothic arches, practically posing for the admissions brochure. The #1 shortlist result was `football-left-chest-t-shirt`, which is *also* a navy tee with a small chest wordmark. The agent actually read the tiny logo ("Balenciaga"), and noted that the football shirt's "white two-line YALE FOOTBALL mark" wasn't there. Setting and color alone didn't fool it.

**4. The agent did its job and nothing more.** The saved message traces show the same pattern on all 4 runs: one `identify_product` call, then the final answer, with **zero fields changed** between the tool's result and the agent's output. It didn't editorialize, didn't make up evidence, and didn't make extra tool calls.

**5. The efficiency limits held.** It made 2 vision calls per photo, never compared the query photo against the catalogue one product at a time, and sent at most 10 product images per call: `candidates_checked` has exactly 10 entries every time.

## What went badly (or would have, given the chance)

**1. The confidence scores tell us nothing.** The scores were 0.99, 0.99, 0.98, 0.99. It's like a student who writes "100% sure" on every exam question. Right this time, but you learn nothing from it. A confidence field that never goes below 0.98 can't be used to set a threshold. We don't know whether it would say 0.99 on a blurry, half-hidden shirt it got *wrong*. Four easy photos can't show whether it's well-calibrated.

**2. The final step is wasteful: the agent copies the whole answer out by hand.** This is the biggest real inefficiency, and it only shows up in the traces. After the tool returns a finished `ProductIdentification`, the outer agent **generates the whole JSON again as its final answer**, including all 10 shortlisted candidates and their scores. That costs **1,600–3,100 output tokens per image**, just to repeat what it was already given. It got every field right this time, but it's still an expensive copy, and every rewrite is a chance for a typo in a product ID.

**3. The shortlist gets sloppy when there's no real match.** For image 04 (a navy tee), the top 10 included `yale-aunt-hoodie`, `berkeley-1-4-zip` and `divinity-school-fleece-sweater`. Three of the 10 slots went to garments with hoods, zippers or fleece, which the query photo obviously doesn't have. Generic words like "Yale" and "navy" in the photo description outweighed the structure penalties. It didn't matter here because the answer was "none", but on a harder positive photo, those are slots the right product could have used.

**4. Step 1 sometimes misreads text.** In one of the development runs (not the saved one), step 1 read the partly hidden "Y_LE BULLDOGS" on image 03 as **"LIFE BUSINESS"**. The shortlist still put the right shirt at #1, thanks to the garment-type and color scores, and step 3 sees the real images. But the whole design depends on step 1 describing the photo in catalogue terms. Garble the text and you're counting on the structure scores to rescue it.

**5. The infrastructure was shakier than the model.** Nothing in the saved run failed, but the history does:
- The very first `--eval` **crashed**: Azure's content filter rejected a comparison call, and the same request passed on the next run. (That's why `ProductIdentification.error` exists now.)
- Portkey **caches** responses. Rerunning the eval finished in **3.5 s**, compared with about 30 s for a real run, with identical wording. So the saved outputs are real model answers, but they're **replays of the previous run**, not new samples. My attempt to force an uncached run (`x-portkey-cache-force-refresh`) hung for 20 minutes and had to be stopped. So "4/4 again!" on a rerun is less impressive than it sounds.

## Did it make a mistake?

**No**, not in the verdicts. But the test set went easy on it:
- Every photo has **one person, one top, facing the camera, text readable**.
- The positives are catalogue designs with **big, clear wordmarks**. The negatives have **obviously different branding** (ESSENTIALS, Balenciaga).
- Nothing tested the **"yes, but can't tell which"** path (`product_present=true, product_id=null`), groups of people, backs, or hidden logos. Nothing tested the classic trap either: a Yale shirt that *isn't* in the catalogue.

Our best guess at its **first real mistake**: a navy tee with a small, unreadable chest logo, photographed from far away. Image 04 shows the #1 candidate would be `football-left-chest-t-shirt`, and reading that tiny "Balenciaga" was the only thing between us and a false positive. Take the text away and the agent has color, cut and placement, which all match. We'd expect it to say "present", with 0.99 confidence, of course.

## How we'd improve it (not implemented yet)

1. **Make the tool's result the final answer.** Use PydanticAI's output-function / `ToolOutput` pattern, so the `ProductIdentification` from `identify_product` becomes the agent's output directly, with no second copy. That saves roughly 2k tokens and several seconds per image, and removes the risk of mistakes in the copy.
2. **Treat hood, zipper and garment family as hard filters.** Drop products that don't fit before ranking (a tee query shouldn't get fleece jackets), then rank by text similarity. Reduce the weight of words that nearly every product has, like "Yale" and "navy".
3. **Make confidence meaningful.** Add a `text_readable` / `visibility` signal to the verdict (step 1 already records `visibility`). Cap confidence when the decisive cue isn't readable. Then check calibration on a larger set: do 0.9-confidence answers turn out right about 90% of the time?
4. **Check the text again when it matters.** If step 1's text doesn't match anything in the catalogue (hello "LIFE BUSINESS") but garment and color match strongly, re-run the shortlist on structure alone, or ask step 3 to re-read the text next to the candidates.
5. **Build a nastier test set.** Add Yale shirts that aren't Campus Customs, "YALE" hoodies that aren't in the catalogue, back views, crowds, hidden logos, video frames from `data/videos/ad_humble.mp4`, and a pair of real lookalikes to test `product_id=null`. Four clean photos mostly show that the pipeline doesn't crash.
6. **Make evaluation reproducible.** Turn off Portkey's cache for eval runs (and find out why the force-refresh header hung), set a timeout on each request, and report latency and token cost per image alongside accuracy.

## Bottom line

On paper it's a perfect score, and it earned it. It told near-identical twins apart for the right reasons and wasn't fooled by a navy tee in front of Yale arches. But the test was easy, the confidence scores carry no information, and the agent pays about 2k tokens per image to copy out an answer it already has. **Grade: A on the test, B+ on "would I bet the store on it?"** Next step: tougher test photos, and making the tool's answer the final output.


---

# Part 2: The Ad Runs (Problem 7): One Video, Two Riveras

**Commands:** both runs were made with the exact commands from the assignment:
- `python agent.py --video "data/videos/ad_humble.mp4" --profile "profiles/profile_student.json"`
- `python agent.py --video "data/videos/ad_humble.mp4" --profile "profiles/profile_parent.json"`

**Output:** `output/ad_effectiveness.json`, a list of 2 `AdEffectiveness` results, both validated.

**The ad:** 9 seconds. A lead performer in a navy YALE hoodie strikes the hand-on-chin pose under a highway overpass while a crowd in Yale gear gathers behind. It's very Kendrick "HUMBLE." It never mentions Campus Customs.

## Scoreboard

| | Jordan (student, 20) | Maria (parent, 49) |
|---|---|---|
| **Verdict** | mixed | **ineffective** |
| **Overall** | 57/100 (3 judges: 57, 57, 57) | 40/100 (3 judges: 37–40) |
| **Purchase likelihood** | 0.18 | 0.08 |
| attention | 8 | 7 |
| profile_relevance | 7 | 5 |
| product_appeal | 8 | 6 |
| brand_clarity | 2 | 2 |
| persuasion | 1 | 1 |
| tone_fit | 8 | **3** |
| Products found | `basic-hoodie-big-yale` (possibly the Champion lookalike) | same |

## What went well

**1. It told the two people apart, in the right direction and for the right reasons.** Same ad, same analysis, same products, and a 17-point gap. The biggest swing is **tone_fit: 8 vs 3**. Jordan's profile says "confident, not corporate". Maria's says "warm, proud" and lists "ads that feel aimed at teenagers" as a turn-off. The judge treated these as real preferences, not decoration. This is the whole point of a *per-customer* judge, and it worked.

**2. It picked up the muted-viewer detail.** Maria's profile has `watches_with_sound: false`. The judge flagged "no captions or readable text beyond YALE, which matters because she watches without sound", and its first recommendation for her is a *captioned* hook. That detail is buried in a nested `MediaHabits` field, and the judge still found it and acted on it. Problem 6's profile design paid off here.

**3. It was consistent about the ad's real flaws.** `brand_clarity = 2` and `persuasion = 1` for **both** people. That's right: "never names Campus Customs, no price, no link, no call to action" is a problem with the ad, not with the viewer. A judge that gave these different scores for different people would be making things up. Ours kept the ad's fixed flaws fixed and let the viewer-dependent dimensions move.

**4. The recommendations are tailored, not generic.**
- **For Jordan:** "Yale students: 15% off today", a price under their $60 ceiling, Saybrook gear, and a tappable shop CTA for phone shopping.
- **For Maria:** "Proud Yale Mom, ready for Family Weekend?", a Yale Mom crewneck, Grandma/Grandpa gift options, shipping time and easy returns.

Each list pulls from that person's `wishlist`, `purchase_occasions` and `decision_factors`. A marketer could build two separate edits of the ad from these.

**5. The judges agreed.** All three said 57 for Jordan, and 37–40 for Maria. Scores varied between runs in Problem 5; the median-of-3 setup settled that.

**6. Pronouns were right.** Jordan is "they/them" everywhere, and Maria is "she/her", as stated in her profile. The Problem 6 `pronouns` field did its job.

## What's off or questionable

**1. Attention = 7 for someone who watches muted.** The judge *mentions* that Maria watches without sound, then gives her attention a 7 anyway. For a muted viewer, the "bass-heavy" soundtrack contributes nothing, and a 9-second clip with no captions is easy to scroll past. I'd call it a 5. Right fact, not enough weight given to it.

**2. Maria's product_appeal of 6 is generous.** The judge says the hoodie "fits her wishlist for a Yale Mom crewneck." It doesn't: it's a hoodie, not a crewneck, and it says YALE, not MOM. It also uses the *possible* Champion lookalike's quality as a selling point, although that product is only a maybe. The judge is being nice when it should be strict.

**3. The overall score is too high for an ad that can't sell anything.** Jordan's ad scores **57 ("mixed")**, but the ad has no store name, no price and no link. The overall score is a plain average, so a great-looking ad with no call to action still lands mid-scale. The goal is "convince them to *shop at Campus Customs*", and on that the ad is close to a zero. `purchase_likelihood` (0.18) tells the truth better than `overall_score` does.

**4. The purchase likelihoods aren't realistic.** An 18% chance that one 9-second view leads to a purchase is very optimistic; real ad conversion is usually in the low single digits. The *ordering* (0.18 > 0.08) is believable, but the numbers mean "relatively likely", not a real probability. Confidence was 0.94 for both runs, the same always-high confidence problem we saw with identification.

**5. The "HUMBLE." reference depends on the filename.** The agent recognizes the parody mainly because the file is called `ad_humble.mp4`, plus the staging and a bass-heavy beat around 152 BPM (probably double time of about 76). Rename the file `ad_01.mp4` and it would probably just say "hip-hop visual language" again. For Jordan, that reference is a big part of why tone_fit gets an 8. So part of the score rests on the filename, which is a weak signal.

**6. It still can't tell which hoodie it is.** `basic-hoodie-big-yale`, with the Champion one as a lookalike. Both judges comment on the uncertainty. Better than the Problem 5 version, which counted it as two products, but still unresolved.

**7. Each profile run redoes the video work.** The two commands are separate processes, so the second run re-extracted the frames and re-sent the video analysis. Portkey's cache made that cheap this time, but the design doesn't guarantee it.

## Did it make a mistake?

**No wrong verdict.** A hip-hop parody with no call to action *should* be "mixed at best" for the streetwear student and "ineffective" for the parent. The mistakes are in **calibration**, not direction: attention too high for a muted viewer, product appeal too generous for Maria, and an overall score that treats "can't buy it" as just one factor out of six.

## How I'd improve it (not implemented)

1. **Cap the score on conversion.** If `brand_clarity` or `persuasion` is ≤ 2, cap the verdict at "mixed" and the overall at about 50. Or weight those two dimensions double, since selling is the goal.
2. **Score a muted viewing.** If `watches_with_sound` is false, tell the judge to score attention and tone as if the audio were silent, and to check for captions.
3. **Stricter product matching.** Make the judge check the ad's products against the customer's `preferred_garments` and `wishlist` field by field (a hoodie isn't a crewneck), and not use `possible_products` as evidence.
4. **Calibrate purchase likelihood.** Give the judge a base rate ("a single social ad view converts roughly 1–3% of viewers") and ask for an adjustment from that.
5. **Test without the filename.** Run the same ad under a neutral filename. If the score drops a lot, the result depends on the name, and that should go in `limitations`.
6. **Multiple profiles in one run.** Allow `--profile a.json --profile b.json`, so the frames, audio, analysis and products are computed once and each profile only costs the 3 judge calls.

## Bottom line

**The agent reads people well.** It noticed Maria watches muted, knew Jordan hates corporate ads, and rewrote the ad two different ways. **It's too generous with numbers**: a no-CTA ad for a student still gets a 57 and an 18% purchase chance. So the per-customer judgement is solid, but the headline score needs fixing. If Campus Customs acted on one line from this output, it should be what both runs say: **put the store's name, a price and a link in the ad.**
