gnt-os(8) Ganeti | Version @GANETI_VERSION@
===========================================

Name
----

gnt-os - Instance operating system administration

Synopsis
--------

**gnt-os** {command} [arguments...]

DESCRIPTION
-----------

The **gnt-os** is used for managing the list of available operating
system flavours for the instances in the Ganeti cluster.

COMMANDS
--------

LIST
~~~~

**list** [\--no-headers]

Gives the list of available/supported OS to use in the instances.
When creating the instance you can give the OS-name as an option.

Note that hidden or blacklisted OSes are not displayed by this
command, use **diagnose** for showing those.

DIAGNOSE
~~~~~~~~

**diagnose**

This command will help you see why an installed OS is not available
in the cluster. The **list** command shows only the OS-es that the
cluster sees available on all nodes. It could be that some OS is
missing from a node, or is only partially installed, and this
command will show the details of all the OSes and the reasons they
are or are not valid.

INFO
~~~~

**info**

This command will list detailed information about each OS available
in the cluster, including its validity status, the supported API
versions, the supported parameters (if any) and their
documentations, etc.

MODIFY
~~~~~~

| **modify** [\--submit] [\--print-job-id]
| [ [ -O | --os-parameters ] =*option*=*value*]
| [ --os-parameters-private=*option*=*value*]
| [-H *HYPERVISOR*:option=*value*[,...]]
| [\--hidden=*yes|no*] [\--blacklisted=*yes|no*]
| {*OS*}

This command will allow you to modify OS parameters.

To modify the per-OS hypervisor parameters (which override the
global hypervisor parameters), you can run modify ``-H`` with the
same syntax as in **gnt-cluster init** to override default
hypervisor parameters of the cluster for specified *OS* argument.

To modify the parameters passed to the OS install scripts, use the
**--os-parameters** option. If the value of the parameter should not be
saved to logs, use **--os-parameters-private** *and* make sure that
no Ganeti daemon or program is running in debug mode. **ganeti-luxid**
in particular will issue a warning at startup time if ran in debug mode.

To modify the hidden and blacklisted states of an OS, pass the options
``--hidden`` *yes|no*, or respectively ``--blacklisted ...``. The
'hidden' state means that an OS won't be listed by default in the OS
list, but is available for installation. The 'blacklisted' state means
that the OS is not listed and is also not allowed for new instance
creations (but can be used for reinstalling old instances).

Note: The given operating system doesn't have to exist. This allows
preseeding the settings for operating systems not yet known to
**gnt-os**.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
