"""Add hand-written catalogue entries for photos the API's content filter refused.

These three products return `content_policy_violation` from Azure OpenAI (false
positives on plain crest garments), so they were described by hand from the
photos and validated against the same Pydantic model. Run after build_catalogue.py:

    python add_manual_entries.py
"""

from __future__ import annotations

from build_catalogue import HERE, PRODUCTS_DIR, load_cache, save
from models import CatalogueEntry, ProductAttributes

MANUAL: dict[str, ProductAttributes] = {
    "benjamin-franklin-t-shirt": ProductAttributes(
        title="Heather Grey Benjamin Franklin College Crest T-Shirt",
        description=(
            "A light heather grey short-sleeve crew-neck t-shirt with a large centered crest on the chest. "
            "The shield is quartered in blue and red, with white lightning-bolt diagonals in the blue quarters "
            "and white fleurs-de-lis in the red quarters. Below it, 'BENJAMIN FRANKLIN COLLEGE' is printed "
            "in black serif capitals on two lines."
        ),
        garment_type="t-shirt",
        primary_color="heather grey",
        secondary_colors=["blue", "red", "white", "black"],
        printed_text=["BENJAMIN FRANKLIN", "COLLEGE"],
        graphics=["Benjamin Franklin College shield crest", "lightning bolts", "fleurs-de-lis"],
        graphic_placement="full-front",
        print_style="screen print",
        affiliation="Benjamin Franklin College",
        brand=None,  # neck tag not legible
        has_hood=False,
        has_zipper=False,
        sleeve_length="short",
        style_keywords=["collegiate", "heraldic", "classic", "minimal"],
    ),
    "berkeley-sweater-fleece-jacket": ProductAttributes(
        title="Heather Grey Berkeley Sweater Fleece Jacket",
        description=(
            "A light heather grey sweater-knit fleece full-zip jacket with a stand-up collar, a dark grey zipper "
            "and zipper tape, dark grey trim along the hem and cuffs, and zippered hand pockets. A small red shield "
            "with a white chevron and white crosses sits on the left chest, above 'BERKELEY' in small dark serif capitals."
        ),
        garment_type="fleece-jacket",
        primary_color="heather grey",
        secondary_colors=["dark grey", "red", "white"],
        printed_text=["BERKELEY"],
        graphics=["Berkeley College shield crest", "chevron", "crosses"],
        graphic_placement="left-chest",
        print_style="embroidered crest",
        affiliation="Berkeley College",
        brand="Port Authority",
        has_hood=False,
        has_zipper=True,
        sleeve_length="long",
        style_keywords=["collegiate", "minimal", "layering", "classic"],
    ),
    "timothy-dwight-college-crewneck": ProductAttributes(
        title="Heather Grey Timothy Dwight College Crewneck",
        description=(
            "A heather grey crewneck sweatshirt with ribbed collar, cuffs and waistband. A small crest on the left chest "
            "has a red top band with a white crescent moon above a white field with a red lion, and 'TIMOTHY DWIGHT' "
            "is printed beneath it in small black serif capitals."
        ),
        garment_type="crewneck",
        primary_color="heather grey",
        secondary_colors=["red", "white", "black"],
        printed_text=["TIMOTHY DWIGHT"],
        graphics=["Timothy Dwight College shield crest", "crescent moon", "lion"],
        graphic_placement="left-chest",
        print_style="small screen print",
        affiliation="Timothy Dwight College",
        brand="Port & Company",
        has_hood=False,
        has_zipper=False,
        sleeve_length="long",
        style_keywords=["minimal", "collegiate", "classic"],
    ),
}


def main() -> None:
    entries = load_cache()
    for product_id, attrs in MANUAL.items():
        path = PRODUCTS_DIR / f"{product_id}.jpg"
        entries[product_id] = CatalogueEntry.from_attributes(
            attrs, product_id=product_id, image_path=path.relative_to(HERE).as_posix(), source="manual",
        )
    save(entries)
    print(f"Added {len(MANUAL)} manual entries; catalogue now has {len(entries)} entries.")


if __name__ == "__main__":
    main()
