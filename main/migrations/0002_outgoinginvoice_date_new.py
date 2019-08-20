# Generated by Django 2.2.4 on 2019-08-16 16:25

import datetime

import pytz
from django.db import migrations, models

from tallybill import settings


def datetime_now_tz():
    return datetime.datetime.now(tz=pytz.timezone(settings.TIME_ZONE))


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='outgoinginvoice',
            name='date_new',
            field=models.DateTimeField(default=datetime_now_tz),
        ),
    ]
