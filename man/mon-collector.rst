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

| drbd [ [ **-s** | **\--drbd-status** ] = *status-file* ] [ [ **-p** |
  **\--drbd-pairing**] = *pairing-file* ]

Collects the information about the version and status of the DRBD kernel
module, and of the disks it is managing.

If *status-file* and *pairing-file* are specified, the status and the
instance-minor paring information will be read from those files.
Otherwise, the collector will read them, respectively, from /proc/drbd
and from the Confd server.

The options that can be passed to the DRBD collector are as follows:

-s *status-file*, \--drbd-status=*status-file*
  Read the DRBD status from the specified file instead of /proc/drbd.

-p *pairing-file*, \--drbd-pairing=*pairing-file*
  Read the information about the pairing between instances and DRBD minors
  from the specified file instead of asking the Confd servers for them.

INSTANCE STATUS
~~~~~~~~~~~~~~~

| inst-status-xen [ [ **-a** | **\--address** ] = *ip-address* ] [ [ **-p** |
  **\--port** ] = *port-number* ]

Collects the information about the status of the instances of the current node.
In order to perform this task, it needs to connect to the ConfD daemon to fetch
some configuration information. The following parameters allow the user to
specify the position where the daemon is listening, in case it's not the default
one:

-a *ip-address*, \--address=*ip-address*
  The IP address the ConfD daemon is listening on.

-p *port-number*, \--port=*port-number*
  The port the ConfD deamon is listening on.
