import logging

from pulp.server.db import connection


_logger = logging.getLogger(__name__)


def migrate(*args, **kwargs):
    """
    Add a ProductName property. The name property is extracted from the MSI's
    ShortName, if it exists, and then it falls back to ProductName.
    """
    collection = connection.get_collection('units_msi')
    # Collect all existing name properties
    names = dict()
    for unit in collection.find({}):
        names[unit['_id']] = unit['name']
    # Add the ProductName property
    for _id, name in names.items():
        collection.update_one(dict(_id=_id),
                              {'$set': dict(ProductName=name)})
