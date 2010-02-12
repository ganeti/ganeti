=====================
Ganeti Cluster Merger
=====================

Current situation
=================

Currently there's no easy way to merge two or more clusters together.
But in order to optimize resources this is a needed missing piece. The
goal of this design doc is to come up with a easy to use solution which
allows you to merge two or more cluster together.

Initial contact
===============

As the design of Ganeti is based on an autonomous system, Ganeti by
itself has no way to reach nodes outside of its cluster. To overcome
this situation we're required to prepare the cluster before we can go
ahead with the actual merge: We've to replace at least the ssh keys on
the affected nodes before we can do any operation within ``gnt-``
commands.

To make this a automated process we'll ask the user to provide us with
the root password of every cluster we've to merge. We use the password
to grab the current ``id_dsa`` key and then rely on that ssh key for any
further communication to be made until the cluster is fully merged.

Cluster merge
=============

After initial contact we do the cluster merge:

1. Grab the list of nodes
2. On all nodes add our own ``id_dsa.pub`` key to ``authorized_keys``
3. Stop all instances running on the merging cluster
4. Disable ``ganeti-watcher`` as it tries to restart Ganeti daemons
5. Stop all Ganeti daemons on all merging nodes
6. Grab the ``config.data`` from the master of the merging cluster
7. Stop local ``ganeti-masterd``
8. Merge the config:

   1. Open our own cluster ``config.data``
   2. Open cluster ``config.data`` of the merging cluster
   3. Grab all nodes of the merging cluster
   4. Set ``master_candidate`` to false on all merging nodes
   5. Add the nodes to our own cluster ``config.data``
   6. Grab all the instances on the merging cluster
   7. Adjust the port if the instance has drbd layout:

      1. In ``logical_id`` (index 2)
      2. In ``physical_id`` (index 1 and 3)

   8. Add the instances to our own cluster ``config.data``

9. Start ``ganeti-masterd`` with ``--no-voting`` ``--yes-do-it``
10. ``gnt-node add --readd`` on all merging nodes
11. ``gnt-cluster redist-conf``
12. Restart ``ganeti-masterd`` normally
13. Enable ``ganeti-watcher`` again
14. Start all merging instances again

Rollback
========

Until we actually (re)add any nodes we can abort and rollback the merge
at any point. After merging the config, though, we've to get the backup
copy of ``config.data`` (from another master candidate node). And for
security reasons it's a good idea to undo ``id_dsa.pub`` distribution by
going on every affected node and remove the ``id_dsa.pub`` key again.
Also we've to keep in mind, that we've to start the Ganeti daemons and
starting up the instances again.

Verification
============

Last but not least we should verify that the merge was successful.
Therefore we run ``gnt-cluster verify``, which ensures that the cluster
overall is in a healthy state. Additional it's also possible to compare
the list of instances/nodes with a list made prior to the upgrade to
make sure we didn't lose any data/instance/node.

Appendix
========

cluster-merge.py
----------------

Used to merge the cluster config. This is a POC and might differ from
actual production code.

::

  #!/usr/bin/python

  import sys
  from ganeti import config
  from ganeti import constants

  c_mine = config.ConfigWriter(offline=True)
  c_other = config.ConfigWriter(sys.argv[1])

  fake_id = 0
  for node in c_other.GetNodeList():
    node_info = c_other.GetNodeInfo(node)
    node_info.master_candidate = False
    c_mine.AddNode(node_info, str(fake_id))
    fake_id += 1

  for instance in c_other.GetInstanceList():
    instance_info = c_other.GetInstanceInfo(instance)
    for dsk in instance_info.disks:
      if dsk.dev_type in constants.LDS_DRBD:
         port = c_mine.AllocatePort()
         logical_id = list(dsk.logical_id)
         logical_id[2] = port
         dsk.logical_id = tuple(logical_id)
         physical_id = list(dsk.physical_id)
         physical_id[1] = physical_id[3] = port
         dsk.physical_id = tuple(physical_id)
    c_mine.AddInstance(instance_info, str(fake_id))
    fake_id += 1

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
