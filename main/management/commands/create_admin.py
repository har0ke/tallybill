#!/usr/bin/python
# -*- coding: <utf-8> -*-

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from main.models import ProductType


class Command(BaseCommand):

    @transaction.atomic
    def handle(self, *args, **options):
        print("Create admin...")
        user = User.objects.create(email="test@test.test", username="Getraenkewart",
                                   first_name="", last_name="", is_staff=True)
        user.set_password("getraenke1893")
        user.save()

        ProductType(name="Getränke").save()
