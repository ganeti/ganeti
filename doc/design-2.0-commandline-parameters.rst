Ganeti 2.0 commandline arguments
================================

.. contents::

Objective
---------

Ganeti 2.0 introduces several new features as well as new ways to
handle instance resources like disks or network interfaces. This
requires some noticable changes in the way commandline arguments are
handled.

- extend and modify commandline syntax to support new features
- ensure consistent patterns in commandline arguments to reduce cognitive load

Background
----------

Ganeti 2.0 introduces several changes in handling instances resources
such as disks and network cards as well as some new features. Due to
these changes, the commandline syntax needs to be changed
significantly since the existing commandline syntax is not able to
cover the changes.

Overview
--------

Design changes for Ganeti 2.0 that require changes for the commandline
syntax, in no particular order:

- flexible instance disk handling: support a variable number of disks
  with varying properties per instance,
- flexible instance network interface handling: support a variable
  number of network interfaces with varying properties per instance
- multiple hypervisors: multiple hypervisors can be active on the same
  cluster, each supporting different parameters,
- support for device type CDROM (via ISO image)

Detailed Design
---------------

There are several areas of Ganeti where the commandline arguments will change:

- Cluster configuration

  - cluster initialization
  - cluster default configuration

- Instance configuration

  - handling of network cards for instances,
  - handling of disks for instances,
  - handling of CDROM devices and
  - handling of hypervisor specific options.

Notes about device removal/addition
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To avoid problems with device location changes (e.g. second network
interface of the instance becoming the first or third and the like)
the list of network/disk devices is treated as a stack, i.e. devices
can only be added/removed at the end of the list of devices of each
class (disk or network) for each instance.

gnt-instance commands
~~~~~~~~~~~~~~~~~~~~~

The commands for gnt-instance will be modified and extended to allow
for the new functionality:

- the add command will be extended to support the new device and
  hypervisor options,
- the modify command continues to handle all modifications to
  instances, but will be extended with new arguments for handling
  devices.

Network Device Options
~~~~~~~~~~~~~~~~~~~~~~

The generic format of the network device option is:

  --net $DEVNUM[:$OPTION=$VALUE][,$OPTION=VALUE]

:$DEVNUM: device number, unsigned integer, starting at 0,
:$OPTION: device option, string,
:$VALUE: device option value, string.

Currently, the following device options will be defined (open to
further changes):

:mac: MAC address of the network interface, accepts either a valid
  MAC address or the string 'auto'. If 'auto' is specified, a new MAC
  address will be generated randomly. If the mac device option is not
  specified, the default value 'auto' is assumed.
:bridge: network bridge the network interface is connected
  to. Accepts either a valid bridge name (the specified bridge must
  exist on the node(s)) as string or the string 'auto'. If 'auto' is
  specified, the default brigde is used. If the bridge option is not
  specified, the default value 'auto' is assumed.

Disk Device Options
~~~~~~~~~~~~~~~~~~~

The generic format of the disk device option is:

  --disk $DEVNUM:[$OPTION=$VALUE][,$OPTION=VALUE]

:$DEVNUM: device number, unsigned integer, starting at 0,
:$OPTION: device option, string,
:$VALUE: device option value, string.

Currently, the following device options will be defined (open to
further changes):

:size: size of the disk device, either a positive number, specifying
  the disk size in mebibytes, or a number followed by a magnitude suffix
  (M for mebibytes, G for gibibytes). Also accepts the string 'auto' in
  which case the default disk size will be used. If the size option is
  not specified, 'auto' is assumed. This option is not valid for all
  disk layout types.
:access: access mode of the disk device, a single letter, valid values
  are:

  - w: read/write access to the disk device or
  - r: read-only access to the disk device.

  If the access mode is not specified, the default mode of read/write
  access will be configured.
:path: path to the image file for the disk device, string. No default
  exists. This option is not valid for all disk layout types.

Adding devices
~~~~~~~~~~~~~~

To add devices to an already existing instance, use the device type
specific option to gnt-instance modify. Currently, there are two
device type specific options supported:

:--net: for network interface cards
:--disk: for disk devices

The syntax to the device specific options is similiar to the generic
device options, but instead of specifying a device number like for
gnt-instance add, you specify the magic string add. The new device
will always be appended at the end of the list of devices of this type
for the specified instance, e.g. if the instance has disk devices 0,1
and 2, the newly added disk device will be disk device 3.

Example: gnt-instance modify --net add:mac=auto test-instance

Removing devices
~~~~~~~~~~~~~~~~

Removing devices from and instance is done via gnt-instance
modify. The same device specific options as for adding instances are
used. Instead of a device number and further device options, only the
magic string remove is specified. It will always remove the last
device in the list of devices of this type for the instance specified,
e.g. if the instance has disk devices 0, 1, 2 and 3, the disk device
number 3 will be removed.

Example: gnt-instance modify --net remove test-instance

Modifying devices
~~~~~~~~~~~~~~~~~

Modifying devices is also done with device type specific options to
the gnt-instance modify command. There are currently two device type
options supported:

:--net: for network interface cards
:--disk: for disk devices

The syntax to the device specific options is similiar to the generic
device options. The device number you specify identifies the device to
be modified.

Example: gnt-instance modify --disk 2:access=r

Hypervisor Options
~~~~~~~~~~~~~~~~~~

Ganeti 2.0 will support more than one hypervisor. Different
hypervisors have various options that only apply to a specific
hypervisor. Those hypervisor specific options are treated specially
via the --hypervisor option. The generic syntax of the hypervisor
option is as follows:

  --hypervisor $HYPERVISOR:$OPTION=$VALUE[,$OPTION=$VALUE]

:$HYPERVISOR: symbolic name of the hypervisor to use, string,
  has to match the supported hypervisors. Example: xen-3.0

:$OPTION: hypervisor option name, string
:$VALUE: hypervisor option value, string

The hypervisor option for an instance can be set on instance creation
time via the gnt-instance add command. If the hypervisor for an
instance is not specified upon instance creation, the default
hypervisor will be used.

Modifying hypervisor parameters
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The hypervisor parameters of an existing instance can be modified
using --hypervisor option of the gnt-instance modify command. However,
the hypervisor type of an existing instance can not be changed, only
the particular hypervisor specific option can be changed. Therefore,
the format of the option parameters has been simplified to omit the
hypervisor name and only contain the comma separated list of
option-value pairs.

Example: gnt-instance modify --hypervisor
cdrom=/srv/boot.iso,boot_order=cdrom:network test-instance

gnt-cluster commands
~~~~~~~~~~~~~~~~~~~~

The command for gnt-cluster will be extended to allow setting and
changing the default parameters of the cluster:

- The init command will be extend to support the defaults option to
  set the cluster defaults upon cluster initialization.
- The modify command will be added to modify the cluster
  parameters. It will support the --defaults option to change the
  cluster defaults.

Cluster defaults

The generic format of the cluster default setting option is:

  --defaults $OPTION=$VALUE[,$OPTION=$VALUE]

:$OPTION: cluster default option, string,
:$VALUE: cluster default option value, string.

Currently, the following cluster default options are defined (open to
further changes):

:hypervisor: the default hypervisor to use for new instances,
  string. Must be a valid hypervisor known to and supported by the
  cluster.
:disksize: the disksize for newly created instance disks, where
  applicable. Must be either a positive number, in which case the unit
  of megabyte is assumed, or a positive number followed by a supported
  magnitude symbol (M for megabyte or G for gigabyte).
:bridge: the default network bridge to use for newly created instance
  network interfaces, string. Must be a valid bridge name of a bridge
  existing on the node(s).

Hypervisor cluster defaults
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The generic format of the hypervisor clusterwide default setting option is:

  --hypervisor-defaults $HYPERVISOR:$OPTION=$VALUE[,$OPTION=$VALUE]

:$HYPERVISOR: symbolic name of the hypervisor whose defaults you want
  to set, string
:$OPTION: cluster default option, string,
:$VALUE: cluster default option value, string.

