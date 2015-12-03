HAREP(1) Ganeti | Version @GANETI_VERSION@
==========================================

NAME
----

harep - Ganeti auto-repair tool

SYNOPSIS
--------

**harep** [ [**-L** | **\--luxi** ] = *socket* ] [ --job-delay = *seconds* ]
[ --dry-run ]

**harep** \--version

DESCRIPTION
-----------

Harep is the Ganeti auto-repair tool. It is able to detect that an instance is
broken and to generate a sequence of jobs that will fix it, in accordance to the
policies set by the administrator. At the moment, only repairs for instances
using the disk templates ``plain`` or ``drbd`` are supported.

Harep is able to recognize what state an instance is in (healthy, suspended,
needs repair, repair disallowed, pending repair, repair failed)
and to lead it through a sequence of steps that will bring the instance
back to the healthy state. Therefore, harep is mainly meant to be run regularly
and frequently using a cron job, so that it can actually follow the instance
along all the process. At every run, harep will update the tags it adds to
instances that describe its repair status, and will submit jobs that actually
perform the required repair operations.

By default, harep only reports on the health status of instances, but doesn't
perform any action, as they might be potentially dangerous. Therefore, harep
will only touch instances that it has been explicitly authorized to work on.

The tags enabling harep, can be associated to single instances, or to a
nodegroup or to the whole cluster, therefore affecting all the instances they
contain. The possible tags share the common structure::

 ganeti:watcher:autorepair:<type>

where ``<type>`` can have the following values:

* ``fix-storage``: allow disk replacement or fix the backend without affecting
  the instance itself (broken DRBD secondary)
* ``migrate``: allow instance migration. Note, however, that current harep does
  not submit migrate jobs; so, currently, this permission level is equivalent to
  ``fix-storage``.
* ``failover``: allow instance reboot on the secondary; this action is taken, if
  the primary node is offline.
* ``reinstall``: allow disks to be recreated and the instance to be reinstalled

Each element in the list of tags, includes all the authorizations of the
previous one, with ``fix-storage`` being the least powerful and ``reinstall``
being the most powerful.

In case multiple autorepair tags act on the same instance, only one can actually
be active. The conflict is solved according to the following rules:

#. if multiple tags are in the same object, the least destructive takes
   precedence.

#. if the tags are across objects, the nearest tag wins.

Example:
A cluster has instances I1 and I2, where I1 has the ``failover`` tag, and
the cluster has both ``fix-storage`` and ``reinstall``.
The I1 instance will be allowed to ``failover``, the I2 instance only to
``fix-storage``.

LIMITATIONS
-----------

Harep doesn't do any hardware failure detection on its own, it relies on
nodes being marked as offline by the administrator.

Also harep currently works only for instances with the ``drbd`` and
``plain`` disk templates.

Using the data model of **htools**\(1), harep cannot distinguish between drained
and offline nodes. In particular, it will (permission provided) failover
instances also in situations where a migration would have been enough.
In particular, handling of node draining is better done using **hbal**\(1),
which will always submit migration jobs, however is the permission to fall
back to failover.

These issues will be addressed by a new maintenance daemon in
future Ganeti versions, which will supersede harep.


OPTIONS
-------

The options that can be passed to the program are as follows:

-L *socket*, \--luxi=*socket*
  collect data via Luxi, optionally using the given *socket* path.

\--job-delay=*seconds*
  insert this much delay before the execution of repair jobs to allow the tool
  to continue processing instances.

\--dry-run
  only show which operations would be carried out, but do nothing, even on
  instances where tags grant the appropriate permissions. Note that harep
  keeps the state of repair operations in instance tags; therefore, only
  the operations of the next round of actions can be inspected.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
