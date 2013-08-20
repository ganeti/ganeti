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

harep is the Ganeti auto-repair tool. It is able to detect that an instance is
broken and to generate a sequence of jobs that will fix it, in accordance to the
policies set by the administrator.

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
