=======
Hotplug
=======

:Created: 2013-Jul-24
:Status: Implemented
:Ganeti-Version: 2.10.0

.. contents:: :depth: 4

This is a design document detailing the implementation of device
hotplugging in Ganeti. The logic used is hypervisor agnostic but still
the initial implementation will target the KVM hypervisor. The
implementation adds ``python-fdsend`` as a new dependency. In case
it is not installed hotplug will not be possible and the user will
be notified with a warning.


Current state and shortcomings
==============================

Currently, Ganeti supports addition/removal/modification of devices
(NICs, Disks) but the actual modification takes place only after
rebooting the instance. To this end an instance cannot change network,
get a new disk etc. without a hard reboot.

Until now, in case of KVM hypervisor, code does not name devices nor
places them in specific PCI slots. Devices are appended in the KVM
command and Ganeti lets KVM decide where to place them. This means that
there is a possibility a device that resides in PCI slot 5, after a
reboot (due to another device removal) to be moved to another PCI slot
and probably get renamed too (due to udev rules, etc.).

In order for a migration to succeed, the process on the target node
should be started with exactly the same machine version, CPU
architecture and PCI configuration with the running process. During
instance creation/startup ganeti creates a KVM runtime file with all the
necessary information to generate the KVM command. This runtime file is
used during instance migration to start a new identical KVM process. The
current format includes the fixed part of the final KVM command, a list
of NICs', and hvparams dict. It does not favor easy manipulations
concerning disks, because they are encapsulated in the fixed KVM
command.


Proposed changes
================

For the case of the KVM hypervisor, QEMU exposes 32 PCI slots to the
instance. Disks and NICs occupy some of these slots. Recent versions of
QEMU have introduced monitor commands that allow addition/removal of PCI
devices. Devices are referenced based on their name or position on the
virtual PCI bus. To be able to use these commands, we need to be able to
assign each device a unique name.

To keep track where each device is plugged into, we add the
``pci`` slot to Disk and NIC objects, but we save it only in runtime
files, since it is hypervisor specific info. This is added for easy
object manipulation and is ensured not to be written back to the config.

We propose to make use of QEMU 1.7 QMP commands so that
modifications to devices take effect instantly without the need for hard
reboot.

Upon hotplugging the PCI configuration of an instance is changed.
Runtime files should be updated correspondingly. Currently this is
impossible in case of disk hotplug because disks are included in command
line entry of the runtime file, contrary to NICs that are correctly
treated separately. We change the format of runtime files, we remove
disks from the fixed KVM command and create new entry containing them
only. KVM options concerning disk are generated during
``_ExecuteKVMCommand()``, just like NICs.

Design decisions
================

Which should be each device ID? Currently KVM does not support arbitrary
IDs for devices; supported are only names starting with a letter, max 32
chars length, and only including '.' '_' '-' special chars.
For debugging purposes and in order to be more informative, device will be
named after: <device type>-<part of uuid>-pci-<slot>.

Who decides where to hotplug each device? As long as this is a
hypervisor specific matter, there is no point for the master node to
decide such a thing. Master node just has to request noded to hotplug a
device. To this end, hypervisor specific code should parse the current
PCI configuration (i.e. ``query-pci`` QMP command), find the first
available slot and hotplug the device. Having noded to decide where to
hotplug a device we ensure that no error will occur due to duplicate
slot assignment (if masterd keeps track of PCI reservations and noded
fails to return the PCI slot that the device was plugged into then next
hotplug will fail).

Where should we keep track of devices' PCI slots? As already mentioned,
we must keep track of devices PCI slots to successfully migrate
instances. First option is to save this info to config data, which would
allow us to place each device at the same PCI slot after reboot. This
would require to make the hypervisor return the PCI slot chosen for each
device, and storing this information to config data. Additionally the
whole instance configuration should be returned with PCI slots filled
after instance start and each instance should keep track of current PCI
reservations. We decide not to go towards this direction in order to
keep it simple and do not add hypervisor specific info to configuration
data (``pci_reservations`` at instance level and ``pci`` at device
level). For the aforementioned reason, we decide to store this info only
in KVM runtime files.

Where to place the devices upon instance startup? QEMU has by default 4
pre-occupied PCI slots. So, hypervisor can use the remaining ones for
disks and NICs. Currently, PCI configuration is not preserved after
reboot.  Each time an instance starts, KVM assigns PCI slots to devices
based on their ordering in Ganeti configuration, i.e. the second disk
will be placed after the first, the third NIC after the second, etc.
Since we decided that there is no need to keep track of devices PCI
slots, there is no need to change current functionality.

How to deal with existing instances? Hotplug depends on runtime file
manipulation. It stores there pci info and every device the kvm process is
currently using. Existing files have no pci info in devices and have block
devices encapsulated inside kvm_cmd entry. Thus hotplugging of existing devices
will not be possible. Still migration and hotplugging of new devices will
succeed. The workaround will happen upon loading kvm runtime: if we detect old
style format we will add an empty list for block devices and upon saving kvm
runtime we will include this empty list as well. Switching entirely to new
format will happen upon instance reboot.


Configuration changes
---------------------

The ``NIC`` and ``Disk`` objects get one extra slot: ``pci``. It refers to
PCI slot that the device gets plugged into.

In order to be able to live migrate successfully, runtime files should
be updated every time a live modification (hotplug) takes place. To this
end we change the format of runtime files. The KVM options referring to
instance's disks are no longer recorded as part of the KVM command line.
Disks are treated separately, just as we treat NICs right now. We insert
and remove entries to reflect the current PCI configuration.


Backend changes
---------------

Introduce one new RPC call:

- hotplug_device(DEVICE_TYPE, ACTION, device, ...)

where DEVICE_TYPE can be either NIC or Disk, and ACTION either REMOVE or ADD.

Hypervisor changes
------------------

We implement hotplug on top of the KVM hypervisor. We take advantage of
QEMU 1.7 QMP commands (``device_add``, ``device_del``,
``blockdev-add``, ``netdev_add``, ``netdev_del``). Since ``drive_del``
is not yet implemented in QMP we use the one of HMP. QEMU
refers to devices based on their id. We use ``uuid`` to name them
properly. If a device is about to be hotplugged we parse the output of
``query-pci`` and find the occupied PCI slots. We choose the first
available and the whole device object is appended to the corresponding
entry in the runtime file.

Concerning NIC handling, we build on the top of the existing logic
(first create a tap with _OpenTap() and then pass its file descriptor to
the KVM process). To this end we need to pass access rights to the
corresponding file descriptor over the QMP socket (UNIX domain
socket). The open file is passed as a socket-level control message
(SCM), using the ``fdsend`` python library.


User interface
--------------

The new ``--no-hotplug`` option to gnt-instance modify is introduced, which
skips live modifications.


Enabling hotplug
++++++++++++++++

Hotplug is enabled by default for gnt-instance modify if it is supported.
For existing instance, after installing a version that supports hotplugging we
have the restriction that hotplug will not be supported for existing
devices. The reason is that old runtime files lack of:

1. Device pci configuration info.

2. Separate block device entry.

Hotplug will be supported only for KVM in the first implementation. For
all other hypervisors, backend will raise an Exception case hotplug is
requested.


NIC Hotplug
+++++++++++

The user can add/modify/remove NICs either with hotplugging or not. If a
NIC is to be added a tap is created first and configured properly with
kvm-vif-bridge script. Then the instance gets a new network interface.
Since there is no QEMU monitor command to modify a NIC, we modify a NIC
by temporary removing the existing one and adding a new with the new
configuration. When removing a NIC the corresponding tap gets removed as
well.

::

 gnt-instance modify --net add test
 gnt-instance modify --net 1:mac=aa:00:00:55:44:33 test
 gnt-instance modify --net 1:remove test


Disk Hotplug
++++++++++++

The user can add and remove disks with hotplugging or not. QEMU monitor
supports resizing of disks, however the initial implementation will
support only disk addition/deletion.

::

 gnt-instance modify --disk add:size=1G test
 gnt-instance modify --disk 1:remove test


Dealing with chroot and uid pool (and disks in general)
-------------------------------------------------------

The design so far covers all issues that arise without addressing the
case where the kvm process will not run with root privileges.
Specifically:

- in case of chroot, the kvm process cannot see the newly created device

- in case of uid pool security model, the kvm process is not allowed
  to access the device

For NIC hotplug we address this problem by using the ``getfd`` QMP
command and passing the file descriptor to the kvm process over the
monitor socket using SCM_RIGHTS. For disk hotplug and in case of uid
pool we can let the hypervisor code temporarily ``chown()`` the  device
before the actual hotplug. Still this is insufficient in case of chroot.
In this case, we need to ``mknod()`` the device inside the chroot. Both
workarounds can be avoided, if we make use of the ``add-fd``
QMP command, that was introduced in version 1.7. This command is the
equivalent of NICs' `get-fd`` for disks and will allow disk hotplug in
every case. So, if the QMP does not support the ``add-fd``
command, we will not allow disk hotplug
and notify the user with the corresponding warning.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
