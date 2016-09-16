import errno
import io
import logging
import os
import rpm
import shutil

from gettext import gettext as _
from xml.etree import ElementTree
from pulp.plugins.util.publish_step import AtomicDirectoryPublishStep
from pulp.plugins.util.publish_step import PublishStep, UnitPublishStep
from pulp.plugins.distributor import Distributor
from pulp_win.common import ids, constants
from . import configuration

# Unfortunately, we need to reach into pulp_rpm in order to generate repomd
from pulp_rpm.plugins.distributors.yum.metadata.repomd import RepomdXMLFileContext  # noqa
from pulp_rpm.plugins.distributors.yum.metadata.primary import PrimaryXMLFileContext  # noqa

_LOG = logging.getLogger(__name__)


def entry_point():
    return WinDistributor, {}


class WinDistributor(Distributor):
    @classmethod
    def metadata(cls):
        return {
            'id': 'win_distributor',
            'display_name': 'Windows Distributor',
            'types': ['msi', 'exe'],
        }

    def validate_config(self, repo, config, config_conduit):
        return configuration.validate_config(repo, config, config_conduit)

    def publish_repo(self, repo, publish_conduit, config):
        publisher = Publisher(
            repo=repo, publish_conduit=publish_conduit,
            config=config, distributor_type=ids.TYPE_ID_DISTRIBUTOR_WIN)
        return publisher.publish()

    def distributor_removed(self, repo, config):
        repo_dir = configuration.get_master_publish_dir(
            repo, ids.TYPE_ID_DISTRIBUTOR_WIN)
        shutil.rmtree(repo_dir, ignore_errors=True)
        # remove the symlinks that might have been created for this
        # repo/distributor
        rel_path = configuration.get_repo_relative_path(repo, config)
        rel_path = rel_path.rstrip(os.sep)
        pub_dirs = [
            configuration.get_http_publish_dir(config),
            configuration.get_https_publish_dir(config),
        ]
        for pub_dir in pub_dirs:
            symlink = os.path.join(pub_dir, rel_path)
            try:
                os.unlink(symlink)
            except OSError as error:
                if error.errno != errno.ENOENT:
                    raise


class Publisher(PublishStep):
    description = _("Publishing windows artifacts")

    def __init__(self, repo, publish_conduit, config, distributor_type):
        super(Publisher, self).__init__(step_type=constants.PUBLISH_REPO_STEP,
                                        repo=repo,
                                        publish_conduit=publish_conduit,
                                        config=config,
                                        distributor_type=distributor_type)
        self.add_child(ModulePublisher(publish_conduit=publish_conduit,
                                       config=config, repo=repo))
        master_publish_dir = configuration.get_master_publish_dir(
            repo, distributor_type)
        target_directories = []
        if config.get(constants.PUBLISH_HTTP_KEYWORD):
            target_directories.append(
                configuration.get_http_publish_dir(config))
        if config.get(constants.PUBLISH_HTTPS_KEYWORD):
            target_directories.append(
                configuration.get_https_publish_dir(config))
        repo_path = configuration.get_repo_relative_path(repo, config)
        target_directories = [('/', os.path.join(x, repo_path))
                              for x in target_directories]
        atomic_publish_step = AtomicDirectoryPublishStep(
            self.get_working_dir(),
            target_directories,
            master_publish_dir)
        self.add_child(atomic_publish_step)
        self.description = self.__class__.description


class RepomdStep(PublishStep):
    def __init__(self):
        super(RepomdStep, self).__init__(constants.PUBLISH_REPOMD)

    def process_main(self, unit=None):
        wd = self.get_working_dir()
        total = len(self.parent.publish_msi.units)
        checksum_type = 'sha256'
        with PrimaryXMLFileContext(wd, total, checksum_type) as primary:
            sio = io.BytesIO()
            units = self.parent.publish_msi.units
            for unit in units:
                sio.seek(0)
                sio.truncate()
                el = self._package_to_xml(unit)
                et = ElementTree.ElementTree(el)
                et.write(sio, encoding="utf-8")
                repodata = unit.metadata.setdefault('repodata', {})
                repodata['primary'] = sio.getvalue()
                primary.add_unit_metadata(unit)

        with RepomdXMLFileContext(wd, checksum_type) as repomd:
            repomd.add_metadata_file_metadata('primary',
                                              primary.metadata_file_path,
                                              primary.checksum)

    @classmethod
    def _package_to_xml(cls, unit):
        unit_key = unit.unit_key.copy()
        checksum_type = unit_key.pop('checksumtype', 'sha256')
        el = cls._to_xml_element("package",
                                 attrib=dict(type=unit.type_id),
                                 content=unit_key)
        csum_nodes = el.findall('checksum')
        if csum_nodes:
            csum_node = csum_nodes[0]
            csum_node.attrib.update(pkgid="YES", type=checksum_type)
        path = os.path.basename(unit.storage_path)
        ElementTree.SubElement(el, "location", attrib=dict(href=path))
        return el

    @classmethod
    def _to_xml_element(cls, tag, attrib=None, content=None):
        if attrib is None:
            attrib = dict()
        if content is None:
            content = dict()
        el = ElementTree.Element(tag, attrib=attrib)
        for k, v in sorted(content.items()):
            ElementTree.SubElement(el, k).text = v
        return el


class PublishMSIStep(UnitPublishStep):
    def __init__(self, work_dir, **kwargs):
        super(PublishMSIStep, self).__init__(
            constants.PUBLISH_MSI_STEP, [ids.TYPE_ID_MSI], **kwargs)
        self.working_dir = work_dir
        self.units = []
        self.units_latest = dict()

    def process_unit(self, unit):
        self.units.append(unit)
        dest_path = os.path.join(self.get_working_dir(),
                                 os.path.basename(unit.storage_path))
        self._create_symlink(unit.storage_path, dest_path)
        name = unit.unit_key['ProductName']
        latest = self.units_latest.get(name)
        if latest is None or self._vercmp(latest.unit_key['ProductVersion'],
                                          unit.unit_key['ProductVersion']) < 0:
            self.units_latest[name] = unit

    @classmethod
    def _vercmp(cls, ver1, ver2):
        return rpm.labelCompare((None, ver1, ''), (None, ver2, ''))


class ModulePublisher(PublishStep):
    description = _("Publishing modules")

    def __init__(self, **kwargs):
        kwargs.setdefault('step_type', constants.PUBLISH_MODULES_STEP)
        super(ModulePublisher, self).__init__(**kwargs)
        self.description = self.__class__.description
        work_dir = self.get_working_dir()
        self.publish_msi = PublishMSIStep(work_dir)
        self.add_child(self.publish_msi)
        self.add_child(RepomdStep())

        if self.non_halting_exceptions is None:
            self.non_halting_exceptions = []

    def _get_total(self):
        return len(self.publish_msi.units)
