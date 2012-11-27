mon-collector(7) Ganeti | Version @GANETI_VERSION@
==================================================

NAME
----

mon-collector - Command line interface for the data collectors of the
monitoring system

SYNOPSIS
--------

**mon-collector** {collector}

DESCRIPTION
-----------

``mon-collector`` is a suite of tools designed to provide a command line
interface to the data collectors implemented by the ganeti monitoring system.
``mon-collector`` is also the generic binary that must be invoked specifying,
as the first command line parameter, the name of the actual desired data
collector to be run.

When executed, ``mon-collector`` will run the specified collector and will
print its output to stdout, in JSON format.




COLLECTORS
----------

DRBD
~~~~

| drbd [*status-file*]

Collects the information about the version and status of the DRBD kernel
module, and of the disks it is managing.

If *status-file* is specified, the status will be read from that file.
Otherwise, the collector will read it from /proc/drbd.
