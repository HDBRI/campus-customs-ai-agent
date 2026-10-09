# HW3 — AI Prompts

Log of the prompts used for each problem in this assignment.

<!--
Template for each problem:

## Problem N: Title

**Prompt:**
> ...

**Follow-up prompt:** (if needed)
> ...
-->

## Problem 2: Build the product catalogue

**Prompt:**
> write build_catalogue.py that turns every product photo in data/products/ into a structured catalogue entry; description & other fields that will be useful for later matching. Put the catalogue entry type in models.py as a pydantic / pydanticAI model. This will have many many images so we neeed to figure out a way to make the process faster so you dont have to go through each photo one by one, should be faster than a plain sequential loop, maybe you can make it a fast parallel process

**Follow-up prompt:**
> start output/harness.md, in it I want u to put how we sped up the catalogue & which fields we used in the catalogue model in models.py & why we chose these fields

**Follow-up prompt 2:**
> write the 3 entries by hand from the photos

## Problem 3: Product identify agent

**Prompt:**
> build a campus customs agents as 4 files - prompts/promts.md - system prompt (load it into the agent; we will add to this file later), agents.py - PydanticAI agent entry point, tools.py - put the agent's tools / helper functions here, model.py - pydantic/ pydantic AI structured types. Its first ability, take an image & decide whether a Campus Customs product appears it it & which one if we can tell. Implement that tool logic in tools.py & wire it from agents.py. Find a way to do this without checking every catalogue image one at a time agianst the query photo & without sending more than 10 product images in a single call to AI. Add the structured return type for this ability to models.py as a Pydantic/ PydanticAI model (keep growing models.py whenevr the agent needs a new typed object)

**Follow-up prompt:**
> The agent mjust take an image path from the terminal, use a command like python agent.py --image "data/test_images/example.jpg".  Save the agent's structired output for this run to output/identify_product.json (matching identity model in models.py). One test image is enough here. In output/harness.md write how our product is doing product identification & what we did to make it efficient & which fields are in the identity model in models.py & why we chose those fields

## Problem 4: Test identify on 4 images

**Prompt:**
> run the agnet on teh 4 photos in data/test_images/. each file name will tell the ground truth - whether a campus customs product is in the image (true) or not (false). Save the agent's outputs for all 4 images to output/identify_product.json - each entry should match the identify Pydantic/PydanticAI model you put in models.py. Read what the agent did & in your own vibe (witty smart funny) evaluate its performace - what was good, what was bad, why it made a mistake if it did & how we would improve the agent if needed (no fix needs to be implemented as of now). Then save that write up to output/agent_evaluation.md

**Follow-up prompt:**
> lets save it separately just incase *(save Problem 3's single-image result to its own file, `output/identify_product_single.json`, so the 4-image list doesn't overwrite it)*

## Problem 5: Ad video + profile ability

**Prompt:**
> Add an ability so agent can take a video & a customer profile JSON file then judge how effective the video would be at convinving the customer to shop at Campus Customs. put the new tool code in tools.py (same tool file as identify). Update the same prompts/prompt.md so the agent knows how to use this ability, keep one prompt file, add to it & do  not start a second one. Put the structired type for this ability in models.py as a Pydantic/PydanticAI model (same models.py file as your catalogue & identoty types). wire the terminal the same way we will in problem 7 - python agent.py --video "data/videos/ad_humble.mp4" --profile "profiles/profile_student.json".  sAVE the agent's structured output for the run to output/ad_effectiveness.json (matching the ad-effectiveness model in models.py). One profile is enough here. In output/harness.md wrote the tools we gace the agent for this video + profile job (what each tool does in 1 short line) & which fields are in the ad-effectiveness model in models.py & why we chose those fields

**Follow-up prompt:**
> u decide just fix it so we can achieve our objective *(fix the open issues from the first run: no audio, the same hoodie counted as two products, and scores varying between runs)*

## Problem 6: Student & parent profiles

**Prompt:**
> create profiles/profile_student.json & profiles/profile_parent.json. These describe a typical yale student & a parent of a yale student - or any student/parent you like, including yourself. Include useful fields that would matter for whether an ad resonates. Define the profile shape in models.py as a pydantic / pydanticAI model, then save the filled in student & parent instances as those JSON files. In output/harness.md explain why u chose those profile fields.  Also why are you taking so long for each prompt figure out a way to do it faster but with the same efficiency.

**Follow-up prompt:**
> go for it *(rerun Problem 5's ad judgement with the new student profile)*

## Problem 7: Run ad for both profiles

**Prompt:**
> Run the agent on the Capcom Plus customs ad video for both profiles. python agent.py --video "data/videos/ad_humble.mp4" --profile "profiles/profile_student.json" python agent.py --video "data/videos/ad_humble.mp4" --profile "profiles/profile_parent.json". Save the structured results for both runs to output/ad_effectiveness.json. Your ad effectiveness by Pydantic, Pydantic AI model from models.py. Read that output in your own vibe. Write what you think in output/agent_evaluation.MD. Add a new section for the ad runs. Your ideas matter more than polished prose. Then assist me with what you noticed and write the file.
>
> be efficient & dont take forever to do this pls

## Problem 8: Safety rules plus audit trail

**Prompt:**
> * Add safety rules for processing images, what the agent must/must not do with customer or influencer photos, to the same `prompts/prompt.md` file you have been growing. Add a clear safety section the agent will load as its system prompt.
> * Make the agent append to `output/audit_trail.json` on every run. For each agent loop iteration, record enough to audit later: time, a brief action/reason summary, tool name, ARGs + short result, stop reason. Do not record private chain-of-thought or hidden reasoning.
> * Append as the agent runs, do not wipe the file each time.
> * Put an audit entry type in `models.py` Pydantic / Pydantic AI model, so each appended record is structured the same way.
> * In `output/harness.MD`, briefly say which audit fields you included and why.
> * Run the agent on at least one of the test images or the video so the audit file has real data.

## Problem 9: Finish the harness

**Prompt:**
> finish the harness - complete output/harness.md so a manager could understand teh sytstem - include - all tools the agent uses, its abilities (identody product in image; judge ad for a profile; anything else u added), the Pydantic/ pydanticAI models in models.py - what each type is for & why its fields were chosen, safety rules, specs such as max loop iterations, how many frames you sample from videos & any other limits that matter for cost or quality. Keep the earlier harness sections (catalogue speedup, field choices, identody efficiency, profile fields, video tools) This problem is about mkaing the whole doucment coherent & complete. - please be fast & dont take very long but be effieicnt
