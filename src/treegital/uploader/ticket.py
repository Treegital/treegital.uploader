# -*- coding: utf-8 -*-

import re
import uuid
from os.path import join


class UUID_ATM(object):

    UUID = re.compile(
        "^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")

    @classmethod
    def check(cls, tid):
        assert cls.UUID.match(uid)

    @staticmethod
    def get_path(tid):
        return join(tid[0:2], tid[2:4], tid[4:6], tid[6:8], tid[9:])

    @staticmethod
    def generate():
        return str(uuid.uuid4())
