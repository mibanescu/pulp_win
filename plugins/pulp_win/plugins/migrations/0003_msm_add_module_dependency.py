import logging

from pulp.server.db import connection
from pulp_win.plugins.db.models import MSM


_logger = logging.getLogger(__name__)


def migrate(*args, **kwargs):
    """
    Add a ModuleDependency property. The property is extracted from running
    msiinfo on the msm file.
    """
    collection = connection.get_collection('units_msm')

    # Collect all units without ModuleDependency
    mds = dict()
    for unit in collection.find({'ModuleDependency':{'$exists':False}}):
        md = MSM._read_metadata(unit['_storage_path'])
        mds[unit['_id']] = md

    # Add the ModuleDependency property
    for _id, metadata in mds.items():
        module_dep = metadata.get('ModuleDependency', [])
        collection.update_one(dict(_id=_id),
                              {'$set': dict(ModuleDependency=module_dep)})
