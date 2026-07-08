"""Audit a chart's type mapping against its spec and the mirror (#59).

Read-only, **mirror-only** (no HWDB calls, no bearer). Most boxes on the
FD-VD chart point at types that are not registered in HWDB yet; this keeps
``<chart>.mapping.yaml`` maintainable as consortia register them. Same
audit→curate loop as ``list_shippable``/``list_systems`` — the workflow is:
types land in HWDB → "Refresh hierarchy" (so the mirror sees them) → run
this audit → hand-edit the mapping file from the paste-ready suggestions.
Nothing is ever written automatically.

Reports, per instance:

- **stale mappings** — mapped part type ids absent from the mirror
  (type deleted upstream, a typo, or the mirror needs a refresh);
- **unknown node ids** — mapping keys that are not in the chart spec
  (typo, or the node was renamed/removed in a spec update);
- **unmapped chart nodes** — boxes with no mapping entry, with candidate
  mirror types fuzzy-matched by name, formatted for pasting.

    python manage.py audit_chart_mapping
    python manage.py audit_chart_mapping fd-vd-v10 --instance dev
"""
import difflib
import re

from django.core.management.base import BaseCommand

from explore import charts
from explore.models import HierarchyNode


def _score(label: str, name: str) -> float:
    """Name-match score in [0, 1]. Substring containment beats raw ratio:
    box labels are short ("FEMB") while type names carry flavor suffixes
    ("FEMB FD-VD MiniSAS"), which difflib alone scores poorly. Tiny strings
    (mirror placeholder names like "0") don't earn the containment bonus."""
    a, b = label.lower(), name.lower()
    if len(min(a, b, key=len)) >= 4 and (a in b or b in a):
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


class Command(BaseCommand):
    help = "Audit a chart's type mapping against its spec and the mirror (read-only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "chart", nargs="?", default=None,
            help="Chart id (default: the only chart, error if several).",
        )
        parser.add_argument(
            "--instance", default="prod",
            help="HWDB instance whose mapping + mirror to audit (default: prod).",
        )

    def handle(self, *args, **opts):
        chart_id = opts["chart"]
        if chart_id is None:
            ids = charts.chart_ids()
            if len(ids) != 1:
                self.stderr.write(f"Pick a chart: {', '.join(ids)}")
                return
            chart_id = ids[0]
        instance = opts["instance"]

        boxes = {b["id"]: b["label"] for b in charts.svg_chart(chart_id)["boxes"]}
        mapping = charts.type_mapping(chart_id, instance)
        leaves = list(
            HierarchyNode.for_instance(instance)
            .filter(level=HierarchyNode.LEVEL_TYPE)
            .exclude(part_type_id="")
        )
        in_mirror = {n.part_type_id for n in leaves}

        mapped = set(mapping) & set(boxes)
        unmapped = sorted(set(boxes) - set(mapping))
        unknown = sorted(set(mapping) - set(boxes))
        stale = [(nid, ptid) for nid in sorted(mapping)
                 for ptid in mapping[nid] if ptid not in in_mirror]

        self.stdout.write(
            f"Chart '{chart_id}' · instance {instance} · "
            f"{len(boxes)} nodes: {len(mapped)} mapped, {len(unmapped)} unmapped · "
            f"mirror has {len(leaves)} component types\n"
        )

        if stale:
            self.stdout.write(
                "Stale mappings — part type ids not in the mirror "
                "(refresh the hierarchy first; else fix or remove):"
            )
            for nid, ptid in stale:
                self.stdout.write(f"  {nid}: {ptid}")
        else:
            self.stdout.write("No stale mappings.")

        if unknown:
            self.stdout.write("")
            self.stdout.write("Mapping keys not in the chart spec (typo or removed node):")
            for nid in unknown:
                self.stdout.write(f"  {nid}")

        if not unmapped:
            self.stdout.write("")
            self.stdout.write("Every chart node is mapped.")
            return

        # Fuzzy-match unmapped labels against mirror type names. Multiplicity
        # suffixes ("FEMB (1)") never appear in type names — strip them.
        already_mapped = {p for ptids in mapping.values() for p in ptids}
        suggestions, no_candidates = [], []
        for nid in unmapped:
            label = re.sub(r"\s*\(.*?\)$", "", boxes[nid])
            ranked = sorted(
                ((round(_score(label, n.name), 2), n) for n in leaves
                 if n.part_type_id not in already_mapped),
                key=lambda t: t[0], reverse=True,
            )
            top = [(s, n) for s, n in ranked[:3] if s >= 0.55]
            (suggestions if top else no_candidates).append((nid, boxes[nid], top))

        if suggestions:
            self.stdout.write("")
            self.stdout.write(
                f"Unmapped nodes with mirror candidates ({len(suggestions)}) — "
                f"paste the right ones into {chart_id}.mapping.yaml:"
            )
            for nid, label, top in suggestions:
                score, best = top[0]
                self.stdout.write(
                    f"    {nid}: [{best.part_type_id}]"
                    f"  # \"{label}\" ~ {best.system_name} › {best.name} ({score:.0%})"
                )
                for score, alt in top[1:]:
                    self.stdout.write(
                        f"    #   alt: {alt.part_type_id}"
                        f"  {alt.system_name} › {alt.name} ({score:.0%})"
                    )

        if no_candidates:
            self.stdout.write("")
            self.stdout.write(
                f"Unmapped nodes with no candidate in the mirror ({len(no_candidates)}) — "
                "likely not registered yet:"
            )
            for nid, label, _ in no_candidates:
                self.stdout.write(f"  {nid:<32}  {label}")
