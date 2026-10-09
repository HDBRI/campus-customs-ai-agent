"""Build the student and parent customer profiles from the CustomerProfile model and save them as JSON.

    python build_profiles.py   # writes profiles/profile_student.json and profiles/profile_parent.json

Defining them as model instances means an invalid field fails here, not later inside the agent.
"""

from __future__ import annotations

from pathlib import Path

from models import Budget, CustomerProfile, MediaHabits

HERE = Path(__file__).resolve().parent
PROFILES_DIR = HERE / "profiles"

STUDENT = CustomerProfile(
    name="Jordan Rivera",
    customer_type="student",
    pronouns="they/them",
    age=20,
    hometown="San Antonio, Texas",
    yale_connection="Yale College, Class of 2028, Saybrook College",
    life_stage="Sophomore; first-generation college student, settled in and wants to rep their college",
    preferred_garments=["hoodie", "crewneck", "t-shirt"],
    style_preferences=["streetwear", "oversized fits", "minimal logos over loud prints"],
    color_preferences=["navy", "black", "heather grey"],
    already_owns=["one free orientation t-shirt"],
    wishlist=["Saybrook gear they'd actually wear to college events", "a heavyweight hoodie for winter"],
    purchase_occasions=["The Game (Yale vs Harvard)", "Saybrook college events", "when friends buy matching gear"],
    budget=Budget(typical_min_usd=25, typical_max_usd=60, price_sensitivity="high",
                  notes="Tight student budget; waits for sales and student discounts"),
    shopping_channels=["phone, online", "rarely goes into campus stores"],
    decision_factors=["price or a discount", "looks good in streetwear fits", "friends are wearing it", "fast pickup or delivery"],
    media_habits=MediaHabits(
        platforms=["TikTok", "Instagram Reels", "YouTube Shorts"],
        content_formats=["short vertical video", "creator content", "memes"],
        attention_span="seconds",
        watches_with_sound=True,
    ),
    interests=["hip-hop and rap", "intramural basketball", "sneakers"],
    cultural_references=["popular hip-hop artists and music videos", "current TikTok trends", "NBA culture"],
    values=["authenticity", "humor", "feeling part of a group"],
    tone_that_works=["funny", "confident", "made by students, not a corporation"],
    turn_offs=["preppy or country-club marketing", "ads that feel corporate or try too hard",
               "not knowing where to buy or what it costs"],
    notes="Would share an ad in a group chat if it's funny or references something they love.",
)

PARENT = CustomerProfile(
    name="Maria Rivera",
    customer_type="parent",
    pronouns="she/her",
    age=49,
    hometown="San Antonio, Texas",
    yale_connection="Parent of Jordan Rivera, Yale College Class of 2028 (Saybrook College)",
    life_stage="Parent of a sophomore; first in the family to have a child at Yale",
    preferred_garments=["crewneck", "quarter-zip", "t-shirt"],
    style_preferences=["classic", "clean crest designs", "good-quality cotton"],
    color_preferences=["navy", "heather grey", "white"],
    already_owns=["a Yale Mom mug", "a car decal from move-in weekend"],
    wishlist=["a 'Yale Mom' crewneck to wear back home", "Yale gifts for Jordan's grandparents"],
    purchase_occasions=["Family Weekend", "holidays and birthdays (gifts)", "The Game", "commencement (planning ahead)"],
    budget=Budget(typical_min_usd=40, typical_max_usd=100, price_sensitivity="medium",
                  notes="Careful day to day, but will spend more on gifts and pride items"),
    shopping_channels=["laptop or phone, online", "in person during campus visits"],
    decision_factors=["quality and fit", "clear price and shipping time", "family-pride designs (Mom, Dad, Grandma)",
                      "easy returns"],
    media_habits=MediaHabits(
        platforms=["Facebook", "Instagram feed", "email newsletters", "Yale parents Facebook group"],
        content_formats=["photos", "short video under 30 seconds", "email with a clear offer"],
        attention_span="under a minute",
        watches_with_sound=False,
    ),
    interests=["her kids' achievements", "cooking", "Spurs basketball", "church community"],
    cultural_references=["90s R&B", "Selena", "local Texas news"],
    values=["family pride", "hard work", "education as opportunity"],
    tone_that_works=["warm", "proud", "clear and straightforward"],
    turn_offs=["ads that feel aimed at teenagers", "hard-to-read text or no captions", "unclear pricing or shipping"],
    notes="Posts proud-parent photos on Facebook; a family-themed ad she can share with relatives would land well.",
)


def main() -> None:
    PROFILES_DIR.mkdir(exist_ok=True)
    for filename, profile in [("profile_student.json", STUDENT), ("profile_parent.json", PARENT)]:
        path = PROFILES_DIR / filename
        path.write_text(profile.model_dump_json(indent=2) + "\n", encoding="utf-8")
        CustomerProfile.model_validate_json(path.read_text(encoding="utf-8"))  # round-trip check
        print(f"Wrote {path.relative_to(HERE).as_posix()} ({profile.name}, {profile.customer_type})")


if __name__ == "__main__":
    main()
