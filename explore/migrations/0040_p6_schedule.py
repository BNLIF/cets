# #206: the P6 schedule (P6Upload + P6Activity, project-wide), a plan's two P6
# activity ids, and one plan per consortium for a type two consortia list.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('explore', '0039_test_event_created_by'),
    ]

    operations = [
        migrations.CreateModel(
            name='P6Activity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('activity_id', models.CharField(db_index=True, max_length=60)),
                ('kind', models.CharField(max_length=8)),
                ('name', models.CharField(blank=True, default='', max_length=300)),
                ('date', models.DateField(blank=True, null=True)),
                ('source', models.CharField(blank=True, default='', max_length=40)),
                ('detector', models.CharField(blank=True, default='', max_length=8)),
                ('sheet', models.CharField(blank=True, default='', max_length=60)),
                ('component', models.CharField(blank=True, default='', max_length=120)),
                ('notes', models.TextField(blank=True, default='')),
            ],
            options={
                'ordering': ['sheet', 'activity_id'],
            },
        ),
        migrations.CreateModel(
            name='P6Upload',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('uploaded', models.DateTimeField(auto_now_add=True)),
                ('uploaded_by', models.CharField(blank=True, default='', max_length=150)),
                ('filename', models.CharField(blank=True, default='', max_length=200)),
                ('n_rows', models.IntegerField(default=0)),
            ],
        ),
        migrations.RemoveConstraint(
            model_name='productionplan',
            name='uniq_production_plan',
        ),
        migrations.AddField(
            model_name='productionplan',
            name='consortium',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='productionplan',
            name='p6_completed_id',
            field=models.CharField(blank=True, default='', max_length=60),
        ),
        migrations.AddField(
            model_name='productionplan',
            name='p6_needed_id',
            field=models.CharField(blank=True, default='', max_length=60),
        ),
        migrations.AddConstraint(
            model_name='productionplan',
            constraint=models.UniqueConstraint(fields=('instance', 'part_type_id', 'consortium'), name='uniq_production_plan'),
        ),
        migrations.AddConstraint(
            model_name='p6activity',
            constraint=models.UniqueConstraint(fields=('activity_id', 'kind'), name='uniq_p6_activity'),
        ),
    ]
