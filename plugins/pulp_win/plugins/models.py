import hashlib
import os
import shutil
import subprocess
from pulp_win.common import ids

MSIINFO_PATH = '/usr/bin/msiinfo'
if not os.path.exists(MSIINFO_PATH):
    raise RuntimeError("msiinfo is not available")


class Error(Exception):
    pass


class InvalidPackageError(Error):
    pass


class Package(object):
    UNIT_KEY_NAMES = set(ids.UNIT_KEY_MSI)
    UNIT_KEY_TO_FIELD_MAP = dict()

    def __init__(self, unit_key, metadata):
        self.unit_key = unit_key
        self.metadata = metadata
        self._unit = None

    @classmethod
    def from_file(cls, filename, user_metadata=None, calculate_checksum=False):
        if not user_metadata:
            user_metadata = {}
        unit_md = cls._read_metadata(filename)
        unit_key = dict(checksumtype='sha256')
        checksum_type = user_metadata.get('checksumtype', '').lower()
        if checksum_type != unit_key['checksumtype']:
            # The client may choose whatever checksum it suits them.
            # Internally we will only use sha256
            checksum_type = None
        checksum = user_metadata.get('checksum', '').lower()
        if calculate_checksum or not (checksum_type and checksum):
            fobj = open(filename, "r")
            unit_key['checksum'] = cls._compute_checksum(fobj)
            unit_key['checksumtype'] = 'sha256'
        else:
            unit_key.update(checksum=checksum)
        for unit_key_name in cls.UNIT_KEY_NAMES:
            prop_name = cls.UNIT_KEY_TO_FIELD_MAP.get(unit_key_name,
                                                      unit_key_name)
            unit_key.setdefault(unit_key_name, unit_md.get(prop_name))
        metadata = {}
        for attr in cls._ATTRS:
            metadata[attr] = unit_md.get(attr)
        metadata['filename'] = cls.filename_from_unit_key(unit_key)
        return cls(unit_key, metadata)

    @classmethod
    def _run_cmd(cls, cmd):
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
            stdout, stderr = p.communicate()
        except Exception, e:
            raise Error(str(e))
        if p.returncode != 0:
            raise InvalidPackageError(stderr)
        return stdout, stderr

    @property
    def relative_path(self):
        return os.path.join(
            self.unit_key['name'], self.unit_key['version'],
            self.unit_key['checksum'], self.metadata['filename'])

    def init_unit(self, conduit):
        self._unit = conduit.init_unit(
            self.TYPE_ID, self.unit_key, self.metadata, self.relative_path)
        return self

    def move_unit(self, file_path):
        shutil.move(file_path, self._unit.storage_path)

    def save_unit(self, conduit):
        conduit.save_unit(self._unit)

    @classmethod
    def _compute_checksum(cls, fobj):
        dig = hashlib.sha256()
        while 1:
            block = fobj.read(16384)
            if not block:
                break
            dig.update(block)
        return dig.hexdigest()

    @classmethod
    def filename_from_unit_key(cls, unit_key):
        return "{0}-{1}.{2}".format(
            unit_key['name'], unit_key['version'], cls.TYPE_ID)

    @classmethod
    def _read_msi_module_signature(cls, filename):
        # https://msdn.microsoft.com/en-us/library/windows/desktop/aa370051(v=vs.85).aspx
        cmd = [MSIINFO_PATH, 'export', filename, 'ModuleSignature']
        stdout, _ = cls._run_cmd(cmd)
        # According to the document linked above, the ModuleID is always
        # name.GUID. msiinfo will return a bunch of header rows which are not
        # in that format, so the rpartition will skip them.
        metadata = []
        for row in stdout.split('\n'):
            arr = row.rstrip().split('\t', 2)
            if len(arr) != 3:
                continue
            name, sep, guid = arr[0].rpartition('.')
            if not sep:
                continue
            metadata.append(dict(name=name, guid=guid, version=arr[2]))
        metadata.sort(key=lambda x: (x['name'], x['version']))
        return metadata

    @classmethod
    def _read_msi_tables(cls, filename):
        cmd = [MSIINFO_PATH, 'tables', filename]
        stdout, _ = cls._run_cmd(cmd)
        tables = set(h.rstrip() for h in stdout.split('\n'))
        return tables


class MSI(Package):
    TYPE_ID = ids.TYPE_ID_MSI
    _ATTRS = ids.EXTRA_FIELDS_MSI
    UNIT_KEY_TO_FIELD_MAP = dict(name='ProductName', version='ProductVersion')

    @classmethod
    def _read_metadata(cls, filename):
        tables = cls._read_msi_tables(filename)
        if 'Property' not in tables:
            raise InvalidPackageError("MSI does not have a Property table")
        cmd = [MSIINFO_PATH, 'export', filename, 'Property']
        stdout, stderr = cls._run_cmd(cmd)
        headers = (h.rstrip().partition('\t')
                   for h in stdout.split('\n'))
        headers = dict((x[0], x[2]) for x in headers if x[1] == '\t')
        # Add the module signature, to link an MSI to an MSM
        if 'ModuleSignature' in tables:
            module_signature = cls._read_msi_module_signature(filename)
        else:
            module_signature = []
        headers['ModuleSignature'] = module_signature
        return headers


class MSM(Package):
    TYPE_ID = ids.TYPE_ID_MSM
    _ATTRS = ids.EXTRA_FIELDS_MSM

    @classmethod
    def _read_metadata(cls, filename):
        # First, dump tables. An MSM should not contain Property
        tables = cls._read_msi_tables(filename)
        if 'Property' in tables:
            raise InvalidPackageError("Attempt to handle an MSI as an MSM")
        if 'ModuleSignature' not in tables:
            # Theoretically impossible:
            # https://msdn.microsoft.com/en-us/library/windows/desktop/aa370051(v=vs.85).aspx
            raise InvalidPackageError("ModuleSignature is missing")

        # According to the document linked above, the ModuleID is always
        # name.GUID. msiinfo will return a bunch of header rows which are not
        # in that format, so the rpartition will skip them.
        module_signature = cls._read_msi_module_signature(filename)
        if len(module_signature) != 1:
            raise InvalidPackageError(
                "Not a valid MSM: more than one entry in ModuleSignature")
        metadata = module_signature[0]
        return metadata
