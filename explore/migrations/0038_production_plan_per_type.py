# #200: the production plan moves onto each component type (one cached row
# per type), the consortium type keeps a component list; the cached
# checklist tables of #199 go. The old plan rows were a cache of those
# tables — dropped, the status page / plan page refill the new shape.

from django.db import migrations, models


def drop_old_plan_rows(apps, schema_editor):
    apps.get_model("explore", "ProductionPlan").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('explore', '0037_production_status'),
    ]

    operations = [
        migrations.RunPython(drop_old_plan_rows, migrations.RunPython.noop),
        migrations.DeleteModel(name='ProductionTable'),
        migrations.AlterModelOptions(name='productionplan', options={'ordering': ['part_type_id']}),
        migrations.RemoveField(model_name='productionplan', name='source_type_id'),
        migrations.RemoveField(model_name='productionplan', name='source_part_id'),
        migrations.RemoveField(model_name='productionplan', name='checklist'),
        migrations.RemoveField(model_name='productionplan', name='component'),
        migrations.AlterField(model_name='productionplan', name='part_type_id',
                              field=models.CharField(db_index=True, max_length=20)),
        migrations.AddField(model_name='productionplan', name='comment',
                            field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='productionplan', name='updated_by',
                            field=models.CharField(blank=True, default='', max_length=150)),
        migrations.AddField(model_name='productionplan', name='updated',
                            field=models.CharField(blank=True, default='', max_length=40)),
        migrations.AddConstraint(model_name='productionplan',
                                 constraint=models.UniqueConstraint(fields=('instance', 'part_type_id'), name='uniq_production_plan')),
        migrations.CreateModel(
            name='ProductionList',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('instance', models.CharField(db_index=True, default='prod', max_length=8)),
                ('part_type_id', models.CharField(db_index=True, max_length=20)),
                ('rows', models.JSONField(default=list)),
                ('read_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['part_type_id'],
                'constraints': [models.UniqueConstraint(fields=('instance', 'part_type_id'), name='uniq_production_list')],
            },
        ),
    ]
