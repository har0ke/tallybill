#!/usr/bin/python
# -*- coding: <utf-8> -*-
import os
import shlex

import pwd
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from main.billing import RecalculateThread
from main.models import ProductType


class Command(BaseCommand):

    def add_arguments(self, parser):
        # declare file to import from
        parser.add_argument("user")
        parser.add_argument("environment")

    def handle(self, *args, **options):
        with open(os.path.join(os.path.dirname(__file__), "tally_recalculate.service")) as f:
            template = f.read()

        options = {
            "user": shlex.quote(options["user"]),
            "venv": shlex.quote(os.path.abspath(options["environment"])),
            "proj": shlex.quote(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
        }

        if not os.path.exists(os.path.join(options["venv"], "bin", "activate")):
            print(os.path.join(options["venv"], "bin", "activate") + " does not exist.")
            exit(-1)

        try:
            pwd.getpwnam(options["user"])
        except KeyError:
            print('User %s does not exist.' % options["user"])
            exit(-1)

        if not os.path.exists(os.path.join(options["venv"], "bin", "activate")):
            print(os.path.join(options["venv"], "bin", "activate") + " does not exist.")

        output_file =  "/etc/systemd/system/tally-recalculate.service"

        print("Installing service (%s)" % output_file)
        os.system("sudo bash -c " + shlex.quote("echo " + shlex.quote(template.format(**options)) + " > " + output_file))
        print("Enabling service")
        os.system("sudo systemctl enable tally-recalculate")