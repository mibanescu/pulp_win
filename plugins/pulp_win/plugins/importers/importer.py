import logging
from pulp.common import config as config_utils
from pulp.plugins.importer import Importer
from pulp.plugins.util import importer_config
from pulp.server.db.model.criteria import UnitAssociationCriteria
from gettext import gettext as _
from pulp_win.common.ids import SUPPORTED_TYPES, TYPE_ID_IMPORTER_WIN, \
    TYPE_ID_MSI
from pulp_win.plugins import models

_LOG = logging.getLogger(__name__)
# The leading '/etc/pulp/' will be added by the read_json_config method.
CONF_FILENAME = 'server/plugins.conf.d/%s.json' % TYPE_ID_IMPORTER_WIN


def entry_point():
    return WinImporter, config_utils.read_json_config(CONF_FILENAME)


class WinImporter(Importer):
    Type_Class_Map = {
        TYPE_ID_MSI: models.MSI,
    }

    def __init__(self):
        super(WinImporter, self).__init__()
        self.sync_cancelled = False

    @classmethod
    def metadata(cls):
        return {
            'id': TYPE_ID_IMPORTER_WIN,
            'display_name': _('Windows importer'),
            'types': sorted(SUPPORTED_TYPES),
        }

    def validate_config(self, repo, config):
        try:
            importer_config.validate_config(config)
            return True, None
        except importer_config.InvalidConfig, e:
            # Concatenate all of the failure messages into a single message
            msg = _('Configuration errors:\n')
            for failure_message in e.failure_messages:
                msg += failure_message + '\n'
        msg = msg.rstrip()  # remove the trailing \n
        return False, msg

    def upload_unit(self, repo, type_id, unit_key, metadata,
                    file_path, conduit, config):
        if type_id not in SUPPORTED_TYPES:
            return self.fail_report(
                "Unsupported unit type {0}".format(type_id))
        model_class = self.Type_Class_Map[type_id]
        try:
            unit = model_class.from_file(file_path, metadata)
        except ValueError, e:
            return self.fail_report(str(e))

        unit.init_unit(conduit)
        unit.move_unit(file_path)
        unit.save_unit(conduit)
        return dict(success_flag=True, summary="",
                    details=dict(
                        unit=dict(unit_key=unit._unit.unit_key,
                                  metadata=unit._unit.metadata)))

    def import_units(self, source_repo, dest_repo, import_conduit,
                     config, units=None):
        if not units:
            # If no units are passed in, assume we will use all units from
            # source repo
            criteria = UnitAssociationCriteria(
                type_ids=sorted(SUPPORTED_TYPES))
            units = import_conduit.get_source_units(criteria=criteria)
        _LOG.info("Importing %s units from %s to %s" %
                  (len(units), source_repo.id, dest_repo.id))
        for u in units:
            import_conduit.associate_unit(u)
        _LOG.debug("%s units from %s have been associated to %s" %
                   (len(units), source_repo.id, dest_repo.id))
        return units

    @classmethod
    def fail_report(cls, message):
        # this is the format returned by the original importer. I'm not sure if
        # anything is actually parsing it
        details = {'errors': [message]}
        return {'success_flag': False, 'summary': '', 'details': details}
