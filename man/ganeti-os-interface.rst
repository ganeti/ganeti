ganeti-os-interface(7) Ganeti | Version @GANETI_VERSION@
========================================================

Name
----

ganeti-os-interface - Specifications for guest OS types

DESCRIPTION
-----------

The method of supporting guest operating systems in Ganeti is to have,
for each guest OS type, a directory containing a number of required
files. This directory must be present across all nodes (Ganeti doesn't
replicate it) in order for the OS to be usable by Ganeti.


REFERENCE
---------

There are eight required files: *create*, *import*, *export*, *rename*,
*verify* (executables), *ganeti_api_version*, *variants.list* and
*parameters.list* (text files).

Common environment
~~~~~~~~~~~~~~~~~~

All commands will get their input via environment variables. A
common set of variables will be exported for all commands, and some
of them might have extra ones. Note that all counts are
zero-based.

Since Ganeti version 2.5, the environment will be cleaned up before
being passed to scripts, therefore they will not inherit the environment
in with which the ganeti node daemon was started. If you depend on any
environment variables (non-Ganeti), then you will need to define or
source them appropriately.

OS_API_VERSION
    The OS API version that the rest of the environment conforms to.

INSTANCE_NAME
    The instance name the script should operate on.

INSTANCE_OS, OS_NAME
    Both names point to the name of the instance's OS as Ganeti knows
    it. This can simplify the OS scripts by providing the same scripts
    under multiple names, and then the scripts can use this name to
    alter their behaviour.

    With OS API 15 changing the script behavior based on this variable
    is deprecated: OS_VARIANT should be used instead (see below).

OS_VARIANT
    The variant of the OS which should be installed. Each OS must
    support all variants listed under its variants.list file, and may
    support more. Any more supported variants should be properly
    documented in the per-OS documentation.

HYPERVISOR
    The hypervisor of this instance.

DISK_COUNT
    The number of disks the instance has. The actual disk definitions are
    in a set of additional variables. The instance's disk will be
    numbered from 0 to this value minus one.

DISK_%N_PATH
    The path to the storage for disk N of the instance. This might be
    either a block device or a regular file, in which case the OS
    scripts should use ``losetup`` (if they need to mount it). E.g. the
    first disk of the instance might be exported as
    ``DISK_0_PATH=/dev/drbd0``. If the disk is only accessible via a
    userspace URI, this not be set.

DISK_%N_URI
    The userspace URI to the storage for disk N of the instance, if
    configured.

DISK_%N_ACCESS
    This is how the hypervisor will export the instance disks: either
    read-write (``rw``) or read-only (``ro``).

DISK_%N_UUID
    The uuid associated with the N-th disk of the instance.

DISK_%N_NAME
    (Optional) The name, if any, associated with the N-th disk of the instance.

DISK_%N_FRONTEND_TYPE
    (Optional) If applicable to the current hypervisor type: the type
    of the device exported by the hypervisor. For example, the Xen HVM
    hypervisor can export disks as either ``paravirtual`` or
    ``ioemu``.

DISK_%N_BACKEND_TYPE
    How files are visible on the node side. This can be either
    ``block`` (when using block devices) or ``file:type``, where
    ``type`` is either ``loop``, ``blktap`` or ``blktap2``, depending on how the
    hypervisor will be configured.  Note that not all backend types apply to all
    hypervisors.

NIC_COUNT
    Similar to the ``DISK_COUNT``, this represents the number of NICs
    of the instance.

NIC_%N_MAC
    The MAC address associated with this interface.

NIC_%N_UUID
    The uuid associated with the N-th NIC of the instance.

NIC_%N_NAME
    (Optional) The name, if any, associated with the N-th NIC of the instance.

NIC_%N_IP
    The IP address, if any, associated with the N-th NIC of the
    instance.

NIC_%N_MODE
    The NIC mode, routed, bridged or openvswitch

NIC_%N_BRIDGE
    The bridge to which this NIC will be attached. This variable is
    defined only when the NIC is in bridged mode.

NIC_%N_LINK
    In bridged or openvswitch mode, this is the interface to which the
    NIC will be attached (same as ``NIC_%N_BRIDGE`` for bridged). In
    routed mode it is the routing table which will be used by the
    hypervisor to insert the appropriate routes.

NIC_%N_FRONTEND_TYPE
    (Optional) If applicable, the type of the exported NIC to the
    instance, this can be one of: ``rtl8139``, ``ne2k_pci``,
    ``ne2k_isa``, ``paravirtual``.

NIC_%d_NETWORK_NAME
    (Optional) If a NIC network is specified, the network's name.

NIC_%d_NETWORK_UUID
    (Optional) If a NIC network is specified, the network's uuid.

NIC_%d_NETWORK_FAMILY
    (Optional) If a NIC network is specified, the network's family.

NIC_%d_NETWORK_SUBNET
    (Optional) If a NIC network is specified, the network's IPv4 subnet.

NIC_%d_NETWORK_GATEWAY
    (Optional) If a NIC network is specified, the network's IPv4
    gateway.

NIC_%d_NETWORK_SUBNET6
    (Optional) If a NIC network is specified, the network's IPv6 subnet.

NIC_%d_NETWORK_GATEWAY6
    (Optional) If a NIC network is specified, the network's IPv6
    gateway.

NIC_%d_NETWORK_MAC_PREFIX
    (Optional) If a NIC network is specified, the network's mac prefix.

NIC_%d_NETWORK_TAGS
    (Optional) If a NIC network is specified, the network's tags, space
    separated.

OSP_*name*
    Each OS parameter (see below) will be exported in its own
    variable, prefixed with ``OSP_``, and upper-cased. For example, a
    ``dhcp`` parameter will be exported as ``OSP_DHCP``.

DEBUG_LEVEL
    If non-zero, this should cause the OS script to generate verbose
    logs of its execution, for troubleshooting purposes. Currently
    only ``0`` and ``1`` are valid values.


EXECUTABLE SCRIPTS
------------------


create
~~~~~~

The **create** command is used for creating a new instance from
scratch. It has no additional environment variables bside the
common ones.

The ``INSTANCE_NAME`` variable denotes the name of the instance,
which is guaranteed to resolve to an IP address. The create script
should configure the instance according to this name. It can
configure the IP statically or not, depending on the deployment
environment.

The ``INSTANCE_REINSTALL`` variable is set to ``1`` when this create
request is reinstalling an existing instance, rather than creating
a new one. This can be used, for example, to preserve some data in the
old instance in an OS-specific way.

export
~~~~~~

This command is used in order to make a backup of a given disk of
the instance. The command should write to stdout a dump of the
given block device. The output of this program will be passed
during restore to the **import** command.

The specific disk to backup is denoted by four additional environment
variables:

EXPORT_INDEX
    The index in the instance disks structure (and could be used for
    example to skip the second disk if not needed for backup).

EXPORT_DISK_PATH
    Alias for ``DISK_N_PATH``. It is duplicated here for easier usage
    by shell scripts (rather than parse the ``DISK_...`` variables).

EXPORT_DISK_URI
    Alias for ``DISK_N_URI``, analagous to ``EXPORT_DISK_PATH``.

EXPORT_DEVICE
    Historical alias for ``EXPORT_DISK_PATH``.

To provide the user with an estimate on how long the export will take,
a predicted size can be written to the file descriptor passed in the
variable ``EXP_SIZE_FD``. The value is in bytes and must be terminated
by a newline character (``\n``). Older versions of Ganeti don't
support this feature, hence the variable should be checked before
use. Example::

    if test -n "$EXP_SIZE_FD"; then
      blockdev --getsize64 $blockdev >&$EXP_SIZE_FD
    fi

import
~~~~~~

The **import** command is used for restoring an instance from a
backup as done by **export**. The arguments are the similar to
those passed to **export**, whose output will be provided on
stdin.

The difference in variables is that the current disk is denoted by
``IMPORT_DISK_PATH``, ``IMPORT_DISK_URI``, ``IMPORT_DEVICE`` and
``IMPORT_INDEX`` (instead of ``EXPORT_...``).

rename
~~~~~~

This command is used in order to perform a rename at the instance
OS level, after the instance has been renamed in Ganeti. The
command should do whatever steps are required to ensure that the
instance is updated to use the new name, if the operating system
supports it.

Note that it is acceptable for the rename script to do nothing at
all, however be warned that in this case, there will be a
desynchronization between what gnt-instance list shows you and the
actual hostname of the instance.

The script will be passed one additional environment variable
called ``OLD_INSTANCE_NAME`` which holds the old instance name. The
``INSTANCE_NAME`` variable holds the new instance name.

A very simple rename script should at least change the hostname and
IP address of the instance, leaving the administrator to update the
other services.

verify
~~~~~~

The *verify* script is used to verify consistency of the OS parameters
(see below). The command should take one or more arguments denoting
what checks should be performed, and return a proper exit code
depending on whether the validation failed or succeeded.

Currently (API version 20), only one parameter is supported:
``parameters``. This should validate the ``OSP_`` variables from the
environment, and output diagnostic messages in case the validation
fails.

For the ``dhcp`` parameter given as example above, a verification
script could be:

.. code-block:: bash

    #!/bin/sh

    case $OSP_DHCP in
      ""|yes|no)
          ;;
      *)
        echo "Invalid value '$OSP_DHCP' for the dhcp parameter" 1>&2
        exit 1;
        ;;
    esac

    exit 0


TEXT FILES
----------


ganeti_api_version
~~~~~~~~~~~~~~~~~~

The ganeti_api_version file is a plain text file containing the
version(s) of the guest OS API that this OS definition complies
with, one per line. The version documented by this man page is 20,
so this file must contain the number 20 followed by a newline if
only this version is supported. A script compatible with more than
one Ganeti version should contain the most recent version first
(i.e. 20), followed by the old version(s) (in this case 15 and/or
10).

variants.list
~~~~~~~~~~~~~

variants.list is a plain text file containing all the declared supported
variants for this OS, one per line. If this file is missing or empty,
then the OS won't be considered to support variants.

Empty lines and lines starting with a hash (``#``) are ignored.

parameters.list
~~~~~~~~~~~~~~~

This file declares the parameters supported by the OS, one parameter
per line, with name and description (space and/or tab separated). For
example::

    dhcp Whether to enable (yes) or disable (no) dhcp
    root_size The size of the root partition, in GiB

The parameters can then be used in instance add or modification, as
follows::

    # gnt-instance add -O dhcp=no,root_size=8 ...


NOTES
-----

Backwards compatibility
~~~~~~~~~~~~~~~~~~~~~~~

Ganeti 2.3 and up is compatible with API versions 10, 15 and 20. The OS
parameters and related scripts (verify) are only supported in
version 20. The variants functionality (variants.list, and OS_VARIANT
env. var) are supported/present only in version 15 and up.

Common behaviour
~~~~~~~~~~~~~~~~

All the scripts should display an usage message when called with a
wrong number of arguments or when the first argument is ``-h`` or
``--help``.

Upgrading from old versions
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Version 15 to 20
^^^^^^^^^^^^^^^^

The ``parameters.list`` file and ``verify`` script have been
added. For no parameters, an empty parameters file and an empty verify
script which returns success can be used.

Version 10 to 15
^^^^^^^^^^^^^^^^

The ``variants.list`` file has been added, so OSes should support at
least one variant, declaring it in that file and must be prepared to
parse the OS_VARIANT environment variable. OSes are free to support more
variants than just the declared ones. Note that this file is optional;
without it, the variants functionality is disabled.

Version 5 to 10
^^^^^^^^^^^^^^^

The method for passing data has changed from command line options
to environment variables, so scripts should be modified to use
these. For an example of how this can be done in a way compatible
with both versions, feel free to look at the debootstrap instance's
common.sh auxiliary script.

Also, instances can have now a variable number of disks, not only
two, and a variable number of NICs (instead of fixed one), so the
scripts should deal with this. The biggest change is in the
import/export, which are called once per disk, instead of once per
instance.

Version 4 to 5
^^^^^^^^^^^^^^

The rename script has been added. If you don't want to do any
changes on the instances after a rename, you can migrate the OS
definition to version 5 by creating the rename script simply as:

.. code-block:: bash

    #!/bin/sh

    exit 0

Note that the script must be executable.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
