# Generated by Django 2.2.4 on 2019-08-16 16:22
import datetime

import pytz
from django.db import migrations
from tallybill import settings


def combine_names(apps, schema_editor):
    OutgoingInvoice = apps.get_model('main', 'OutgoingInvoice')
    for inv in OutgoingInvoice.objects.all():
        inv.date_new = datetime.datetime(inv.date.year, inv.date.month, inv.date.day, tzinfo=pytz.timezone(settings.TIME_ZONE))
        inv.save()


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0002_outgoinginvoice_date_new'),
    ]

    operations = [
        migrations.RunPython(combine_names),
    ]
