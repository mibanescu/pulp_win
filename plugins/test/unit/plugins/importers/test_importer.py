"""
Contains tests for pulp_win.plugins.importers.importer.
"""
from gettext import gettext as _
import hashlib
import json
import os
import uuid

import mock

from pulp_win.common import ids
from .... import testbase
from pulp_win.plugins import models
from pulp_win.plugins.importers import importer


class TestEntryPoint(testbase.TestCase):
    """
    Tests for the entry_point() function.
    """
    def test_return_value(self):
        """
        Assert the correct return value for the entry_point() function.
        """
        return_value = importer.entry_point()

        expected_value = (importer.WinImporter, {})
        self.assertEqual(return_value, expected_value)
        self.assertEquals({
            models.MSI.TYPE_ID: models.MSI,
            models.MSM.TYPE_ID: models.MSM,
        }, importer.WinImporter.Type_Class_Map)


class TestWinImporter(testbase.TestCase):
    """
    This class contains tests for the WinImporter class.
    """

    def new_file(self, name=None, contents=None):
        if name is None:
            name = str(uuid.uuid4())
        file_path = os.path.join(self.work_dir, name)
        if contents is None:
            contents = str(uuid.uuid4())
        elif isinstance(contents, (dict, list)):
            contents = json.dumps(contents)
        checksum = hashlib.sha256(contents).hexdigest()
        with open(file_path, "w") as fobj:
            fobj.write(contents)
        return file_path, checksum

    def test_move_unit(self):
        unit_key = dict(name="aaa", version="1", checksum="bob")
        file_path, _ = self.new_file(contents=unit_key)
        metadata = dict(filename=file_path)
        unit = models.MSI(unit_key, metadata)
        conduit = mock.MagicMock()
        dest_path = os.path.join(self.work_dir, "dest-file")
        conduit.init_unit.return_value.configure_mock(storage_path=dest_path)
        unit.init_unit(conduit)

        # Make sure the file gets moved
        self.assertTrue(os.path.exists(file_path))
        self.assertFalse(os.path.exists(dest_path))
        unit.move_unit(file_path)
        self.assertFalse(os.path.exists(file_path))
        self.assertTrue(os.path.exists(dest_path))

    @mock.patch("pulp_win.plugins.importers.importer.UnitAssociationCriteria")  # noqa
    def test_import_units_units_none(self, _unitAssociationCriteria):
        """
        Assert correct behavior when units == None.
        """
        _unitAssociationCriteria.return_value = _uac = mock.MagicMock()
        win_importer = importer.WinImporter()
        import_conduit = mock.MagicMock()
        units = ['unit_a', 'unit_b', 'unit_3']
        import_conduit.get_source_units.return_value = units

        imported_units = win_importer.import_units(mock.MagicMock(),
                                                   mock.MagicMock(),
                                                   import_conduit,
                                                   mock.MagicMock(),
                                                   units=None)

        # Assert that the correct criteria was used
        self.assertEqual(
            [_uac],
            [x[2]['criteria']
             for x in import_conduit.get_source_units.mock_calls])
        import_conduit.get_source_units.assert_called_once_with(criteria=_uac)
        # Assert that the units were associated correctly
        associate_unit_call_args = [
            c[1] for c in import_conduit.associate_unit.mock_calls]
        self.assertEqual(associate_unit_call_args, [(u,) for u in units])
        # Assert that the units were returned
        self.assertEqual(imported_units, units)

    def test_import_units_units_not_none(self):
        """
        Assert correct behavior when units != None.
        """
        win_importer = importer.WinImporter()
        import_conduit = mock.MagicMock()
        units = ['unit_a', 'unit_b', 'unit_3']

        imported_units = win_importer.import_units(mock.MagicMock(),
                                                   mock.MagicMock(),
                                                   import_conduit,
                                                   mock.MagicMock(),
                                                   units=units)

        # Assert that no criteria was used
        self.assertEqual(import_conduit.get_source_units.call_count, 0)
        # Assert that the units were associated correctly
        associate_unit_call_args = [
            c[1] for c in import_conduit.associate_unit.mock_calls]
        self.assertEqual(associate_unit_call_args, [(u,) for u in units])
        # Assert that the units were returned
        self.assertEqual(imported_units, units)

    def test_metadata(self):
        """
        Test the metadata class method's return value.
        """
        metadata = importer.WinImporter.metadata()

        expected_value = {
            'id': ids.TYPE_ID_IMPORTER_WIN,
            'display_name': _('Windows importer'),
            'types': [ids.TYPE_ID_MSI, ids.TYPE_ID_MSM], }
        self.assertEqual(metadata, expected_value)

    @mock.patch('pulp_win.plugins.models.Package.from_file')
    @mock.patch('pulp_win.plugins.models.Package.init_unit', autospec=True)
    @mock.patch('pulp_win.plugins.models.Package.move_unit', autospec=True)
    @mock.patch('pulp_win.plugins.models.Package.save_unit', autospec=True)
    @mock.patch('shutil.move')
    def test_upload_unit(self, move, save_unit, move_unit, init_unit,
                         from_file):
        """
        Assert correct operation of upload_unit().
        """
        msi_file = os.path.join(self.work_dir, 'foo.msi')
        data = str(uuid.uuid4())
        file(msi_file, "wb").write(data)

        unit_key = dict()
        metadata = dict(
            checksumtype="sha1",
            checksum=hashlib.sha1(data).hexdigest())
        package = models.MSI(unit_key, metadata)
        from_file.return_value = package
        storage_path = '/some/path/name-version.msi'

        def init_unit_side_effect(self, conduit):
            class Unit(object):
                def __init__(self, *args, **kwargs):
                    self.unit_key = dict(name='a',
                                         version='1')
                    self.metadata = dict(filename='a-1.msi')
                    self.storage_path = storage_path
            self._unit = Unit()
        init_unit.side_effect = init_unit_side_effect

        win_importer = importer.WinImporter()
        repo = mock.MagicMock()
        type_id = ids.TYPE_ID_MSI
        conduit = mock.MagicMock()
        config = {}

        report = win_importer.upload_unit(repo, type_id, unit_key, metadata,
                                          msi_file, conduit, config)

        self.assertEqual(report,
                         {'success_flag': True,
                          'details': dict(
                              unit=dict(
                                  unit_key=dict(name='a', version='1'),
                                  metadata=dict(filename='a-1.msi'))),
                          'summary': ''})
        from_file.assert_called_once_with(msi_file, metadata)
        init_unit.assert_called_once_with(package, conduit)
        move_unit.assert_called_once_with(package, msi_file)
        save_unit.assert_called_once_with(package, conduit)

    def test_validate_config(self):
        """
        There is no config, so we'll just assert that validation passes.
        """
        win_importer = importer.WinImporter()
        return_value = win_importer.validate_config(mock.MagicMock(), {})

        self.assertEqual(return_value, (True, None))

    def test_ids(self):
        self.assertEquals(set(ids.UNIT_KEY_MSI),
                          models.MSI.UNIT_KEY_NAMES)
