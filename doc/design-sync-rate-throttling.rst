DRBD Sync Rate Throttling
=========================

Objective
---------

This document outlines the functionality to conveniently set rate limits for
synchronization tasks. A use-case of this is that moving instances might
otherwise clog the network for the nodes. If the replication network differs
from the network used by the instances, there would be no benefits.

Namely there should be two limits that can be set:

* `resync-rate`: which should not be exceeded for each device. This exists
  already.
* `total-resync-rate`: which should not be exceeded collectively for each
  node.

Configuration
-------------

Suggested command line parameters for controlling throttling are as
follows::

  gnt-cluster modify -D resync-rate=<bytes-per-second>
  gnt-cluster modify -D total-resync-rate=<bytes-per-second>

Where ``bytes-per-second`` can be in the format ``<N>{b,k,M,G}`` to set the
limit to N bytes, kilobytes, megabytes, and gigabytes respectively.

Semantics
---------

The rate limit that is set for the drbdsetup is at least

  rate = min(resync-rate,
             total-resync-rate/number-of-syncing-devices)


where number-of-syncing-devices is checked on beginning and end of syncs. This
is set on each node with

  drbdsetup <minor> disk-options --resync-rate <rate> --c-max-rate <rate>

Later versions might free additional bandwidth on the source/target if the
target/source is more throttled.

Architecture
------------

The code to adjust the sync rates is collected in a separate tool ``hrates``
that

#. is run when a new sync is started or finished.
#. can be run manually if necessary.

Since the rates don't depend on the job, an unparameterized RPC
``perspective_node_run_hrates`` to NodeD will trigger the execution of the
tool.

A first version will query ConfD for the other nodes of the group and request
the sync state for all of them.

.. TODO: second version that avoids overhead.
