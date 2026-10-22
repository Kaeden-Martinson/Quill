"""Voices: ready-made styles, a custom voice from a few settings, or the writer's own samples.

A voice becomes a short plain-English description that both the editor and the drafter follow,
in the same shape as style.describe_voice() so the fine-tuned editor reads it the way it was
trained to.
"""
import style

# Each preset: what it sounds like, the traits the model follows, and an original sample.
PRESETS = {
    "plain": {
        "name": "Plain & clear",
        "blurb": "Short, direct sentences. Says the thing and moves on.",
        "traits": ["Average sentence is about 12 words, fairly even in length", "Uses contractions sometimes",
                   "Prefers common words over fancy ones", "One idea per sentence"],
        "sample": "The library closes at nine, so I study there until eight-thirty. It's quiet, the chairs are "
                  "bad, and nobody bothers me. That's the whole system. It works because I don't give myself "
                  "another option.",
    },
    "warm": {
        "name": "Warm & personal",
        "blurb": "Friendly and reflective, like telling a story to someone you like.",
        "traits": ["Average sentence is about 15 words, mixes short and long sentences", "Uses contractions freely",
                   "Writes in first person often", "Notices small, specific details"],
        "sample": "My grandmother kept a jar of buttons on the windowsill, and I used to sort them by color while "
                  "she cooked. I didn't know then that she was keeping me busy. I just knew the blue ones were "
                  "rarest, and that she always let me keep one.",
    },
    "academic": {
        "name": "Formal academic",
        "blurb": "Measured and precise, for papers and reports.",
        "traits": ["Average sentence is about 22 words, fairly even in length", "Rarely uses contractions; keep it that way",
                   "Mostly avoids first person", "Supports each claim before moving on"],
        "sample": "The Treaty of Versailles imposed reparations that the Weimar government could not realistically "
                  "pay. Historians continue to debate the extent of this burden; however, most agree that the "
                  "resulting resentment was exploited by political movements throughout the following decade.",
    },
    "punchy": {
        "name": "Punchy blog",
        "blurb": "Energetic and conversational, with short bursts and a little attitude.",
        "traits": ["Average sentence is about 9 words, mixes short and long sentences", "Uses contractions freely",
                   "Uses sentence fragments on purpose", "Uses rhetorical questions"],
        "sample": "Everyone says to wake up at five. Have you tried it? I have. Three days. By day four I was "
                  "napping in my car at lunch. So here's my take: sleep is a strategy too.",
    },
    "story": {
        "name": "Storyteller",
        "blurb": "Scene-first, with vivid moments and a clear arc.",
        "traits": ["Average sentence is about 16 words, mixes short and long sentences", "Uses contractions freely",
                   "Writes in first person often", "Opens with a concrete scene before explaining"],
        "sample": "The power went out halfway through my chemistry final. For a second nobody moved. Then thirty "
                  "phone flashlights clicked on at once, and Mr. Ortiz, without missing a beat, told us we had "
                  "exactly as long as the batteries lasted.",
    },
}

# Custom voice settings: name -> (allowed values, description per value)
CUSTOM_OPTIONS = {
    "formality": {"casual": "Casual and conversational", "balanced": "Neither stiff nor slangy",
                  "formal": "Formal and precise"},
    "sentences": {"short": "Average sentence is about 9 words, mixes short and long sentences",
                  "medium": "Average sentence is about 15 words, mixes short and long sentences",
                  "long": "Average sentence is about 22 words, fairly even in length"},
    "contractions": {"yes": "Uses contractions freely", "no": "Rarely uses contractions; keep it that way"},
    "person": {"first": "Writes in first person often", "third": "Mostly avoids first person"},
    "humor": {"none": None, "light": "Allows a little dry humor", "lots": "Funny and playful where it fits"},
}
CUSTOM_DEFAULTS = {"formality": "balanced", "sentences": "medium", "contractions": "yes", "person": "first", "humor": "none"}


def clean_custom(custom):
    """Keeps only known settings with allowed values; anything else falls back to the default."""
    custom = custom or {}
    return {k: custom.get(k) if custom.get(k) in CUSTOM_OPTIONS[k] else CUSTOM_DEFAULTS[k] for k in CUSTOM_OPTIONS}


def describe_custom(custom):
    custom = clean_custom(custom)
    lines = [CUSTOM_OPTIONS[k][v] for k, v in custom.items() if CUSTOM_OPTIONS[k][v]]
    return "\n".join(f"- {line}" for line in lines)


def describe_preset(preset_id):
    preset = PRESETS[preset_id]
    return "\n".join(f"- {t}" for t in preset["traits"])


def describe(profile, draft):
    """The voice description to use for one request, given a saved profile and the draft text."""
    mode = profile.get("voice_mode") or "auto"
    if mode == "preset" and profile.get("preset_id") in PRESETS:
        return describe_preset(profile["preset_id"])
    if mode == "custom":
        return describe_custom(profile.get("custom"))
    if mode == "samples" and profile.get("stats"):
        return style.describe_voice(profile["stats"])
    # auto, or a choice that's no longer usable: measure the draft itself.
    return style.describe_voice(style.profile_stats([draft])) if draft.strip() else style.describe_voice({})


def sample_for(profile):
    """A short example of the voice, to show the drafter how it sounds (presets and samples)."""
    mode = profile.get("voice_mode")
    if mode == "preset" and profile.get("preset_id") in PRESETS:
        return PRESETS[profile["preset_id"]]["sample"]
    if mode == "samples" and profile.get("samples"):
        return profile["samples"][0][:1200]
    return None
