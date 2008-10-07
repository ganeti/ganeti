Ganeti 2.0 OS Interface
=======================

.. contents::

Objective
---------

We want to update the Ganeti OS Interface, which allows different operating
systems to be installed on instances in a Ganeti cluster. This interface has
been designed for Ganeti 1.2, and needs some changes to be compatible with the
changes introduced in Ganeti 2.0 (for a more through discussion of those please
check the Cluster Parameters design doc).


Background
----------

The current Ganeti OS interface, version 5, is tailored for Ganeti 1.2. The
interface is composed by a series of scripts which get called with certain
parameters to perform OS-dependent operations on the cluster. The current
scripts are:

create
  called when a new instance is added to the cluster
export
  called to export an instance disk to a stream
import
  called to import from a stream to a new instance
rename
  called to perform the os-specific operations necessary for renaming an
  instance

Currently these scripts suffer from the limitations of Ganeti 1.2: for example
they accept exactly one block and one swap devices to operate on, rather than
any amount of generic block devices, they blindly assume that an instance will
have just one network interface to operate, they can not be configured to
optimise the instance for a particular hypervisor.

Since in Ganeti 2.0 we want to support multiple hypervisors, and a non-fixed
number of network and disks the OS interface need to change to transmit the
appropriate amount of information about an instance to its managing operating
system, when operating on it. Moreover since some old assumptions usually used
in OS scripts are no longer valid we need to re-establish a common knowledge on
what can be assumed and what cannot be regarding Ganeti environment.


Overview
--------

When designing the new OS API our priorities are:
- ease of use
- future extensibility
- ease of porting from the old api
- modularity

As such we want to limit the number of scripts that must be written to support
an OS, and make it easy to share code between them by uniforming their input.
We also will leave the current script structure unchanged, as far as we can,
and make a few of the scripts (import, export and rename) optional. Most
information will be passed to the script through environment variables, for
ease of access and at the same time ease of using only the information a script
needs.


Detailed Design
---------------

The Scripts
~~~~~~~~~~~

As in Ganeti 1.2, every OS which wants to be installed in Ganeti needs to
support the following functionality, through scripts:

create:
  used to create a new instance running that OS. This script should prepare the
  block devices, and install them so that the new OS can boot under the
  specified hypervisor.
export (optional):
  used to export an installed instance using the given OS to a format which can
  be used to import it back into a new instance.
import (optional):
  used to import an exported instance into a new one. This script is similar to
  create, but the new instance should have the content of the export, rather
  than contain a pristine installation.
rename (optional):
  used to perform the internal OS-specific operations needed to rename an
  instance.

If any optional script is not implemented Ganeti will refuse to perform the
given operation on instances using the non-implementing OS. Of course the
create script is mandatory, and it doesn't make sense to support the either the
export or the import operation but not both.

Incompatibilities with 1.2
~~~~~~~~~~~~~~~~~~~~~~~~~~

We expect the following incompatibilities between the OS scripts for 1.2 and
the ones for 2.0:

- Input parameters: in 1.2 those were passed on the command line, in 2.0 we'll
  use environment variables, as there will be a lot more information and not
  all OSes may care about all of it.
- Input/Output: in 1.2 import scripts accepted the instance contents from
  standard input, and export scripts exported it to standard output. This can't
  be done in 2.0 as we can have more than one disk and so we wouldn't have a
  way to distinguish them. A target/source node and directory will be instead
  passed, for the import script to do the correct job. All scripts will get
  nothing in input and are supposed to output only user-relevant messages.
- Scripts are not compulsory: if a script is missing the relevant operations
  will be forbidden for instances of that os. This makes it easier to
  distinguish between unsupported operations and no-op ones (if any).


Input
~~~~~

Rather than using command line flags, as they do now, scripts will accept
inputs from environment variables.  We expect the following input values:

INSTANCE_NAME
  Name of the instance acted on
HYPERVISOR
  The hypervisor the instance should run on (eg. 'xen-pvm', 'xen-hvm', 'kvm')
DISK_COUNT
  The number of disks this instance will have
NIC_COUNT
  The number of nics this instance will have
DISK_<N>_PATH
  Path to the Nth disk.
DISK_<N>_ACCESS
  W if read/write, R if read only. OS scripts are not supposed to touch
  read-only disks, but will be passed them to know.
DISK_<N>_FRONTEND_TYPE
  Type of the disk as seen by the instance. Can be 'scsi', 'ide', 'virtio'
DISK_<N>_BACKEND_TYPE
  Type of the disk as seen from the node. Can be 'block', 'file:loop' or
  'file:blktap'
NIC_<N>_MAC
  Mac address for the Nth network interface
NIC_<N>_IP
  Ip address for the Nth network interface, if available
NIC_<N>_BRIDGE
  Node bridge the Nth network interface will be connected to
NIC_<N>_FRONTEND_TYPE
  Type of the Nth nic as seen by the instance. For example 'virtio', 'rtl8139', etc.
DEBUG_LEVEL
  Whether more out should be produced, for debugging purposes. Currently the
  only valid values are 0 and 1.

These are only the basic variables we are thinking of now, but more may come
during the implementation and they will be documented in the ganeti-os-api man
page. All these variables will be available to all scripts.

Some scripts will need a few more information to work. These will have
per-script variables, such as for example:

NEW_INSTANCE_NAME
  rename: the name the instance should be renamed to.
EXPORT_NODE
  import/export: node where the export should be saved to or sourced from.
EXPORT_PATH
  import/export: the place where exports are/should be saved to.
EXPORT_COMPRESSION
  import/export: the type of compression for the exports.

(Rationale for the EXPORT_NODE, EXPORT_PATH decision: giving always a local
path would require either copying exports around, which takes a lot of
time/resources or depending on some type of remote filesystem to mount
resources on different nodes, which would add even more complexity to the
ganeti code, and can be added later, if really needed.)

(Rationale for INSTANCE_NAME as an environment variable: the instance name is
always needed and we could pass it on the command line. On the other hand,
though, this would force scripts to both access the environment and parse the
command line, so we'll move it for uniformity.)


Output/Behaviour
~~~~~~~~~~~~~~~~

As discussed scripts should only send user-targeted information to stdout. The
create and import scripts are supposed to format/initialise the given block
devices and install the correct instance data. The export script is supposed to
export instance data to a target node in a format understandable by the the
import script. The rename script should only modify the instance's knowledge of
what its name is.

Other declarative style features
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

As for Ganeti 1.2 OS specifications will need to provide a 'ganeti_api_version'
with a number matching the version of the api they implement. Ganeti itself
will always be compatible with one version of the API and may maintain
retrocompatibility if it's feasible to do so.

In addition to that an OS will be able to declare that it does support only a
subset of the ganeti hypervisors, by declaring them in the 'hypervisors' file.


Caveats/Notes
-------------

We might want to have a "default" import/export behaviour that just dumps all
disks and restores them. This can save work as most systems will just do this,
while allowing flexibility for different systems.

Environment variables are limited in size, but we expect that there will be
enough space to store the information we need. If we discover that this is not
the case we may want to go to a more complex API such as storing those
information on the filesystem and providing the OS script with the path to a
file where they are encoded in some format.
