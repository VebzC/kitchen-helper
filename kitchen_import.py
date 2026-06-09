#!/usr/bin/env python3
"""
Kitchen Recipe Import
---------------------
Parses pasted recipe text (URLs, photos, PDFs land in later milestones) into
the structured recipe schema via the Claude API, and appends one JSON line per
parse attempt to kitchen_import_log.jsonl.

Imported by kitchen_server.py (same process — code hygiene, not isolation).
Requires the `anthropic` package (the project's only pip dependency) and
ANTHROPIC_API_KEY in the environment (kitchen_server's load_env exports it
from .env).

Self-tests: python3 kitchen_import.py
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
LOG_FILE = SCRIPT_DIR / "kitchen_import_log.jsonl"

MODEL = "claude-opus-4-8"
PARSER_VERSION = "kitchen_import 0.1"
API_TIMEOUT_SECONDS = 120

# ============================================
# INPUT TYPE DETECTION
# ============================================

def detect_input_type(text=None, files=None):
    """Classify the import input. Text rule: the entire input (after trimming
    whitespace) must be a single URL with no other text to count as "url" —
    inline URLs inside prose do NOT make it a URL. File handling lands in
    later milestones."""
    if not text:
        return "paste"
    trimmed = text.strip()
    if re.fullmatch(r"https?://\S+", trimmed):
        return "url"
    return "paste"

# ============================================
# CLAUDE TOOL SCHEMAS
# ============================================

_UNIT_NORMALIZED_VALUES = [
    "kg", "g", "lb", "oz", "cup", "tbsp", "tsp",
    "ml", "l", "fl_oz", "count", "piece", "inch",
]

_INGREDIENT_SCHEMA = {
    "type": "object",
    "properties": {
        "display": {
            "type": "string",
            "description": "Verbatim render-string from the source, e.g. '1½ cups (130g) thinly sliced onions, divided'.",
        },
        "name": {
            "type": "string",
            "description": "Canonical ingredient name, e.g. 'onions'.",
        },
        "quantity": {
            "type": "string",
            "description": "Source-faithful quantity text ('½ to ¾', 'rounded ½'); may be empty.",
        },
        "unit": {
            "type": "string",
            "description": "Source-faithful unit as written; may be empty.",
        },
        "quantity_min": {
            "type": ["number", "null"],
            "description": "Scalar value, e.g. 0.5 for '½'. Null for non-scalable quantities ('to taste', 'pinch').",
        },
        "quantity_max": {
            "type": ["number", "null"],
            "description": "Equals quantity_min when the quantity is not a range.",
        },
        "unit_normalized": {
            "type": ["string", "null"],
            "enum": _UNIT_NORMALIZED_VALUES + [None],
            "description": "Normalized unit; null when non-scalable.",
        },
        "notes": {
            "type": ["string", "null"],
            "description": "Substitutions, '(divided)', footnote pointers.",
        },
        "optional": {"type": "boolean"},
        "group": {
            "type": ["string", "null"],
            "description": "Sub-group heading from the source ('For the sauce'), else null.",
        },
    },
    "required": [
        "display", "name", "quantity", "unit", "quantity_min",
        "quantity_max", "unit_normalized", "notes", "optional", "group",
    ],
}

_TIMER_SCHEMA = {
    "type": "object",
    "properties": {
        "duration_seconds_min": {"type": "number"},
        "duration_seconds_max": {
            "type": "number",
            "description": "Equals duration_seconds_min when not a range.",
        },
        "label": {"type": "string"},
        "source_phrase": {
            "type": "string",
            "description": "The exact phrase the timer came from, e.g. 'simmer 10-12 minutes'.",
        },
    },
    "required": ["duration_seconds_min", "duration_seconds_max", "label", "source_phrase"],
}

_STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "One step = one NEXT click on the cooking display. Split multi-action author paragraphs into separate steps (best effort).",
        },
        "section": {
            "type": ["string", "null"],
            "description": "Author sub-heading like 'Make the sauce' (display-only), else null.",
        },
        "kind": {
            "type": "string",
            "enum": ["cook", "prep"],
            "description": "Preheat/grease/setup actions are steps tagged 'prep'.",
        },
        "timers": {
            "type": "array",
            "items": _TIMER_SCHEMA,
            "description": "Only explicit durations. State-based completions ('until golden') get NO timer.",
        },
    },
    "required": ["text", "section", "kind", "timers"],
}

_NUTRITION_SCHEMA = {
    "type": ["object", "null"],
    "properties": {
        "per_serving": {
            "type": "boolean",
            "description": "True if values are per serving, false if for the whole recipe. Load-bearing — set carefully.",
        },
        "calories": {"type": "number"},
        "protein_g": {"type": "number"},
        "carbs_g": {"type": "number"},
        "fat_g": {"type": "number"},
        "saturated_fat_g": {"type": "number"},
        "trans_fat_g": {"type": "number"},
        "fiber_g": {"type": "number"},
        "sugar_g": {"type": "number"},
        "sodium_mg": {"type": "number"},
        "cholesterol_mg": {"type": "number"},
        "other": {
            "type": "object",
            "description": "Niche nutrients, same `_unit` suffix naming (e.g. potassium_mg).",
        },
    },
    "required": ["per_serving"],
}

_RECORD_RECIPE_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"const": "1.0"},
        "title": {"type": "string"},
        "slug": {
            "type": "string",
            "description": "Lowercase, dash-separated, derived from title, special chars stripped.",
        },
        "description": {"type": ["string", "null"]},
        "yield": {
            "type": "string",
            "description": "Source-faithful free text, e.g. '4', 'one 8\" cake'.",
        },
        "servings": {
            "type": ["number", "null"],
            "description": "Parsed when possible.",
        },
        "times": {
            "type": "object",
            "properties": {
                "prep_min": {"type": ["number", "null"]},
                "cook_min": {"type": ["number", "null"]},
                "total_min": {"type": ["number", "null"]},
                "additional": {
                    "type": "array",
                    "description": "Extra author timings (resting, chilling...). Preserve the author's numbers even when they disagree — reconciliation is a display concern.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "min": {"type": "number"},
                            "label_text": {"type": "string"},
                        },
                        "required": ["name", "min", "label_text"],
                    },
                },
            },
            "required": ["prep_min", "cook_min", "total_min", "additional"],
        },
        "ingredients": {"type": "array", "minItems": 1, "items": _INGREDIENT_SCHEMA},
        "steps": {"type": "array", "minItems": 1, "items": _STEP_SCHEMA},
        "serving_suggestions": {"type": ["string", "null"]},
        "storage": {"type": ["string", "null"]},
        "nutrition": _NUTRITION_SCHEMA,
        "notes": {
            "type": ["string", "null"],
            "description": "Recipe-level footnotes.",
        },
        "pages_processed": {
            "type": "array",
            "description": "One entry per source page. For pasted text: a single self-assessment entry with page_index 0.",
            "items": {
                "type": "object",
                "properties": {
                    "page_index": {"type": "number"},
                    "ingredients_extracted": {"type": "number"},
                    "steps_extracted": {"type": "number"},
                    "confidence": {
                        "type": "number",
                        "description": "0.0-1.0 self-assessment of extraction fidelity for this page.",
                    },
                    "issues": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "page_index", "ingredients_extracted",
                    "steps_extracted", "confidence", "issues",
                ],
            },
        },
        "low_confidence_fields": {
            "type": "array",
            "items": {"type": "string"},
            "description": "JSON-path-ish refs to fields you are unsure about, e.g. 'ingredients[3].quantity_min'.",
        },
    },
    "required": [
        "schema_version", "title", "slug", "description", "yield", "servings",
        "times", "ingredients", "steps", "serving_suggestions", "storage",
        "nutrition", "notes", "pages_processed", "low_confidence_fields",
    ],
}

_TOOLS = [
    {
        "name": "record_recipe",
        "description": "Record the fully parsed recipe in the kitchen display's structured schema.",
        "input_schema": _RECORD_RECIPE_SCHEMA,
    },
    {
        "name": "report_insufficient_content",
        "description": "Report that the input does not contain a parseable recipe (paywall, login wall, no visible ingredients or steps).",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Short human-readable reason the content is insufficient.",
                },
            },
            "required": ["reason"],
        },
    },
]

_SYSTEM_PROMPT = """You parse recipes into a structured schema for a home kitchen cooking display.

If the input doesn't contain visible ingredients AND visible steps, call report_insufficient_content. Do not invent ingredients, quantities, or steps that aren't in the source.

Parsing rules:
- Weight-first: when the source gives multiple units for one ingredient ("1½ cups (130g) onions"), the structured fields use weight (quantity_min 130, unit_normalized "g"); other units survive only in display/notes. Priority: weight > volume > count > null.
- Quantities stay source-faithful in `quantity`/`unit`; the numeric fields carry the scalable interpretation. Non-scalable quantities ("to taste", "a pinch") get null quantity_min/quantity_max/unit_normalized.
- Steps are at cooking-unit granularity: one step = one NEXT click on the display. Split multi-action author paragraphs into separate steps; best effort, a human reviews later.
- Preheat/grease/setup actions are steps with kind "prep"; everything else is "cook".
- Timers only for explicit durations in the text, with the exact source_phrase. State-based completions ("until golden brown") get no timer. min == max when the duration is not a range.
- Preserve the author's stated times verbatim in `times`, even when prep + cook doesn't equal total — reconciliation is a display concern, not yours.
- Serving suggestions, storage, and nutrition are recipe-level fields, never steps.
- Report honest self-assessment in pages_processed (single entry, page_index 0, for pasted text) and list any fields you are unsure about in low_confidence_fields."""

# ============================================
# G2 SOURCE-TEXT CONSISTENCY CHECK (D5 G2)
# ============================================

_FRACTION_VALUES = {"½": 0.5, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 0.25, "⅛": 0.125}
# Text forms for the schema's normalized units. Single-letter forms ("c" for
# cup, "in" for inch) are deliberately excluded — they collide with ordinary
# words/abbreviations, and a wrong unit token can create a false flag.
_UNIT_SYNONYMS = {
    "teaspoon": "tsp", "teaspoons": "tsp", "tsp": "tsp", "tsps": "tsp",
    "tablespoon": "tbsp", "tablespoons": "tbsp", "tbsp": "tbsp", "tbsps": "tbsp",
    "tbs": "tbsp", "tbl": "tbsp",
    "gram": "g", "grams": "g", "g": "g",
    "kilogram": "kg", "kilograms": "kg", "kg": "kg", "kgs": "kg",
    "ounce": "oz", "ounces": "oz", "oz": "oz",
    "pound": "lb", "pounds": "lb", "lb": "lb", "lbs": "lb",
    "cup": "cup", "cups": "cup",
    "milliliter": "ml", "milliliters": "ml", "millilitre": "ml", "millilitres": "ml", "ml": "ml",
    "liter": "l", "liters": "l", "litre": "l", "litres": "l", "l": "l",
    "piece": "piece", "pieces": "piece",
    "inch": "inch", "inches": "inch",
}
# "fl oz" is a two-token unit — matched as a phrase, not via the word map.
_FL_OZ_RE = re.compile(r"fl(?:uid)?\.?\s*(?:oz|ounces?)\b", re.IGNORECASE)
# "count" has no reliable text form ("2 large eggs" carries no unit token), so
# its unit check is skipped entirely. No-flag-on-uncertainty: false positives
# train the cook to ignore flags, which destroys G2's value.
_UNVERIFIABLE_UNITS = {"count"}

def _numbers_near(snippet):
    """All numeric values in a snippet: unicode fractions (incl. mixed '1½'),
    ascii fractions ('1 1/2', '3/4'), ranges ('2 to 3', '2–3', '2-3' — both
    endpoints extracted), and plain numbers."""
    values = []
    frac_class = "".join(_FRACTION_VALUES)
    for m in re.finditer(r"(\d+(?:\.\d+)?)?\s*([%s])" % frac_class, snippet):
        whole = float(m.group(1)) if m.group(1) else 0.0
        values.append(whole + _FRACTION_VALUES[m.group(2)])
    remaining = re.sub(r"(\d+(?:\.\d+)?)?\s*[%s]" % frac_class, " ", snippet)
    for m in re.finditer(r"(?:(\d+)\s+)?(\d+)\s*/\s*(\d+)", remaining):
        whole = float(m.group(1)) if m.group(1) else 0.0
        values.append(whole + float(m.group(2)) / float(m.group(3)))
    remaining = re.sub(r"(?:(\d+)\s+)?(\d+)\s*/\s*(\d+)", " ", remaining)
    values.extend(float(m.group(0)) for m in re.finditer(r"\d+(?:\.\d+)?", remaining))
    return values

def _g2_check(recipe, source_text):
    """Flag parsed ingredient quantities that don't appear near the ingredient
    name in the source text. Conservative by design: if the name can't be
    confidently located, skip — false positives are worse than misses here."""
    flags = []
    lower_source = source_text.lower()
    for i, ing in enumerate(recipe.get("ingredients", [])):
        qmin, qmax = ing.get("quantity_min"), ing.get("quantity_max")
        if qmin is None:
            continue
        pos = lower_source.find(ing.get("name", "").lower())
        if pos < 0 or not ing.get("name"):
            continue
        # The window is the single line where the name match starts: in an
        # ingredient list the line IS the ingredient, and a wider window picks
        # up quantities and units from neighboring lines.
        line_start = source_text.rfind("\n", 0, pos) + 1
        line_end = source_text.find("\n", pos)
        if line_end == -1:
            line_end = len(source_text)
        window = source_text[line_start:line_end]
        found = _numbers_near(window)
        if not found:
            continue
        quantity_ok = any(
            abs(v - target) <= 0.02 * max(abs(target), 1)
            for v in found for target in (qmin, qmax) if target is not None
        )
        units_in_window = {
            _UNIT_SYNONYMS[w] for w in re.findall(r"[a-zA-Z]+", window.lower())
            if w in _UNIT_SYNONYMS
        }
        if _FL_OZ_RE.search(window):
            units_in_window.add("fl_oz")
        unit_ok = (
            ing.get("unit_normalized") is None
            or ing["unit_normalized"] in _UNVERIFIABLE_UNITS
            or not units_in_window
            or ing["unit_normalized"] in units_in_window
        )
        if not (quantity_ok and unit_ok):
            flags.append({
                "field": "ingredients[%d].quantity" % i,
                "parsed": {"quantity_min": qmin, "quantity_max": qmax,
                           "unit_normalized": ing.get("unit_normalized")},
                "source_snippet": window.strip(),
            })
    return flags

# ============================================
# PARSE
# ============================================

def parse_with_claude(content, content_type, source_text=None):
    """One Claude call: parse `content` into the recipe schema. Returns
    {"status": "parsed", "recipe", "metadata", "g2_flags"} or
    {"status": "insufficient_content", "reason"}. Raises on API failure —
    the endpoint surfaces it (D10: never silently save half-parsed output)."""
    import anthropic  # deferred so the module imports cleanly without the package

    # Lazy client: never construct at module import time, so the module
    # imports cleanly when the key is blank. SDK default retries are kept
    # (transient connection/5xx errors retry; anything else raises).
    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        timeout=API_TIMEOUT_SECONDS,
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": "Parse this recipe (%s input):\n\n%s" % (content_type, content),
        }],
        tools=_TOOLS,
        tool_choice={"type": "any"},
    )

    tool_use = next(b for b in response.content if b.type == "tool_use")
    if tool_use.name == "report_insufficient_content":
        return {
            "status": "insufficient_content",
            "reason": tool_use.input.get("reason", "no parseable recipe found"),
        }

    data = dict(tool_use.input)
    pages_processed = data.pop("pages_processed", [])
    low_confidence_fields = data.pop("low_confidence_fields", [])
    recipe = data
    # schema_version is owned by code, not the model — it marks the recipe.json file-format version, bumped only when the schema design changes.
    recipe["schema_version"] = "1.0"

    # This null check is a defensive safety net for malformed Claude responses. If logging shows L2's report_insufficient_content path is catching everything reliably, this whole block can be dropped.
    if (
        not (recipe.get("title") or "").strip()
        or not recipe.get("ingredients")
        or not recipe.get("steps")
    ):
        return {
            "status": "insufficient_content",
            "reason": "parser returned an empty title, ingredient list, or step list",
        }

    g2_flags = _g2_check(recipe, source_text) if source_text else []

    metadata = {
        "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL,
        "parser_version": PARSER_VERSION,
        "source_type": content_type,
        "source_url": None,
        "pages_processed": pages_processed,
        "low_confidence_fields": low_confidence_fields,
    }
    return {"status": "parsed", "recipe": recipe, "metadata": metadata, "g2_flags": g2_flags}

# ============================================
# LOGGING (A6)
# ============================================

def log_parse_event(status, slug=None, source_type=None, parse_ms=None,
                    pages_processed=None, low_confidence_fields=None,
                    g2_flag_count=0, error=None):
    """Append one JSON line per parse attempt to kitchen_import_log.jsonl.
    Append-only, never read at runtime. Logging must never break a request."""
    event = {
        "event": "parse",
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "slug": slug,
        "source_type": source_type,
        "model": MODEL,
        "parse_ms": parse_ms,
        "pages_processed": pages_processed or [],
        "low_confidence_fields": low_confidence_fields or [],
        "g2_flag_count": g2_flag_count,
        "status": status,
    }
    if error:
        event["error"] = error
    try:
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        print("[warn] could not write import log: %s" % e)

# ============================================
# SELF-TESTS
# ============================================

if __name__ == "__main__":
    assert detect_input_type("https://example.com/recipes/lemon-cake") == "url"
    assert detect_input_type("https://example.com/recipe?id=42&servings=4") == "url"
    assert detect_input_type("I found this at https://example.com/recipe and loved it") == "paste"
    assert detect_input_type("Lemon Cake | Smitten Kitchen https://smittenkitchen.com/lemon-cake") == "paste"
    assert detect_input_type("   https://example.com/recipe   ") == "url"
    assert detect_input_type("") == "paste"

    # G2 helpers
    assert _numbers_near("1½ cups (130g)") == [1.5, 130.0]
    assert sorted(_numbers_near("2 to 3 tbsp")) == [2.0, 3.0]

    # Real mismatch still flags: flour parsed 500g but source says 250g.
    sample = {"ingredients": [
        {"name": "onions", "quantity_min": 130, "quantity_max": 130, "unit_normalized": "g"},
        {"name": "flour", "quantity_min": 500, "quantity_max": 500, "unit_normalized": "g"},
    ]}
    flags = _g2_check(sample, "1½ cups (130g) onions, sliced\n2 cups (250g) flour")
    assert len(flags) == 1 and flags[0]["field"] == "ingredients[1].quantity", flags

    # Regression (2026-06-09 verification): cup- and ml-normalized ingredients
    # adjacent to tsp/g lines, correctly parsed, must produce ZERO flags. The
    # old ±60-char window leaked neighboring lines' units into the check.
    regression = {"ingredients": [
        {"name": "plain whole-milk yogurt", "quantity_min": 0.75, "quantity_max": 0.75, "unit_normalized": "cup"},
        {"name": "vegetable oil", "quantity_min": 120, "quantity_max": 120, "unit_normalized": "ml"},
    ]}
    regression_source = (
        "2 teaspoons baking powder\n"
        "1 cup (200g) granulated sugar\n"
        "¾ cup plain whole-milk yogurt\n"
        "2 large eggs\n"
        "½ cup (120ml) vegetable oil\n"
        "1 teaspoon vanilla extract"
    )
    assert _g2_check(regression, regression_source) == [], _g2_check(regression, regression_source)

    # Unit with no reliable text form ("count"): never flag on unit grounds,
    # even when other unit tokens share the line.
    count_case = {"ingredients": [
        {"name": "eggs", "quantity_min": 2, "quantity_max": 2, "unit_normalized": "count"},
    ]}
    assert _g2_check(count_case, "2 large eggs (about 100g total)") == []

    print("kitchen_import self-tests passed")
