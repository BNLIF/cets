"""#154: rewrite every HwdbTestValue row from its HwdbTestData record so
``values`` keeps the list structure (a list per list level) instead of the
flat leaf list 0027 stored. One-level data comes out identical; array keys
under lists of dicts (per-run × per-SiPM sweeps) gain their shape, which the
Plot view needs to pin one index. Pure functions from explore.plotting; no
HWDB access."""

from django.db import migrations, transaction


def _has_dict_in_list(node) -> bool:
    """Only records with a dict (or a list) inside a list store differently
    from 0027 — everything else keeps its flat row."""
    if isinstance(node, list):
        return any(isinstance(e, (dict, list)) for e in node) or False
    if isinstance(node, dict):
        return any(_has_dict_in_list(v) for v in node.values())
    return False


def rebuild(apps, schema_editor):
    from explore.plotting import flatten, leaves, nested, path_key

    HwdbTestData = apps.get_model("explore", "HwdbTestData")
    HwdbTestValue = apps.get_model("explore", "HwdbTestValue")
    qs = HwdbTestData.objects.order_by("pk")
    last, batch = 0, 200
    while True:
        recs = list(qs.filter(pk__gt=last)[:batch])
        if not recs:
            break
        last = recs[-1].pk
        rows, todo = [], []
        for r in recs:
            td = r.test_data if isinstance(r.test_data, dict) else {}
            if not _has_dict_in_list(td):
                continue
            todo.append(r)
            for p in flatten(td):
                v = nested(td, list(p))
                if v is None or v == []:
                    continue
                if not isinstance(v, list):
                    v = [v]
                rows.append(HwdbTestValue(instance=r.instance, part_type_id=r.part_type_id,
                                          part_id=r.part_id, test_type_id=r.test_type_id,
                                          path=path_key(p), values=v, nv=len(leaves(v))))
        if not todo:
            continue
        with transaction.atomic():
            for r in todo:
                HwdbTestValue.objects.filter(instance=r.instance, part_id=r.part_id,
                                             test_type_id=r.test_type_id).delete()
            HwdbTestValue.objects.bulk_create(rows, batch_size=2000)


class Migration(migrations.Migration):
    atomic = False          # commit per batch — a long single transaction would write-lock SQLite
    dependencies = [("explore", "0027_hwdbtestvalue")]
    operations = [migrations.RunPython(rebuild, migrations.RunPython.noop)]
