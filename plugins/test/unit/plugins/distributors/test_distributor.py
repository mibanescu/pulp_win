import os
import shutil
import sys
import time
import uuid
import hashlib
from xml.etree import ElementTree

import mock
from pulp.plugins.model import Unit
from .... import testbase

from pulp_win.common import ids


class Attributer(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ModuleFinder(object):
    _known = dict(
        nectar=dict(
            config=dict(DownloaderConfig=mock.MagicMock()),
            downloaders=dict(
                local=dict(LocalFileDownloader=mock.MagicMock()),
                threaded=dict(HTTPThreadedDownloader=mock.MagicMock()),
            ),
            listener=Attributer(DownloadEventListener=object),
        ),
        pulp_rpm=dict(
            plugins=dict(
                distributors=dict(
                    yum=dict(
                        metadata=dict(
                            repomd=dict(RepomdXMLFileContext=mock.MagicMock()),
                            primary=dict(PrimaryXMLFileContext=mock.MagicMock()),  # noqa
                        ),
                    )
                )
            )
        ),
    )

    def __init__(self, name=None):
        self.name = name

    def find_module(self, fullname, path=None):
        comps = fullname.split('.')
        fmod = self._known
        for comp in comps:
            fmod = fmod.get(comp)
            if fmod is None:
                return None
        return self

    def load_module(self, fullname):
        fn = []
        if self.name is not None:
            fn.append(self.name)
        fn.append(fullname)
        return self.__class__('.'.join(fn))

    def __getattr__(self, name):
        if name == '__path__':
            return "FAKE"
        if self.name:
            comps = self.name.split('.')
        else:
            comps = []
        comps.append(name)
        fmod = self._known
        for comp in comps:
            fmod = fmod.get(comp)
            if fmod is None:
                raise AttributeError(comp)
        return fmod


class BaseTest(testbase.TestCase):
    def setUp(self):
        super(BaseTest, self).setUp()
        self._meta_path = sys.meta_path
        sys.meta_path = [ModuleFinder()] + sys.meta_path
        from pulp_win.plugins.distributors import distributor
        self.Module = distributor
        self.Configuration = distributor.configuration
        root = os.path.join(self.work_dir, "root")
        self._confmock = mock.patch.dict(
            distributor.configuration.__dict__,
            ROOT_PUBLISH_DIR=root,
            MASTER_PUBLISH_DIR=os.path.join(root, "master"),
            HTTP_PUBLISH_DIR=os.path.join(root, "http", "repos"),
            HTTPS_PUBLISH_DIR=os.path.join(root, "https", "repos"),
        )
        self._confmock.start()

        comps = 'pulp_rpm.plugins.distributors.yum.metadata'.split('.')
        mdmod = reduce(lambda d, k: d[k], comps, ModuleFinder._known)
        self.repomdxml = mdmod['repomd']['RepomdXMLFileContext']
        self.primaryxml = mdmod['primary']['PrimaryXMLFileContext']
        self.repomdxml.reset_mock()
        self.primaryxml.reset_mock()

    def tearDown(self):
        self._confmock.stop()
        sys.meta_path = self._meta_path
        shutil.rmtree(self.work_dir)
        super(BaseTest, self).tearDown()

    def _config_conduit(self):
        ret = mock.MagicMock()
        ret.get_repo_distributors_by_relative_url.return_value = []
        return ret


class TestEntryPoint(BaseTest):
    """
    Tests for the entry_point() function.
    """
    def test_entry_point(self):
        """
        Assert the correct return value for the entry_point() function.
        """
        return_value = self.Module.entry_point()

        expected_value = (self.Module.WinDistributor, {})
        self.assertEqual(return_value, expected_value)


class TestConfiguration(BaseTest):
    def test_validate_config_empty(self):
        repo = mock.MagicMock(id="repo-1")
        conduit = self._config_conduit()
        config = {}
        distributor = self.Module.WinDistributor()
        self.assertEquals(
            (False, '\n'.join([
                'Configuration key [http] is required, but was not provided',
                'Configuration key [https] is required, but was not provided',
                'Configuration key [relative_url] is required, but was not provided',  # noqa
                'Settings serve via http and https are both set to false. At least one option should be set to true.',  # noqa
            ])),
            distributor.validate_config(repo, config, conduit))

    def test_validate_config(self):
        repo = mock.MagicMock(id="repo-1")
        conduit = self._config_conduit()
        config = dict(http=True, https=False, relative_url=None)
        distributor = self.Module.WinDistributor()
        self.assertEquals(
            distributor.validate_config(repo, config, conduit),
            (True, None))


class TestPublishRepo(BaseTest):
    @classmethod
    def _units(cls, storage_dir):
        units = [
            Unit(ids.TYPE_ID_MSI,
                 unit_key=dict(name='burgundy',
                               version='0.1938.0',
                               checksum='abcde', checksum_type='sha3.14'),
                 metadata={},
                 storage_path=None),
            Unit(ids.TYPE_ID_MSI,
                 unit_key=dict(name='chablis',
                               version='0.2013.0',
                               checksum='yz', checksum_type='sha3.14'),
                 metadata={},
                 storage_path=None)
        ]
        for unit in units:
            filename = "%s-%s.msi" % (unit.unit_key['name'],
                                      unit.unit_key['version'])
            unit.metadata['filename'] = filename
            unit.storage_path = os.path.join(storage_dir, filename)
            file(unit.storage_path, "wb").write(str(uuid.uuid4()))
            unit.unit_key['checksumtype'] = 'sha256'
            unit.unit_key['checksum'] = hashlib.sha256(
                open(unit.storage_path, "rb").read()).hexdigest()
        return units

    def test_publish_repo(self):
        # Set up some files
        storage_dir = os.path.join(self.work_dir, 'storage_dir')
        publish_dir = os.path.join(self.work_dir, 'publish_dir')
        os.makedirs(storage_dir)
        units = self._units(storage_dir)

        unit_counts = {ids.TYPE_ID_MSI: len(units)}

        distributor = self.Module.WinDistributor()
        repo = mock.Mock()
        repo_id = "repo-%d-win-level0" % int(time.time())
        repo.configure_mock(
            working_dir=os.path.join(self.work_dir, 'work_dir'),
            content_unit_counts=unit_counts,
            id=repo_id)

        conduit = self._config_conduit()
        conduit.get_units.return_value = units
        repo_config = dict(
            http=True, https=False,
            relative_url='level1/' + repo.id,
            http_publish_dir=publish_dir+'/http/repos',
            https_publish_dir=publish_dir+'/https/repos')

        distributor.publish_repo(repo, conduit, config=repo_config)
        self.assertEquals(
            [x[0][0] for x in conduit.build_success_report.call_args_list],
            [{'publish_directory': 'FINISHED', 'publish_modules': 'FINISHED'}])
        self.assertEquals(
            [x[0][1][0]['num_processed']
             for x in conduit.build_success_report.call_args_list],
            [1])
        self.assertEquals(
            [len(x[0][1][0]['sub_steps'])
             for x in conduit.build_success_report.call_args_list],
            [2])
        # Make sure symlinks got created
        for unit in units:
            published_path = os.path.join(
                repo_config['http_publish_dir'],
                repo_config['relative_url'],
                unit.metadata['filename'])
            self.assertEquals(os.readlink(published_path), unit.storage_path)

        self.assertEqual(
            [['msi']],
            [x[0][0]['type_ids']
             for x in conduit.get_units.call_args_list],
        )

        publish_dir = os.path.join(repo_config['http_publish_dir'],
                                   repo_config['relative_url'])

        # Make sure we've invoked the repomd publisher
        self.repomdxml.assert_called_once_with(repo.working_dir, 'sha256')
        exp_units = units
        count = len(exp_units)
        self.primaryxml.assert_called_once_with(repo.working_dir, count,
                                                'sha256')
        cargs = self.primaryxml.return_value.__enter__.return_value. add_unit_metadata.call_args_list  # noqa
        self.assertEquals(
            [mock.call(u) for u in exp_units],
            cargs
        )

        processed_units = [x[0][0] for x in cargs]
        checksum_nodes = [
            self._xml_path(u.metadata['repodata']['primary'], 'checksum')
            for u in processed_units]
        self.assertEquals(
            [x.unit_key['checksum'] for x in exp_units],
            [node.text for node in checksum_nodes])
        self.assertEquals(
            [dict(pkgid='YES', type='sha256') for x in exp_units],
            [node.attrib for node in checksum_nodes])

        exp_filenames = [os.path.basename(x.storage_path) for x in exp_units]
        self.assertEquals(
            exp_filenames,
            [self._xml_path(x[0][0].metadata['repodata']['primary'],
                            'location').get('href')
             for x in cargs]
        )

        # Delete distributor
        master_repo_dir = self.Configuration.get_master_publish_dir(
            repo, ids.TYPE_ID_DISTRIBUTOR_WIN)
        self.assertTrue(os.path.exists(master_repo_dir))
        self.assertTrue(os.path.exists(publish_dir))
        distributor.distributor_removed(repo, repo_config)
        self.assertFalse(os.path.exists(master_repo_dir))
        self.assertFalse(os.path.exists(publish_dir))

    @classmethod
    def _xml_path(cls, strxml, *paths):
        el = ElementTree.fromstring(strxml)
        for p in paths:
            el = el.find(p)
            return el
