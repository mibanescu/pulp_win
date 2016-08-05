import sys
import tempfile
import unittest
from types import ModuleType


class ImporterWrapper(ModuleType):
    def __init__(self, name):
        self.__path__ = '/fake-path/' + name.replace('.', '/') + ".py"

    def __getattr__(self, name):
        if name != 'config':
            raise AttributeError(name)
        return self


sys.modules['pulp.server.config'] = ImporterWrapper('pulp.server.config')
import pulp.server  # noqa
pulp.server.config = sys.modules['pulp.server.config']


class TestCase(unittest.TestCase):
    def setUp(self):
        super(TestCase, self).setUp()
        self.work_dir = tempfile.mkdtemp()
