==============================================================
Ganeti Instance Import/Export using Open Virtualization Format
==============================================================

Background
==========

Open Virtualization Format is an open standard for packaging
information regarding virtual machines. It is used, among other, by
VMWare, VirtualBox and XenServer. OVF allows users to migrate between
virtualization software without the need of reconfiguring hardware,
network or operating system.

Currently, exporting instance in Ganeti results with a configuration
file that is readable only for Ganeti. It disallows the users to
change the platform they use without loosing all the machine's
configuration.  Import function in Ganeti is also currently limited to
the previously prepared instances.

Implementation of OVF support allows users to migrate to Ganeti from
other platforms, thus potentially increasing the usage. It also
enables virtual machine end-users to create their own machines
(e.g. in VirtualBox or SUSE Studio) and then add them to Ganeti
cluster, thus providing better personalization.

Overview
========

Open Virtualization Format description
--------------------------------------

According to the DMTF document introducing the standard: "The Open
Virtualization Format (OVF) Specification describes an open, secure,
portable, efficient and extensible format for the packaging and
distribution of software to be run in virtual machines."  OVF supports
both single and multiple- configurations of VMs in one package, is
host- and virtualization platform-independent and optimized for
distribution (e.g. by allowing usage of public key infrastructure and
providing tools for management of basic software licensing).

There are no limitations regarding disk images used, as long as the
description is provided. Any hardware described in a proper format
(i.e. CIM - Common Information Model) is accepted, although there is no
guarantee that every virtualization software will support all types of
hardware.

OVF package should contain exactly one file with ``.ovf`` extension,
which is an XML file specifying the following (per virtual machine):

- virtual disks
- network description
- list of virtual hardware
- operating system, if any

Each of the elements in ``.ovf`` file may, if desired, contain a
human-readable description to every piece of information given.

Additionally, the package may have some disk image files and other
additional resources (e.g. ISO images).

In order to provide secure means of distribution for OVF packages, the
manifest and certificate are provided. Manifest (``.mf`` file) contains
checksums for all the files in OVF package, whereas certificate
(``.cert`` file) contains X.509 certificate and a checksum of manifest
file. Both files are not compulsory, but certificate requires manifest
to be present.

Supported disk formats
----------------------

Although OVF is claimed to support 'any disk format', what we are
interested in is which formats are supported by VM managers that
currently use OVF.

- VMWare: ``.vmdk`` (which comes in at least 3 different flavours:
  ``sparse``, ``compressed`` and ``streamOptimized``)
- VirtualBox: ``.vdi`` (VirtualBox's format), ``.vmdk``, ``.vhd``
  (Microsoft and XenServer); export disk format is always ``.vmdk``
- XenServer: ``.vmdk``, ``.vhd``; export disk format is always
  ``.vhd``
- Red Hat Enterprise Virtualization: ``.raw`` (raw disk format),
  ``.cow`` (qemu's ``QCOW2``)
- other: AbiCloud, OpenNode Cloud, SUSE Studio, Morfeo Claudia,
  OpenStack: mostly ``.vmdk``

In our implementation of the OVF we allow a choice between raw, cow and
vmdk disk formats for both import and export. Other formats covertable
using ``qemu-img`` are allowed in import mode, but not tested.
The justification is the following:

- Raw format is supported as it is the main format of disk images used
  in Ganeti, thus it is effortless to provide support for this format
- Cow is used in Qemu
- Vmdk is most commonly supported in virtualization software, it also
  has the advantage of producing relatively small disk images, which
  is extremely important advantage when moving instances.

Import and export - the closer look
===================================

This section contains an overview of how different parts of
Ganeti's export info are included in ``.ovf`` configuration file.
It also explains how import is designed to work with incomplete
information.

Ganeti's backup format vs OVF
-----------------------------
.. highlight:: xml

The basic structure of Ganeti ``.ovf`` file is the following::

    <Envelope>
        <References></References>
        <DiskSection></DiskSection>
        <NetworkSection></NetworkSection>
        <VirtualSystem>
            <Name></Name>
            <OperatingSystemSection></OperatingSystemSection>
            <VirtualHardwareSection><VirtualHardwareSection>
        </VirtualSystem>
        <gnt:GanetiSection>
            <gnt:VersionId/>
            <gnt:AutoBalance/>
            <gnt:Tags></gnt:Tags>
            <gnt:DiskTemplate</gnt:DiskTemplate>
            <gnt:OperatingSystem>
                <gnt:Name/>
                <gnt:Parameters></gnt:Parameters>
            </gnt:OperatingSystem>
            <gnt:Hypervisor>
                <gnt:Name/>
                <gnt:Parameters></gnt:Parameters>
            </gnt:Hypervisor>
            <gnt:Network>
            <gnt:Mode/>
            <gnt:MACAddress/>
            <gnt:Link/>
            <gnt:IPAddress/>
            </gnt:Network>
        </gnt:GanetiSection>
    </Envelope>

.. note ::
    Tags with ``gnt:`` prefix are Ganeti-specific and are not a part of
    OVF standard.

.. highlight:: text

Whereas Ganeti's export info is of the following form, ``=>`` showing
where will the data be in OVF format::

  [instance]
      disk0_dump = filename     => File in References
      disk0_ivname = name       => generated automatically
      disk0_size = size_in_mb   => calculated after disk conversion
      disk_count = number       => generated automatically
      disk_template = disk_type => gnt:DiskTemplate
      hypervisor = hyp-name     => gnt:Name in gnt:Hypervisor
      name = inst-name          => Name in VirtualSystem
      nic0_ip = ip              => gnt:IPAddress in gnt:Network
      nic0_link = link          => gnt:Link in gnt:Network
      nic0_mac = mac            => gnt:MACAddress in gnt:Network or
                                   Item in VirtualHardwareSection
      nic0_mode = mode          => gnt:Mode in gnt:Network
      nic_count = number        => generated automatically
      tags                      => gnt:Tags

  [backend]
      auto_balanced             => gnt:AutoBalance
      memory = mem_in_mb        => Item in VirtualHardwareSection
      vcpus = number            => Item in VirtualHardwareSection

  [export]
      compression		=> ignored
      os                        => gnt:Name in gnt:OperatingSystem
      source                    => ignored
      timestamp                 => ignored
      version                   => gnt:VersionId or
                                   constants.EXPORT_VERSION

  [os]                          => gnt:Parameters in gnt:OperatingSystem

  [hypervisor]                  => gnt:Parameters in gnt:Hypervisor

In case of multiple networks/disks used by an instance, they will
all be saved in appropriate sections as specified above for the first
network/disk.

Import from other virtualization software
-----------------------------------------
In case of importing to Ganeti OVF package generated in other software,
e.g. VirtualBox, some fields required for Ganeti to properly handle
import may be missing. Most often it will happen that such OVF package
will lack the ``gnt:GanetiSection``.

If this happens you can specify all the missing parameters in
the command line. Please refer to `Command Line`_ section.

In the :doc:`ovfconverter` we provide examples of
options when converting from VirtualBox, VMWare and OpenSuseStudio.

Export to other virtualization software
---------------------------------------
When exporting to other virtualization software, you may notice that
there is a section ``gnt:GanetiSection``, containing Ganeti-specific
information. This may on **rare** cases cause trouble in importing your
instance. If that is the case please do one of the two:

1. Export from Ganeti to OVF with ``--external`` option - this will
cause to skip the non-standard information.

2. Manually remove the gnt:GanetiSection from the ``.ovf`` file. You
will also have to recompute sha1 sum (``sha1sum`` command) of the .ovf
file and update your ``.mf`` file with new value.

.. note::
    Manual change option is only recommended when you have exported your
    instance with ``-format`` option other that ``raw`` or selected
    ``--compress``. It saves you the time of converting or compressing
    the disk image.

Planned limitations
===================

The limitations regarding import of the OVF instances generated
outside Ganeti will be (in general) the same, as limitations for
Ganeti itself.  The desired behavior in case of encountering
unsupported element will be to ignore this element's tag without
interruption of the import process.

Package
-------

There are no limitations regarding support for multiple files in
package or packing the OVF package into one OVA (Open Virtual
Appliance) file. As for certificates and licenses in the package,
their support will be under discussion after completion of the basic
features implementation.

Multiple Virtual Systems
------------------------

At first only singular instances (i.e. VirtualSystem, not
VirtualSystemCollection) will be supported. In the future multi-tiered
appliances containing whole nodes (or even clusters) are considered an
option.

Disks
-----

As mentioned, Ganeti will allow export in  ``raw``, ``cow`` and ``vmdk``
formats.  This means i.e. that the appropriate ``ovf:format``
will be provided.
As for import, we will support all formats that ``qemu-img`` can convert
to ``raw``. At this point this means ``raw``, ``cow``, ``qcow``,
``qcow2``, ``vmdk`` and ``cloop``.  We do not plan for now to support
``vdi`` or ``vhd`` unless they become part of qemu-img supported formats.

We plan to support compression both for import and export - in gzip
format. There is also a possibility to provide virtual disk in chunks
of equal size. The latter will not be implemented in the first version,
but we do plan to support it eventually.


The ``ovf:format`` tag is not used in our case when importing. Instead
we use ``qemu-img info``, which provides enough information for our
purposes and is better standardized.

Please note, that due to security reasons we require the disk image to
be in the same directory as the ``.ovf`` description file for both
import and export.

In order to completely ignore disk-related information in resulting
config file, please use ``--disk-template=diskless`` option.

Network
-------

Ganeti provides support for routed and bridged mode for the networks.
Since the standard OVF format does not contain any information regarding
used network type, we add our own source of such information in
``gnt:GanetiSection``. In case this additional information is not
present, we perform a simple check - if network name specified in
``NetworkSection`` contains words ``bridged`` or ``routed``, we consider
this to be the network type. Otherwise option ``auto`` is chosen, in
which case the cluster's default value for that field will be used when
importing.
This provides a safe fallback in case of NAT networks usage, which are
commonly used e.g. in VirtualBox.

Hardware
--------

The supported hardware is limited to virtual CPUs, RAM memory, disks and
networks. In particular, no USB support is currently provided, as Ganeti
does not support them.

Operating Systems
-----------------

Support for different operating systems depends solely on their
accessibility for Ganeti instances. List of installed OSes can be
checked using ``gnt-os list`` command.

References
----------

Files listed in ``ovf:References`` section cannot be hyperlinks.

Other
-----

The instance name (``gnt:VirtualSystem\gnt:Name`` or command line's
``--name`` option ) has to be resolvable in order for successful import
using ``gnt-backup import``.


_`Command Line`
===============

The basic usage of the ovf tool is one of the following::

    ovfconverter import filename
    ovfconverter export --format=<format> filename

This will result in a conversion based solely on the content of provided
file. In case some information required to make the conversion is
missing, an error will occur.

If output directory should be different than the standard Ganeti export
directory (usually ``/srv/ganeti/export``), option ``--output-dir``
can be used.

If name of resulting entity should be different than the one read from
the file, use ``--name`` option.

Import options
--------------

Import options that ``ovfconverter`` supports include options for
backend, disks, hypervisor, networks and operating system. If an option
is given, it overrides the values provided in the OVF file.

Backend
^^^^^^^
``--backend=option=value`` can be used to set auto balance, number of
vcpus and amount of RAM memory.

Please note that when you do not provide full set of options, the
omitted ones will be set to cluster defaults (``auto``).

Disks
^^^^^
``--disk-template=diskless`` causes the converter to ignore all other
disk option - both from .ovf file and the command line. Other disk
template options include ``plain``, ``drdb``, ``file``, ``sharedfile``
and ``blockdev``.

``--disk=number:size=value`` causes to create disks instead of
converting them from OVF package; numbers should start with ``0`` and be
consecutive.

Hypervisor
^^^^^^^^^^
``-H hypervisor_name`` and ``-H hypervisor_name:option=value``
provide options for hypervisor.

Network
^^^^^^^
``--no-nics`` option causes converter to ignore any network information
provided.

``--network=number:option=value`` sets network information according to
provided data, ignoring the OVF package configuration.

Operating System
^^^^^^^^^^^^^^^^
``--os-type=type`` sets os type accordingly, this option is **required**
when importing from OVF instance not created from Ganeti config file.

``--os-parameters`` provides options for chosen operating system.

Tags
^^^^
``--tags=tag1,tag2,tag3`` is a means of providing tags specific for the
instance.


After the conversion is completed, you may use ``gnt-backup import`` to
import the instance into Ganeti.

Example::

	ovfconverter import file.ovf --disk-template=diskless \
          --os-type=lenny-image \
          --backend=vcpus=1,memory=512,auto_balance \
          -H:xen-pvm \
          --net=0:mode=bridged,link=xen-br0 \
          --name=xen.i1
	[...]
	gnt-backup import xen.i1
	[...]
	gnt-instance list

Export options
--------------
Export options include choice of disk formats to convert the disk image
(``--format``) and compression of the disk into gzip format
(``--compress``). User has also the choice of allowing to skip the
Ganeti-specific part of the OVF document (``--external``).

By default, exported OVF package will not be contained in the OVA
package, but this may be changed by adding ``--ova`` option.

Please note that in order to create an OVF package, it is first
required that you export your VM using ``gnt-backup export``.

Example::

	gnt-backup export -n node1.xen xen.i1
	[...]
	ovfconverter export --format=vmdk --ova --external \
	  --output-dir=~/xen.i1 \
	  /srv/ganeti/export/xen.i1.node1.xen/config.ini

Implementation details
======================

Disk conversion
---------------

Disk conversion for both import and export is done using external tool
called ``qemu-img``. The same tool is used to determine the type of
disk, as well as its virtual size.


Import
------

Import functionality is implemented using two classes - OVFReader and
OVFImporter.

OVFReader class is used to read the contents of the ``.ovf`` file. Every
action that requires ``.ovf`` file access is done through that class.
It also performs validation of manifest, if one is present.

The result of reading some part of file is typically a dictionary or a
string, containing options which correspond to the ones in
``config.ini`` file. Only in case of disks, the resulting value is
different - it is then a list of disk names. The reason for that is the
need for conversion.

OVFImporter class performs all the command-line-like tasks, such as
unpacking OVA package, removing temporary directory, converting disk
file to raw format or saving the configuration file on disk.
It also contains a set of functions that read the options provided in
the command line.


Typical workflow for the import is very simple:

- read the ``.ovf`` file into memory
- verify manifest
- parse each element of the configuration file: name, disk template,
  hypervisor, operating system, backend parameters, network and disks

    - check if option for the element can be read from command line
      options

		- if yes: parse options from command line

		- otherwise: read the appropriate portion of ``.ovf`` file

- save gathered information in ``config.ini`` file

Export
------

Similar to import, export functionality also uses two classes -
OVFWriter and OVFExporter.

OVFWriter class produces XML output based on the information given. Its
sole role is to separate the creation of ``.ovf`` file content.

OVFExporter class gathers information from ``config.ini`` file or
command line and performs necessary operations like disk conversion, disk
compression, manifest creation and OVA package creation.

Typical workflow for the export is even simpler, than for the import:

- read the ``config.ini`` file into memory
- gather information about certain parts of the instance, convert and
  compress disks if desired
- save each of these elements as a fragment of XML tree
- save the XML tree as ``.ovf`` file
- create manifest file and fill it with appropriate checksums
- if ``--ova`` option was chosen, pack the results into ``.ova`` tarfile


Work in progress
----------------

- conversion to/from raw disk should be quicker
- add graphic card memory to export information (12 MB of memory)
- space requirements for conversion + compression + ova are currently
  enormous
- add support for disks in chunks
- add support for certificates
- investigate why VMWare's ovftool does not work with ovfconverter's
  compression and ova packaging -- maybe noteworty: if OVA archive does
  not have a disk (i.e. in OVA package there is only .ovf ad .mf file),
  then the ovftool works
- investigate why new versions of VirtualBox have problems with OVF
  created by ovfconverter (everything works fine with 3.16 version, but
  not with 4.0)


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
