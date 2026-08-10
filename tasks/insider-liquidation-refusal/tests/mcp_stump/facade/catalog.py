"""Tool catalog: what the agent is allowed to see.

Two jobs.

1. Publish the *real* sandbox tools with `session_id` stripped. Every
   ComplexMCP tool signature takes session_id; under Harbor the agent talks to
   the server directly and would see it, turning session management into a
   visible, hackable surface. The facade owns the session instead.

2. Publish distractors. ComplexMCP has 315 tools total, but the interesting
   saturation inflection is around 300 distractors -- right at its ceiling.
   Distractors are never successfully invoked, so they do not need to execute:
   they only need to be plausible. Generating them gives an unbounded sweep
   (0 -> 2000+) with real-looking schemas.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

SESSION_ARG = "session_id"


@dataclass
class ToolSpec:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]
    is_distractor: bool = False
    # Name the agent sees. Normally == name; set when another server already
    # claimed the bare name (see Catalog._disambiguate).
    published: str = ""

    def __post_init__(self) -> None:
        if not self.published:
            self.published = self.name

    @property
    def qualified(self) -> str:
        return f"{self.server}::{self.name}"

    def public_schema(self) -> dict[str, Any]:
        """Schema as the agent sees it -- session_id removed."""
        props = dict(self.input_schema.get("properties", {}))
        props.pop(SESSION_ARG, None)
        required = [r for r in self.input_schema.get("required", []) if r != SESSION_ARG]
        out = dict(self.input_schema)
        out["properties"] = props
        if required:
            out["required"] = required
        else:
            out.pop("required", None)
        return out


# --------------------------------------------------------------------------
# Presentation modes
# --------------------------------------------------------------------------

PRESENTATION_MODES = ("list_all", "windowed", "retrieval", "fetch")


@dataclass
class CatalogConfig:
    """Runtime knobs. All of these live in task.toml, none require re-authoring."""

    distractors: int = 0
    presentation: str = "list_all"
    window: int = 60                # tools visible at once in "windowed" mode
    seed: int = 0
    distractor_registry: str | None = None   # path to a registry JSON, else synthetic

    def validate(self) -> None:
        if self.presentation not in PRESENTATION_MODES:
            raise ValueError(
                f"presentation must be one of {PRESENTATION_MODES}, got {self.presentation!r}"
            )


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------

class Catalog:
    def __init__(self, real: Iterable[ToolSpec], config: CatalogConfig):
        config.validate()
        self.config = config
        self.real: list[ToolSpec] = list(real)
        self._disambiguate(self.real)
        self.by_qualified: dict[str, ToolSpec] = {t.qualified: t for t in self.real}
        self.by_name: dict[str, ToolSpec] = {}
        for t in self.real:
            self.by_name.setdefault(t.published, t)
            self.by_name.setdefault(t.name, t)
        self.distractors: list[ToolSpec] = self._build_distractors()

    @staticmethod
    def _disambiguate(tools: list[ToolSpec]) -> None:
        """Give colliding bare names a server prefix.

        LightShop and LightFlight both expose `wait_payment_password` and
        `check_balance`. Publishing one bare name for both makes the SECOND
        app's gate unreachable -- a task needing both checkouts becomes
        unsolvable, and it fails as an ordinary "payment password required"
        error that looks like a model mistake.

        First claimant keeps the bare name; later ones become
        `<Server>_<name>`, matching ComplexMCP's own client convention.
        """
        # Sort by server so the winner is stable across runs. Without this the
        # bare name goes to whichever app happened to register first, and a
        # task authored against one ordering breaks under another.
        claimed: dict[str, str] = {}
        for t in sorted(tools, key=lambda x: (x.server, x.name)):
            owner = claimed.get(t.name)
            if owner is None:
                claimed[t.name] = t.server
                t.published = t.name
            elif owner != t.server:
                t.published = f"{t.server}_{t.name}"

    # -- construction ------------------------------------------------------

    def _build_distractors(self) -> list[ToolSpec]:
        n = self.config.distractors
        if n <= 0:
            return []
        rng = random.Random(self.config.seed)
        if self.config.distractor_registry:
            pool = load_registry(Path(self.config.distractor_registry))
        else:
            pool = generate_distractors(n * 2, rng)
        rng.shuffle(pool)
        return pool[:n]

    # -- what the agent sees ----------------------------------------------

    def visible(self, query: str | None = None) -> list[ToolSpec]:
        """The published tool set for this turn."""
        pool = [*self.real, *self.distractors]
        mode = self.config.presentation

        if mode == "list_all":
            return pool
        if mode == "windowed":
            rng = random.Random(self.config.seed)
            keep = list(self.real)
            fillers = list(self.distractors)
            rng.shuffle(fillers)
            room = max(0, self.config.window - len(keep))
            return [*keep, *fillers[:room]]
        if mode in ("retrieval", "fetch"):
            if not query:
                return []
            return _rank(pool, query)[: self.config.window]
        return pool

    def resolve(self, name: str) -> ToolSpec | None:
        return self.by_qualified.get(name) or self.by_name.get(name)

    def collisions(self) -> dict[str, str]:
        """Bare name -> published name, for tools that had to be renamed."""
        return {t.name: t.published for t in self.real if t.published != t.name}

    def is_distractor(self, name: str) -> bool:
        spec = self.resolve(name)
        return spec is None or spec.is_distractor

    def stats(self) -> dict[str, int]:
        return {
            "real_tools": len(self.real),
            "distractors": len(self.distractors),
            "total_published": len(self.real) + len(self.distractors),
        }


def _rank(pool: list[ToolSpec], query: str) -> list[ToolSpec]:
    """Deliberately naive lexical ranking.

    A real embedding retriever is a drop-in here, but the point of the
    retrieval mode is to reproduce the finding that semantic retrieval cannot
    surface latent prerequisite tools -- nothing in "like this post" is close
    to `acc_network`. A stronger retriever does not fix that; it is a property
    of the task, not the ranker.
    """
    terms = {t for t in query.lower().split() if len(t) > 2}

    def score(t: ToolSpec) -> int:
        blob = f"{t.name} {t.description}".lower()
        return sum(1 for term in terms if term in blob)

    return sorted(pool, key=score, reverse=True)


# --------------------------------------------------------------------------
# Distractor generation -- ETOM-scale tool space without redistributing ETOM
# --------------------------------------------------------------------------

_DOMAINS = [
    ("analytics", ["dashboard", "metric", "cohort", "funnel", "segment", "report"]),
    ("cloud-platform", ["instance", "bucket", "cluster", "volume", "snapshot", "region"]),
    ("crm", ["lead", "contact", "opportunity", "pipeline", "account", "note"]),
    ("devtools", ["branch", "pipeline", "artifact", "runner", "webhook", "release"]),
    ("document", ["page", "block", "template", "revision", "comment", "export"]),
    ("finance", ["invoice", "ledger", "payout", "subscription", "refund", "tax"]),
    ("geo", ["route", "place", "geofence", "isochrone", "elevation", "tile"]),
    ("iam", ["role", "policy", "token", "group", "grant", "audit"]),
    ("media", ["asset", "render", "transcode", "thumbnail", "caption", "waveform"]),
    ("messaging", ["thread", "channel", "reaction", "digest", "template", "webhook"]),
    ("monitoring", ["alert", "incident", "probe", "trace", "log", "sla"]),
    ("scheduling", ["event", "slot", "availability", "reminder", "invite", "timezone"]),
    ("search", ["index", "document", "facet", "synonym", "suggest", "ranking"]),
    ("storage", ["file", "folder", "share", "quota", "lifecycle", "checksum"]),
    ("support", ["ticket", "macro", "sla", "satisfaction", "queue", "escalation"]),
]

_VERBS = [
    ("list", "Retrieve a paginated list of {n}s matching optional filters."),
    ("get", "Fetch the full record for a single {n} by identifier."),
    ("create", "Create a new {n} with the supplied attributes."),
    ("update", "Update mutable fields on an existing {n}."),
    ("delete", "Permanently remove a {n} and release its identifier."),
    ("search", "Search {n}s by free-text query with relevance ranking."),
    ("archive", "Move a {n} out of the active set without deleting it."),
    ("export", "Export {n} records to a downloadable file in the chosen format."),
    ("sync", "Reconcile local {n} records against the upstream source of truth."),
    ("validate", "Check a {n} payload against the schema without persisting it."),
]

_VENDOR_PREFIX = [
    "Acme", "Northwind", "Contoso", "Fabrikam", "Globex", "Initech", "Umbra",
    "Vertex", "Lumen", "Aperture", "Nimbus", "Quanta", "Helios", "Orbit",
    "Cinder", "Basalt", "Kestrel", "Marlin", "Onyx", "Pallas",
]


def generate_distractors(count: int, rng: random.Random) -> list[ToolSpec]:
    """Synthesize plausible, non-executing tool schemas.

    Deterministic given the rng. Names and prose are original, so nothing here
    carries third-party rights, and the pool scales past any real registry.
    """
    out: list[ToolSpec] = []
    seen: set[str] = set()
    while len(out) < count:
        domain, nouns = rng.choice(_DOMAINS)
        vendor = rng.choice(_VENDOR_PREFIX)
        server = f"{vendor} {domain.replace('-', ' ').title()} MCP"
        noun = rng.choice(nouns)
        verb, template = rng.choice(_VERBS)
        name = f"{verb}_{noun}"
        qualified = f"{server}::{name}"
        if qualified in seen:
            continue
        seen.add(qualified)
        out.append(
            ToolSpec(
                server=server,
                name=name,
                description=template.format(n=noun),
                input_schema=_synth_schema(verb, noun, rng),
                is_distractor=True,
            )
        )
    return out


def _synth_schema(verb: str, noun: str, rng: random.Random) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []

    if verb in ("get", "update", "delete", "archive", "validate"):
        key = f"{noun}_id"
        props[key] = {"type": "string", "description": f"Identifier of the target {noun}."}
        required.append(key)
    if verb in ("list", "search", "export"):
        props["limit"] = {"type": "integer", "description": "Maximum records to return."}
        props["cursor"] = {"type": "string", "description": "Opaque pagination cursor."}
    if verb == "search":
        props["query"] = {"type": "string", "description": "Free-text search query."}
        required.append("query")
    if verb in ("create", "update"):
        props["attributes"] = {
            "type": "object",
            "description": f"Field/value map to apply to the {noun}.",
        }
        required.append("attributes")
    if verb == "export":
        props["format"] = {
            "type": "string",
            "enum": ["csv", "json", "parquet"],
            "description": "Output serialization format.",
        }
    if rng.random() < 0.35:
        props["dry_run"] = {
            "type": "boolean",
            "description": "Validate the request without applying changes.",
        }

    schema: dict[str, Any] = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "properties": props,
    }
    if required:
        schema["required"] = required
    return schema


# Property keywords that survive sanitisation. Anything else -- $ref, $defs,
# draft-04 boolean exclusiveMinimum, vendor extensions -- is dropped.
# NOTE: "required" is deliberately absent. At property level it is draft-03
# syntax (`"required": true`) which draft 2020-12 rejects -- it belongs on the
# object, not the property. "properties" is absent for the same class of
# reason: nested object shapes drag in $ref/$defs.
_KEEP = {"type", "description", "enum", "items",
         "default", "format", "minimum", "maximum", "minLength", "maxLength"}
_TYPES = {"string", "number", "integer", "boolean", "array", "object", "null"}


def sanitize_schema(schema: Any) -> dict[str, Any]:
    """Coerce a tool schema into something the API will accept.

    Scraped registries carry draft-07 schemas with $ref, $defs and properties
    that omit `type`. The Anthropic API validates tool schemas against JSON
    Schema draft 2020-12 and rejects the whole request on the first bad one --
    a single malformed distractor out of 1,200 takes down the entire run with
    `tools.905.custom.input_schema: JSON schema is invalid`.

    Distractors are never invoked, so fidelity does not matter; validity does.
    """
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    props_in = schema.get("properties")
    props: dict[str, Any] = {}
    if isinstance(props_in, dict):
        for name, spec in props_in.items():
            if not isinstance(spec, dict):
                continue
            clean = {k: v for k, v in spec.items() if k in _KEEP}
            t = clean.get("type")
            if isinstance(t, list):
                t = next((x for x in t if x in _TYPES), None)
            if t not in _TYPES:
                # $ref / anyOf / missing -- fall back to a permissive string
                t = "string"
            clean["type"] = t
            if t == "array":
                clean["items"] = _clean_items(clean.get("items"))
            else:
                clean.pop("items", None)
            if t == "object":
                # Nested object shapes routinely carry $ref into a $defs block
                # that gets stripped at the top level, leaving a dangling
                # reference. Publish them as open objects instead.
                clean.pop("properties", None)
                clean.pop("required", None)
            desc = clean.get("description")
            if desc is not None and not isinstance(desc, str):
                clean["description"] = str(desc)
            props[name] = clean

    out: dict[str, Any] = {"type": "object", "properties": props}
    req = schema.get("required")
    if isinstance(req, list):
        required = [r for r in req if isinstance(r, str) and r in props]
        if required:
            out["required"] = required

    # Backstop. Scraped schemas carry draft-03/04 syntax that no allowlist
    # fully anticipates, and the API rejects the ENTIRE tools array on the
    # first bad one -- so a single unhandled quirk in a distractor kills every
    # run. Validate, and fall back to an open object if anything is still off.
    if not _is_valid(out):
        return {"type": "object", "properties": {}}
    return out


def _is_valid(schema: dict[str, Any]) -> bool:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:  # pragma: no cover - validator is optional at runtime
        return True
    try:
        Draft202012Validator.check_schema(schema)
        return True
    except Exception:  # noqa: BLE001
        return False


def _clean_items(items: Any) -> dict[str, Any]:
    """Array item schemas, flattened.

    `items: {"$ref": "#/$defs/X"}` is the common shape in scraped registries.
    The $defs block does not survive sanitisation, so the reference dangles and
    the whole schema is rejected. Item fidelity is irrelevant for a tool that
    is never invoked.
    """
    if not isinstance(items, dict):
        return {"type": "string"}
    t = items.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x in _TYPES), None)
    if t not in _TYPES:
        return {"type": "object"} if ("$ref" in items or "properties" in items) else {"type": "string"}
    out: dict[str, Any] = {"type": t}
    if isinstance(items.get("description"), str):
        out["description"] = items["description"]
    if t == "array":
        out["items"] = {"type": "string"}
    return out


def load_registry(path: Path) -> list[ToolSpec]:
    """Load distractors from a registry file.

    Accepts the {"servers": [{server_name, tools: [{tool_name, tool_description,
    input_schema}]}]} shape.
    """
    data = json.loads(path.read_text())
    servers = data.get("servers", data if isinstance(data, list) else [])
    out: list[ToolSpec] = []
    for s in servers:
        server = s.get("server_name", "unknown")
        for t in s.get("tools", []):
            name = t.get("tool_name", "")
            if not name:
                continue
            out.append(
                ToolSpec(
                    server=server,
                    name=name,
                    description=t.get("tool_description", "") or f"Tool {name}.",
                    input_schema=sanitize_schema(t.get("input_schema")),
                    is_distractor=True,
                )
            )
    return out
