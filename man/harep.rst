HAREP(1) Ganeti | Version @GANETI_VERSION@
==========================================

NAME
----

harep - Ganeti auto-repair tool

SYNOPSIS
--------

**harep** [ [**-L** | **\--luxi** ] = *socket* ] [ --job-delay = *seconds* ]

**harep** \--version

DESCRIPTION
-----------

Harep is the Ganeti auto-repair tool. It is able to detect that an instance is
broken and to generate a sequence of jobs that will fix it, in accordance to the
policies set by the administrator.

Harep is able to recognize what state an instance is in (healthy, suspended,
needs repair, repair disallowed, pending repair, repair disallowed, repair
failed) and to lead it through a sequence of steps that will bring the instance
back to the healthy state. Therefore, harep is mainly meant to be run regularly
and frequently using a cron job, so that is can actually follow the instance
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

* ``fix-storage``: allow disk replacement or fix the backend without affecting the instance
  itself (broken DRBD secondary)
* ``migrate``: allow instance migration
* ``failover``: allow instance reboot on the secondary
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


OPTIONS
-------

The options that can be passed to the program are as follows:

-L *socket*, \--luxi=*socket*
  collect data via Luxi, optionally using the given *socket* path.

\--job-delay=*seconds*
  insert this much delay before the execution of repair jobs to allow the tool
  to continue processing instances.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
