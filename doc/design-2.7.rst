=================
Ganeti 2.7 design
=================

The following design documents have been implemented in Ganeti 2.7:

- :doc:`design-bulk-create`
- :doc:`design-opportunistic-locking`
- :doc:`design-restricted-commands`
- :doc:`design-node-add`
- :doc:`design-virtual-clusters`
- :doc:`design-network`
- :doc:`design-linuxha`
- :doc:`design-shared-storage` (Updated to reflect the new ExtStorage
  Interface)

The following designs have been partially implemented in Ganeti 2.7:

- :doc:`design-query-splitting`: only queries not needing RPC are
  supported, through confd
- :doc:`design-partitioned`: only exclusive use of disks is implemented
- :doc:`design-monitoring-agent`: an example standalone DRBD data
  collector is included

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
