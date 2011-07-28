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

There are no limitations regarding hard drive images used, as long as
the description is provided. Any hardware described in a proper
i.e. CIM - Common Information Model) format is accepted, although
there is no guarantee that every virtualization software will support
all types of hardware.

OVF package should contain one file with ``.ovf`` extension, which is an
XML file specifying the following (per virtual machine):

- virtual disks
- network description
- list of virtual hardware
- operating system, if any

Each of the elements in ``.ovf`` file may, if desired, contain a
human-readable description to every piece of information given.

Additionally, the package may have some disk image files and other
additional resources (e.g. ISO images).

Supported disk formats
----------------------

Although OVF is claimed to support 'any disk format', what we are
interested in is which of the formats are supported by VM managers
that currently use OVF.

- VMWare: ``.vmdk`` (which comes in at least 3 different flavours:
  ``sparse``, ``compressed`` and ``streamOptimized``)
- VirtualBox: ``.vdi`` (VirtualBox's format), ``.vmdk``, ``.vhd``
  (Microsoft and XenServer); export disk format is always ``.vmdk``
- XenServer: ``.vmdk``, ``.vhd``; export disk format is always
  ``.vhd``
- Red Hat Enterprise Virtualization: ``.raw`` (raw disk format),
  ``.cow`` (qemu's ``QCOW2``)
- other: AbiCloud, OpenNode Cloud, SUSE Studio, Morfeo Claudia,
  OpenStack

In our implementation of the OVF we plan to allow a choice between
raw, cow and vmdk disk formats for both import and export. The
justification is the following:

- Raw format is supported as it is the main format of disk images used
  in Ganeti, thus it is effortless to provide support for this format
- Cow is used in Qemu, [TODO: ..why do we support it, again? That is,
  if we do?]
- Vmdk is most commonly supported in virtualization software, it also
  has the advantage of producing relatively small disk images, which
  is extremely important advantage when moving instances.

The conversion between RAW and the other formats will be done using
qemu-img, which transforms, among other, raw disk images to monolithic
sparse vmdk images.

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
            <gnt:OSParameters></gnt:OSParameters>
            <gnt:Hypervisor>
                <gnt:HypervisorParameters>
                </gnt:HypervisorParameters>
            </gnt:Hypervisor>
        </gnt:GanetiSection>
    </Envelope>

.. note ::
    Tags with ``gnt:`` prefix are Ganeti-specific and are not a part of
    OVF standard.

.. highlight:: text

Whereas Ganeti's export info is of the following form, ``=>`` showing
where will the data be in OVF format::

  [instance]
      disk0_dump = filename     => References
      disk0_ivname = name       => ignored
      disk0_size = size_in_mb   => DiskSection
      disk_count = number       => ignored
      disk_template = disk_type => References
      hypervisor = hyp-name     => gnt:HypervisorSection
      name = inst-name          => Name in VirtualSystem
      nic0_ip = ip              => Item in VirtualHardwareSection
      nic0_link = link          => Item in VirtualHardwareSection
      nic0_mac = mac            => Item in VirtualHardwareSection
      nic0_mode = mode          => Network in NetworkSection
      nic_count = number        => ignored
      tags                      => gnt:Tags

  [backend]
      auto_balanced             => gnt:AutoBalance
      memory = mem_in_mb        => Item in VirtualHardwareSection
      vcpus = number            => Item in VirtualHardwareSection

  [export]
      compression               => DiskSection
      os                        => OperatingSystemSection
      source                    => ignored
      timestamp                 => ignored
      version                   => gnt:VersionId

  [os]                          => gnt:OSParameters

  [hypervisor]                  => gnt:HypervisorParameters

In case of multiple networks/disks used by an instance, they will
all be saved in appropriate sections as specified above for the first
network/disk.

Import from other virtualization software
-----------------------------------------
In case of importing to Ganeti OVF package generated in other software,
e.g. VirtualBox, some fields required for Ganeti to properly handle
import may be missing. Most often it will happen that such OVF package
will lack the ``gnt:GanetiSection``.

If this happens, the tool will simply ask for all the necessary
information or otherwise you can specify all the missing parameters in
the command line. For the latter, please refer to [TODO: reference to
command line options]

Export to other virtualization software
---------------------------------------
When exporting to other virtualization software, you may notice that
there is a section ``gnt:GanetiSection``, containing Ganeti-specific
information. This may on **rare** cases cause trouble in importing your
instance. If that is the case please do one of the two:

1. Export from Ganeti to OVF with ``--external`` option - this will
cause to skip the non-standard information.

2. Manually remove the gnt:GanetiSection from the ``.ovf`` file. You
will also have to recompute sha1 sum (``sha1sum`` command) and update
your ``.mf`` file with new value.

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
unsupported element will be to ignore this element's tag and inform
the user on console output, if possible - without interruption of the
import process.

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

As mentioned, Ganeti will allow exporting only ``raw``, ``cow`` and
``vmdk`` formats.  As for import, we will support all that
``qemu-img`` can convert to raw format. At this point this means
``raw``, ``cow``, ``qcow``, ``qcow2``, ``vmdk`` and ``cloop``.  We do
not plan for now to support ``vdi`` or ``vhd``.

We plan to support compression both for import and export - in tar.gz
format. There is also a possibility to provide virtual disk in chunks
of equal size.

When no ``ovf:format`` tag is provided during import, we assume that
the disk is to be created on import and proceed accordingly.

Network
-------

There are no known limitations regarding network support.

Hardware
--------

TODO

Operating Systems
-----------------

TODO

Other
-----


Implementation details
======================

TODO

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
