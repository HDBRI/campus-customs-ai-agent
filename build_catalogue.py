"""Turn every product photo in data/products/ into a structured catalogue entry.

Photos are described concurrently: an asyncio semaphore keeps N vision calls
in flight at once instead of waiting on them one by one. Results already in
catalogue.json are reused, so a rerun only processes new or failed images.

Usage:
    python build_catalogue.py                  # all images, 16 at a time
    python build_catalogue.py --concurrency 32
    python build_catalogue.py --limit 5        # quick test
    python build_catalogue.py --force          # ignore cache, redo everything
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from models import Catalogue, CatalogueEntry, ProductAttributes

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
load_dotenv(HERE.parent / ".env")

MODEL_NAME = os.getenv("AI_MODEL", "gpt-5.6-luna")
PRODUCTS_DIR = HERE / "data" / "products"
OUTPUT_PATH = HERE / "catalogue.json"
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
MAX_RETRIES = 3

INSTRUCTIONS = """You catalogue Yale merchandise from product photos.
Describe only what is visible. Record every piece of printed text exactly as written,
including small text. Be specific about colors, graphics, and where the design sits,
since these entries will later be matched against photos and video frames of people
wearing the products. The filename is a hint, but the image wins if they disagree."""


def build_agent() -> Agent[None, ProductAttributes]:
    key = os.getenv("PORTKEY_API_KEY")
    if not key:
        raise RuntimeError("PORTKEY_API_KEY is missing from HW3/.env or the repository-root .env")
    client = AsyncOpenAI(api_key=key, base_url=os.getenv("PORTKEY_BASE_URL", "https://api.portkey.ai/v1"),
                         default_headers={"x-portkey-provider": os.getenv("PORTKEY_PROVIDER", "openai")})
    model = OpenAIChatModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))
    return Agent(model, output_type=ProductAttributes, instructions=INSTRUCTIONS)


async def describe_image(agent: Agent[None, ProductAttributes], path: Path, sem: asyncio.Semaphore) -> CatalogueEntry:
    image = BinaryContent(data=path.read_bytes(), media_type=IMAGE_TYPES[path.suffix.lower()])
    async with sem:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = await agent.run([f"Filename: {path.name}", image])
                break
            except Exception as exc:
                # A content-filter rejection returns the same answer every time, so don't retry it.
                if attempt == MAX_RETRIES or "content_policy_violation" in str(exc):
                    raise RuntimeError(f"{path.name}: {exc}") from exc
                await asyncio.sleep(2 ** attempt)  # back off on rate limits / transient errors
    return CatalogueEntry.from_attributes(
        result.output,
        product_id=path.stem,
        image_path=path.relative_to(HERE).as_posix(),
    )


def load_cache() -> dict[str, CatalogueEntry]:
    if not OUTPUT_PATH.exists():
        return {}
    catalogue = Catalogue.model_validate_json(OUTPUT_PATH.read_text(encoding="utf-8"))
    return {e.product_id: e for e in catalogue.entries}


def save(entries: dict[str, CatalogueEntry]) -> None:
    catalogue = Catalogue(model=MODEL_NAME, entries=sorted(entries.values(), key=lambda e: e.product_id))
    OUTPUT_PATH.write_text(catalogue.model_dump_json(indent=2), encoding="utf-8")


async def main(concurrency: int, limit: int | None, force: bool) -> None:
    images = sorted(p for p in PRODUCTS_DIR.iterdir() if p.suffix.lower() in IMAGE_TYPES)[:limit]
    entries = {} if force else load_cache()
    todo = [p for p in images if p.stem not in entries]
    print(f"{len(images)} images, {len(images) - len(todo)} cached, {len(todo)} to process ({concurrency} at a time)")
    if not todo:
        return

    agent = build_agent()
    sem = asyncio.Semaphore(concurrency)
    tasks = {asyncio.create_task(describe_image(agent, p, sem)): p for p in todo}
    failures: list[str] = []
    start = time.perf_counter()

    for done, task in enumerate(asyncio.as_completed(tasks), 1):
        try:
            entry = await task
            entries[entry.product_id] = entry
            print(f"[{done}/{len(todo)}] {entry.product_id}: {entry.title}")
        except Exception as exc:
            failures.append(str(exc))
            print(f"[{done}/{len(todo)}] FAILED: {exc}")
        if done % 10 == 0:
            save(entries)  # checkpoint so a crash doesn't lose finished work

    save(entries)
    elapsed = time.perf_counter() - start
    print(f"\nDone in {elapsed:.1f}s ({elapsed / len(todo):.2f}s per image). "
          f"{len(entries)} entries written to {OUTPUT_PATH.name}, {len(failures)} failed.")
    if failures:
        print("Rerun the script to retry the failed images.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--concurrency", type=int, default=16, help="max vision calls in flight at once")
    parser.add_argument("--limit", type=int, default=None, help="only process the first N images")
    parser.add_argument("--force", action="store_true", help="ignore cached entries in catalogue.json")
    args = parser.parse_args()
    asyncio.run(main(args.concurrency, args.limit, args.force))
