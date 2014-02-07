gnt-instance(8) Ganeti | Version @GANETI_VERSION@
=================================================

Name
----

gnt-instance - Ganeti instance administration

Synopsis
--------

**gnt-instance** {command} [arguments...]

DESCRIPTION
-----------

The **gnt-instance** command is used for instance administration in
the Ganeti system.

COMMANDS
--------

Creation/removal/querying
~~~~~~~~~~~~~~~~~~~~~~~~~

ADD
^^^

| **add**
| {-t|\--disk-template {diskless \| file \| plain \| drbd \| rbd}}
| {\--disk=*N*: {size=*VAL*[,spindles=*VAL*] \| adopt=*LV*}[,options...]
|  \| {size=*VAL*,provider=*PROVIDER*}[,param=*value*... ][,options...]
|  \| {-s|\--os-size} *SIZE*}
| [\--no-ip-check] [\--no-name-check] [\--no-conflicts-check]
| [\--no-start] [\--no-install]
| [\--net=*N* [:options...] \| \--no-nics]
| [{-B|\--backend-parameters} *BEPARAMS*]
| [{-H|\--hypervisor-parameters} *HYPERVISOR* [: option=*value*... ]]
| [{-O|\--os-parameters} *param*=*value*... ]
| [\--file-storage-dir *dir\_path*] [\--file-driver {loop \| blktap \| blktap2}]
| {{-n|\--node} *node[:secondary-node]* \| {-I|\--iallocator} *name*}
| {{-o|\--os-type} *os-type*}
| [\--submit] [\--print-job-id]
| [\--ignore-ipolicy]
| [\--no-wait-for-sync]
| [{-c|\--communication=yes|no}]
| {*instance*}

Creates a new instance on the specified host. The *instance* argument
must be in DNS, but depending on the bridge/routing setup, need not be
in the same network as the nodes in the cluster.

The ``disk`` option specifies the parameters for the disks of the
instance. The numbering of disks starts at zero, and at least one disk
needs to be passed. For each disk, either the size or the adoption
source needs to be given. The size is interpreted (when no unit is
given) in mebibytes. You can also use one of the suffixes *m*, *g* or
*t* to specify the exact the units used; these suffixes map to
mebibytes, gibibytes and tebibytes. Each disk can also take these
parameters (all optional):

spindles
  How many spindles (physical disks on the node) the disk should span.

mode
  The access mode. Either ``ro`` (read-only) or the default ``rw``
  (read-write).

name
   This option specifies a name for the disk, which can be used as a disk
   identifier. An instance can not have two disks with the same name.

vg
   The LVM volume group. This works only for LVM and DRBD devices.

metavg
   This options specifies a different VG for the metadata device. This
   works only for DRBD devices

When creating ExtStorage disks, also arbitrary parameters can be passed,
to the ExtStorage provider. Those parameters are passed as additional
comma separated options. Therefore, an ExtStorage disk provided by
provider ``pvdr1`` with parameters ``param1``, ``param2`` would be
passed as ``--disk 0:size=10G,provider=pvdr1,param1=val1,param2=val2``.

When using the ``adopt`` key in the disk definition, Ganeti will
reuse those volumes (instead of creating new ones) as the
instance's disks. Ganeti will rename these volumes to the standard
format, and (without installing the OS) will use them as-is for the
instance. This allows migrating instances from non-managed mode
(e.g. plain KVM with LVM) to being managed via Ganeti. Please note that
this works only for the \`plain' disk template (see below for
template details).

Alternatively, a single-disk instance can be created via the ``-s``
option which takes a single argument, the size of the disk. This is
similar to the Ganeti 1.2 version (but will only create one disk).

The minimum disk specification is therefore ``--disk 0:size=20G`` (or
``-s 20G`` when using the ``-s`` option), and a three-disk instance
can be specified as ``--disk 0:size=20G --disk 1:size=4G --disk
2:size=100G``.

The minimum information needed to specify an ExtStorage disk are the
``size`` and the ``provider``. For example:
``--disk 0:size=20G,provider=pvdr1``.

The ``--no-ip-check`` skips the checks that are done to see if the
instance's IP is not already alive (i.e. reachable from the master
node).

The ``--no-name-check`` skips the check for the instance name via
the resolver (e.g. in DNS or /etc/hosts, depending on your setup).
Since the name check is used to compute the IP address, if you pass
this option you must also pass the ``--no-ip-check`` option.

If you don't want the instance to automatically start after
creation, this is possible via the ``--no-start`` option. This will
leave the instance down until a subsequent **gnt-instance start**
command.

The NICs of the instances can be specified via the ``--net``
option. By default, one NIC is created for the instance, with a
random MAC, and set up according the the cluster level NIC
parameters. Each NIC can take these parameters (all optional):

mac
    either a value or 'generate' to generate a new unique MAC

ip
    specifies the IP address assigned to the instance from the Ganeti
    side (this is not necessarily what the instance will use, but what
    the node expects the instance to use). Note that if an IP in the
    range of a network configured with **gnt-network**\(8) is used,
    and the NIC is not already connected to it, this network has to be
    passed in the **network** parameter if this NIC is meant to be
    connected to the said network. ``--no-conflicts-check`` can be used
    to override this check. The special value **pool** causes Ganeti to
    select an IP from the the network the NIC is or will be connected to.
    One can pick an externally reserved IP of a network along with
    ``--no-conflict-check``. Note that this IP cannot be assigned to
    any other instance until it gets released.

mode
    specifies the connection mode for this NIC: routed, bridged or
    openvswitch.

link
    in bridged or openvswitch mode specifies the interface to attach
    this NIC to, in routed mode it's intended to differentiate between
    different routing tables/instance groups (but the meaning is
    dependent on the network script, see **gnt-cluster**\(8) for more
    details). Note that openvswitch support is also hypervisor
    dependent.

network
    derives the mode and the link from the settings of the network
    which is identified by its name. If the network option is chosen,
    link and mode must not be specified. Note that the mode and link
    depend on the network-to-nodegroup connection, thus allowing
    different nodegroups to be connected to the same network in
    different ways.

name
   this option specifies a name for the NIC, which can be used as a NIC
   identifier. An instance can not have two NICs with the same name.

vlan
   in openvswitch mode specifies the VLANs that the NIC will be
   connected to. To connect as an access port use ``n`` or ``.n`` with
   **n** being the VLAN ID. To connect as an trunk port use ``:n[:n]``.
   A hybrid port can be created with ``.n:n[:n]``

Of these "mode" and "link" are NIC parameters, and inherit their
default at cluster level.  Alternatively, if no network is desired for
the instance, you can prevent the default of one NIC with the
``--no-nics`` option.

The ``-o (--os-type)`` option specifies the operating system to be
installed.  The available operating systems can be listed with
**gnt-os list**.  Passing ``--no-install`` will however skip the OS
installation, allowing a manual import if so desired. Note that the
no-installation mode will automatically disable the start-up of the
instance (without an OS, it most likely won't be able to start-up
successfully).

The ``-B (--backend-parameters)`` option specifies the backend
parameters for the instance. If no such parameters are specified, the
values are inherited from the cluster. Possible parameters are:

maxmem
    the maximum memory size of the instance; as usual, suffixes can be
    used to denote the unit, otherwise the value is taken in mebibytes

minmem
    the minimum memory size of the instance; as usual, suffixes can be
    used to denote the unit, otherwise the value is taken in mebibytes

vcpus
    the number of VCPUs to assign to the instance (if this value makes
    sense for the hypervisor)

auto\_balance
    whether the instance is considered in the N+1 cluster checks
    (enough redundancy in the cluster to survive a node failure)

always\_failover
    ``True`` or ``False``, whether the instance must be failed over
    (shut down and rebooted) always or it may be migrated (briefly
    suspended)

Note that before 2.6 Ganeti had a ``memory`` parameter, which was the
only value of memory an instance could have. With the
``maxmem``/``minmem`` change Ganeti guarantees that at least the minimum
memory is always available for an instance, but allows more memory to be
used (up to the maximum memory) should it be free.

The ``-H (--hypervisor-parameters)`` option specified the hypervisor
to use for the instance (must be one of the enabled hypervisors on the
cluster) and optionally custom parameters for this instance. If not
other options are used (i.e. the invocation is just -H *NAME*) the
instance will inherit the cluster options. The defaults below show the
cluster defaults at cluster creation time.

The possible hypervisor options are as follows:

boot\_order
    Valid for the Xen HVM and KVM hypervisors.

    A string value denoting the boot order. This has different meaning
    for the Xen HVM hypervisor and for the KVM one.

    For Xen HVM, The boot order is a string of letters listing the boot
    devices, with valid device letters being:

    a
        floppy drive

    c
        hard disk

    d
        CDROM drive

    n
        network boot (PXE)

    The default is not to set an HVM boot order, which is interpreted
    as 'dc'.

    For KVM the boot order is either "floppy", "cdrom", "disk" or
    "network".  Please note that older versions of KVM couldn't netboot
    from virtio interfaces. This has been fixed in more recent versions
    and is confirmed to work at least with qemu-kvm 0.11.1. Also note
    that if you have set the ``kernel_path`` option, that will be used
    for booting, and this setting will be silently ignored.

blockdev\_prefix
    Valid for the Xen HVM and PVM hypervisors.

    Relevant to non-pvops guest kernels, in which the disk device names
    are given by the host.  Allows one to specify 'xvd', which helps run
    Red Hat based installers, driven by anaconda.

floppy\_image\_path
    Valid for the KVM hypervisor.

    The path to a floppy disk image to attach to the instance.  This
    is useful to install Windows operating systems on Virt/IO disks
    because you can specify here the floppy for the drivers at
    installation time.

cdrom\_image\_path
    Valid for the Xen HVM and KVM hypervisors.

    The path to a CDROM image to attach to the instance.

cdrom2\_image\_path
    Valid for the KVM hypervisor.

    The path to a second CDROM image to attach to the instance.
    **NOTE**: This image can't be used to boot the system. To do that
    you have to use the 'cdrom\_image\_path' option.

nic\_type
    Valid for the Xen HVM and KVM hypervisors.

    This parameter determines the way the network cards are presented
    to the instance. The possible options are:

    - rtl8139 (default for Xen HVM) (HVM & KVM)
    - ne2k\_isa (HVM & KVM)
    - ne2k\_pci (HVM & KVM)
    - i82551 (KVM)
    - i82557b (KVM)
    - i82559er (KVM)
    - pcnet (KVM)
    - e1000 (KVM)
    - paravirtual (default for KVM) (HVM & KVM)

vif\_type
    Valid for the Xen HVM hypervisor.

    This parameter specifies the vif type of the nic configuration
    of the instance. Unsetting the value leads to no type being specified
    in the configuration. Note that this parameter only takes effect when
    the 'nic_type' is not set. The possible options are:

    - ioemu
    - vif

disk\_type
    Valid for the Xen HVM and KVM hypervisors.

    This parameter determines the way the disks are presented to the
    instance. The possible options are:

    - ioemu [default] (HVM & KVM)
    - paravirtual (HVM & KVM)
    - ide (KVM)
    - scsi (KVM)
    - sd (KVM)
    - mtd (KVM)
    - pflash (KVM)


cdrom\_disk\_type
    Valid for the KVM hypervisor.

    This parameter determines the way the cdroms disks are presented
    to the instance. The default behavior is to get the same value of
    the earlier parameter (disk_type). The possible options are:

    - paravirtual
    - ide
    - scsi
    - sd
    - mtd
    - pflash


vnc\_bind\_address
    Valid for the Xen HVM and KVM hypervisors.

    Specifies the address that the VNC listener for this instance
    should bind to. Valid values are IPv4 addresses. Use the address
    0.0.0.0 to bind to all available interfaces (this is the default)
    or specify the address of one of the interfaces on the node to
    restrict listening to that interface.

vnc\_password\_file
    Valid for the Xen HVM and KVM hypervisors.

    Specifies the location of the file containing the password for
    connections using VNC. The default is a file named
    vnc-cluster-password which can be found in the configuration
    directory.

vnc\_tls
    Valid for the KVM hypervisor.

    A boolean option that controls whether the VNC connection is
    secured with TLS.

vnc\_x509\_path
    Valid for the KVM hypervisor.

    If ``vnc_tls`` is enabled, this options specifies the path to the
    x509 certificate to use.

vnc\_x509\_verify
    Valid for the KVM hypervisor.

spice\_bind
    Valid for the KVM hypervisor.

    Specifies the address or interface on which the SPICE server will
    listen. Valid values are:

    - IPv4 addresses, including 0.0.0.0 and 127.0.0.1
    - IPv6 addresses, including :: and ::1
    - names of network interfaces

    If a network interface is specified, the SPICE server will be bound
    to one of the addresses of that interface.

spice\_ip\_version
    Valid for the KVM hypervisor.

    Specifies which version of the IP protocol should be used by the
    SPICE server.

    It is mainly intended to be used for specifying what kind of IP
    addresses should be used if a network interface with both IPv4 and
    IPv6 addresses is specified via the ``spice_bind`` parameter. In
    this case, if the ``spice_ip_version`` parameter is not used, the
    default IP version of the cluster will be used.

spice\_password\_file
    Valid for the KVM hypervisor.

    Specifies a file containing the password that must be used when
    connecting via the SPICE protocol. If the option is not specified,
    passwordless connections are allowed.

spice\_image\_compression
    Valid for the KVM hypervisor.

    Configures the SPICE lossless image compression. Valid values are:

    - auto_glz
    - auto_lz
    - quic
    - glz
    - lz
    - off

spice\_jpeg\_wan\_compression
    Valid for the KVM hypervisor.

    Configures how SPICE should use the jpeg algorithm for lossy image
    compression on slow links. Valid values are:

    - auto
    - never
    - always

spice\_zlib\_glz\_wan\_compression
    Valid for the KVM hypervisor.

    Configures how SPICE should use the zlib-glz algorithm for lossy image
    compression on slow links. Valid values are:

    - auto
    - never
    - always

spice\_streaming\_video
    Valid for the KVM hypervisor.

    Configures how SPICE should detect video streams. Valid values are:

    - off
    - all
    - filter

spice\_playback\_compression
    Valid for the KVM hypervisor.

    Configures whether SPICE should compress audio streams or not.

spice\_use\_tls
    Valid for the KVM hypervisor.

    Specifies that the SPICE server must use TLS to encrypt all the
    traffic with the client.

spice\_tls\_ciphers
    Valid for the KVM hypervisor.

    Specifies a list of comma-separated ciphers that SPICE should use
    for TLS connections. For the format, see man **cipher**\(1).

spice\_use\_vdagent
    Valid for the KVM hypervisor.

    Enables or disables passing mouse events via SPICE vdagent.

cpu\_type
    Valid for the KVM hypervisor.

    This parameter determines the emulated cpu for the instance. If this
    parameter is empty (which is the default configuration), it will not
    be passed to KVM.

    Be aware of setting this parameter to ``"host"`` if you have nodes
    with different CPUs from each other. Live migration may stop working
    in this situation.

    For more information please refer to the KVM manual.

acpi
    Valid for the Xen HVM and KVM hypervisors.

    A boolean option that specifies if the hypervisor should enable
    ACPI support for this instance. By default, ACPI is disabled.

    ACPI should be enabled for user shutdown detection.  See
    ``user_shutdown``.

pae
    Valid for the Xen HVM and KVM hypervisors.

    A boolean option that specifies if the hypervisor should enable
    PAE support for this instance. The default is false, disabling PAE
    support.

viridian
    Valid for the Xen HVM hypervisor.

    A boolean option that specifies if the hypervisor should enable
    viridian (Hyper-V) for this instance. The default is false,
    disabling viridian support.

use\_localtime
    Valid for the Xen HVM and KVM hypervisors.

    A boolean option that specifies if the instance should be started
    with its clock set to the localtime of the machine (when true) or
    to the UTC (When false). The default is false, which is useful for
    Linux/Unix machines; for Windows OSes, it is recommended to enable
    this parameter.

kernel\_path
    Valid for the Xen PVM and KVM hypervisors.

    This option specifies the path (on the node) to the kernel to boot
    the instance with. Xen PVM instances always require this, while for
    KVM if this option is empty, it will cause the machine to load the
    kernel from its disks (and the boot will be done accordingly to
    ``boot_order``).

kernel\_args
    Valid for the Xen PVM and KVM hypervisors.

    This options specifies extra arguments to the kernel that will be
    loaded. device. This is always used for Xen PVM, while for KVM it
    is only used if the ``kernel_path`` option is also specified.

    The default setting for this value is simply ``"ro"``, which
    mounts the root disk (initially) in read-only one. For example,
    setting this to single will cause the instance to start in
    single-user mode.

initrd\_path
    Valid for the Xen PVM and KVM hypervisors.

    This option specifies the path (on the node) to the initrd to boot
    the instance with. Xen PVM instances can use this always, while
    for KVM if this option is only used if the ``kernel_path`` option
    is also specified. You can pass here either an absolute filename
    (the path to the initrd) if you want to use an initrd, or use the
    format no\_initrd\_path for no initrd.

root\_path
    Valid for the Xen PVM and KVM hypervisors.

    This options specifies the name of the root device. This is always
    needed for Xen PVM, while for KVM it is only used if the
    ``kernel_path`` option is also specified.

    Please note, that if this setting is an empty string and the
    hypervisor is Xen it will not be written to the Xen configuration
    file

serial\_console
    Valid for the KVM hypervisor.

    This boolean option specifies whether to emulate a serial console
    for the instance. Note that some versions of KVM have a bug that
    will make an instance hang when configured to use the serial console
    unless a connection is made to it within about 2 seconds of the
    instance's startup. For such case it's recommended to disable this
    option, which is enabled by default.

serial\_speed
    Valid for the KVM hypervisor.

    This integer option specifies the speed of the serial console.
    Common values are 9600, 19200, 38400, 57600 and 115200: choose the
    one which works on your system. (The default is 38400 for historical
    reasons, but newer versions of kvm/qemu work with 115200)

disk\_cache
    Valid for the KVM hypervisor.

    The disk cache mode. It can be either default to not pass any
    cache option to KVM, or one of the KVM cache modes: none (for
    direct I/O), writethrough (to use the host cache but report
    completion to the guest only when the host has committed the
    changes to disk) or writeback (to use the host cache and report
    completion as soon as the data is in the host cache). Note that
    there are special considerations for the cache mode depending on
    version of KVM used and disk type (always raw file under Ganeti),
    please refer to the KVM documentation for more details.

security\_model
    Valid for the KVM hypervisor.

    The security model for kvm. Currently one of *none*, *user* or
    *pool*. Under *none*, the default, nothing is done and instances
    are run as the Ganeti daemon user (normally root).

    Under *user* kvm will drop privileges and become the user
    specified by the security\_domain parameter.

    Under *pool* a global cluster pool of users will be used, making
    sure no two instances share the same user on the same node. (this
    mode is not implemented yet)

security\_domain
    Valid for the KVM hypervisor.

    Under security model *user* the username to run the instance
    under.  It must be a valid username existing on the host.

    Cannot be set under security model *none* or *pool*.

kvm\_flag
    Valid for the KVM hypervisor.

    If *enabled* the -enable-kvm flag is passed to kvm. If *disabled*
    -disable-kvm is passed. If unset no flag is passed, and the
    default running mode for your kvm binary will be used.

mem\_path
    Valid for the KVM hypervisor.

    This option passes the -mem-path argument to kvm with the path (on
    the node) to the mount point of the hugetlbfs file system, along
    with the -mem-prealloc argument too.

use\_chroot
    Valid for the KVM hypervisor.

    This boolean option determines whether to run the KVM instance in a
    chroot directory.

    If it is set to ``true``, an empty directory is created before
    starting the instance and its path is passed via the -chroot flag
    to kvm. The directory is removed when the instance is stopped.

    It is set to ``false`` by default.

user\_shutdown
    Valid for the KVM hypervisor.

    This boolean option determines whether the KVM instance suports user
    shutdown detection.  This option does not necessarily require ACPI
    enabled, but ACPI must be enabled for users to poweroff their KVM
    instances.

    If it is set to ``true``, the user can shutdown this KVM instance
    and its status is reported as ``USER_down``.

    It is set to ``false`` by default.

migration\_downtime
    Valid for the KVM hypervisor.

    The maximum amount of time (in ms) a KVM instance is allowed to be
    frozen during a live migration, in order to copy dirty memory
    pages. Default value is 30ms, but you may need to increase this
    value for busy instances.

    This option is only effective with kvm versions >= 87 and qemu-kvm
    versions >= 0.11.0.

cpu\_mask
    Valid for the Xen, KVM and LXC hypervisors.

    The processes belonging to the given instance are only scheduled
    on the specified CPUs.

    The format of the mask can be given in three forms. First, the word
    "all", which signifies the common case where all VCPUs can live on
    any CPU, based on the hypervisor's decisions.

    Second, a comma-separated list of CPU IDs or CPU ID ranges. The
    ranges are defined by a lower and higher boundary, separated by a
    dash, and the boundaries are inclusive. In this form, all VCPUs of
    the instance will be mapped on the selected list of CPUs. Example:
    ``0-2,5``, mapping all VCPUs (no matter how many) onto physical CPUs
    0, 1, 2 and 5.

    The last form is used for explicit control of VCPU-CPU pinnings. In
    this form, the list of VCPU mappings is given as a colon (:)
    separated list, whose elements are the possible values for the
    second or first form above. In this form, the number of elements in
    the colon-separated list _must_ equal the number of VCPUs of the
    instance.

    Example:

    .. code-block:: bash

      # Map the entire instance to CPUs 0-2
      gnt-instance modify -H cpu_mask=0-2 my-inst

      # Map vCPU 0 to physical CPU 1 and vCPU 1 to CPU 3 (assuming 2 vCPUs)
      gnt-instance modify -H cpu_mask=1:3 my-inst

      # Pin vCPU 0 to CPUs 1 or 2, and vCPU 1 to any CPU
      gnt-instance modify -H cpu_mask=1-2:all my-inst

      # Pin vCPU 0 to any CPU, vCPU 1 to CPUs 1, 3, 4 or 5, and CPU 2 to
      # CPU 0 (backslashes for escaping the comma)
      gnt-instance modify -H cpu_mask=all:1\\,3-5:0 my-inst

      # Pin entire VM to CPU 0
      gnt-instance modify -H cpu_mask=0 my-inst

      # Turn off CPU pinning (default setting)
      gnt-instance modify -H cpu_mask=all my-inst

cpu\_cap
    Valid for the Xen hypervisor.

    Set the maximum amount of cpu usage by the VM. The value is a percentage
    between 0 and (100 * number of VCPUs). Default cap is 0: unlimited.

cpu\_weight
    Valid for the Xen hypervisor.

    Set the cpu time ratio to be allocated to the VM. Valid values are
    between 1 and 65535. Default weight is 256.

usb\_mouse
    Valid for the KVM hypervisor.

    This option specifies the usb mouse type to be used. It can be
    "mouse" or "tablet". When using VNC it's recommended to set it to
    "tablet".

keymap
    Valid for the KVM hypervisor.

    This option specifies the keyboard mapping to be used. It is only
    needed when using the VNC console. For example: "fr" or "en-gb".

reboot\_behavior
    Valid for Xen PVM, Xen HVM and KVM hypervisors.

    Normally if an instance reboots, the hypervisor will restart it. If
    this option is set to ``exit``, the hypervisor will treat a reboot
    as a shutdown instead.

    It is set to ``reboot`` by default.

cpu\_cores
    Valid for the KVM hypervisor.

    Number of emulated CPU cores.

cpu\_threads
    Valid for the KVM hypervisor.

    Number of emulated CPU threads.

cpu\_sockets
    Valid for the KVM hypervisor.

    Number of emulated CPU sockets.

soundhw
    Valid for the KVM and XEN hypervisors.

    Comma separated list of emulated sounds cards, or "all" to enable
    all the available ones.

cpuid
    Valid for the XEN hypervisor.

    Modify the values returned by CPUID_ instructions run within instances.

    This allows you to enable migration between nodes with different CPU
    attributes like cores, threads, hyperthreading or SS4 support by hiding
    the extra features where needed.

    See the XEN documentation for syntax and more information.

.. _CPUID: http://en.wikipedia.org/wiki/CPUID

usb\_devices
    Valid for the KVM hypervisor.

    Space separated list of usb devices. These can be emulated devices
    or passthrough ones, and each one gets passed to kvm with its own
    ``-usbdevice`` option. See the **qemu**\(1) manpage for the syntax
    of the possible components. Note that values set with this
    parameter are split on a space character and currently don't support
    quoting. For backwards compatibility reasons, the RAPI interface keeps
    accepting comma separated lists too.

vga
    Valid for the KVM hypervisor.

    Emulated vga mode, passed the the kvm -vga option.

kvm\_extra
    Valid for the KVM hypervisor.

    Any other option to the KVM hypervisor, useful tweaking anything
    that Ganeti doesn't support. Note that values set with this
    parameter are split on a space character and currently don't support
    quoting.

machine\_version
    Valid for the KVM hypervisor.

    Use in case an instance must be booted with an exact type of
    machine version (due to e.g. outdated drivers). In case it's not set
    the default version supported by your version of kvm is used.

kvm\_path
    Valid for the KVM hypervisor.

    Path to the userspace KVM (or qemu) program.

vnet\_hdr
    Valid for the KVM hypervisor.

    This boolean option determines whether the tap devices used by the
    KVM paravirtual nics (virtio-net) will get created with VNET_HDR
    (IFF_VNET_HDR) support.

    If set to false, it effectively disables offloading on the virio-net
    interfaces, which prevents host kernel tainting and log flooding,
    when dealing with broken or malicious virtio-net drivers.

    It is set to ``true`` by default.

The ``-O (--os-parameters)`` option allows customisation of the OS
parameters. The actual parameter names and values depends on the OS
being used, but the syntax is the same key=value. For example, setting
a hypothetical ``dhcp`` parameter to yes can be achieved by::

    gnt-instance add -O dhcp=yes ...

The ``-I (--iallocator)`` option specifies the instance allocator plugin
to use (``.`` means the default allocator). If you pass in this option
the allocator will select nodes for this instance automatically, so you
don't need to pass them with the ``-n`` option. For more information
please refer to the instance allocator documentation.

The ``-t (--disk-template)`` options specifies the disk layout type
for the instance. If no disk template is specified, the default disk
template is used. The default disk template is the first in the list
of enabled disk templates, which can be adjusted cluster-wide with
``gnt-cluster modify``. The available choices for disk templates are:

diskless
    This creates an instance with no disks. Its useful for testing only
    (or other special cases).

file
    Disk devices will be regular files.

sharedfile
    Disk devices will be regulare files on a shared directory.

plain
    Disk devices will be logical volumes.

drbd
    Disk devices will be drbd (version 8.x) on top of lvm volumes.

rbd
    Disk devices will be rbd volumes residing inside a RADOS cluster.

blockdev
    Disk devices will be adopted pre-existent block devices.

ext
    Disk devices will be provided by external shared storage,
    through the ExtStorage Interface using ExtStorage providers.

The optional second value of the ``-n (--node)`` is used for the drbd
template type and specifies the remote node.

If you do not want gnt-instance to wait for the disk mirror to be
synced, use the ``--no-wait-for-sync`` option.

The ``--file-storage-dir`` specifies the relative path under the
cluster-wide file storage directory to store file-based disks. It is
useful for having different subdirectories for different
instances. The full path of the directory where the disk files are
stored will consist of cluster-wide file storage directory + optional
subdirectory + instance name. This option is only relevant for
instances using the file storage backend.

The ``--file-driver`` specifies the driver to use for file-based
disks. Note that currently these drivers work with the xen hypervisor
only. This option is only relevant for instances using the file
storage backend. The available choices are:

loop
    Kernel loopback driver. This driver uses loopback devices to
    access the filesystem within the file. However, running I/O
    intensive applications in your instance using the loop driver
    might result in slowdowns. Furthermore, if you use the loopback
    driver consider increasing the maximum amount of loopback devices
    (on most systems it's 8) using the max\_loop param.

blktap
    The blktap driver (for Xen hypervisors). In order to be able to
    use the blktap driver you should check if the 'blktapctrl' user
    space disk agent is running (usually automatically started via
    xend).  This user-level disk I/O interface has the advantage of
    better performance. Especially if you use a network file system
    (e.g. NFS) to store your instances this is the recommended choice.

blktap2
    Analogous to the blktap driver, but used by newer versions of Xen.

If ``--ignore-ipolicy`` is given any instance policy violations occuring
during this operation are ignored.

The ``-c`` and ``--communication`` specify whether to enable/disable
instance communication, which is a communication mechanism between the
instance and the host.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Example::

    # gnt-instance add -t file --disk 0:size=30g -B maxmem=512 -o debian-etch \
      -n node1.example.com --file-storage-dir=mysubdir instance1.example.com
    # gnt-instance add -t plain --disk 0:size=30g -B maxmem=1024,minmem=512 \
      -o debian-etch -n node1.example.com instance1.example.com
    # gnt-instance add -t plain --disk 0:size=30g --disk 1:size=100g,vg=san \
      -B maxmem=512 -o debian-etch -n node1.example.com instance1.example.com
    # gnt-instance add -t drbd --disk 0:size=30g -B maxmem=512 -o debian-etch \
      -n node1.example.com:node2.example.com instance2.example.com
    # gnt-instance add -t rbd --disk 0:size=30g -B maxmem=512 -o debian-etch \
      -n node1.example.com instance1.example.com
    # gnt-instance add -t ext --disk 0:size=30g,provider=pvdr1 -B maxmem=512 \
      -o debian-etch -n node1.example.com instance1.example.com
    # gnt-instance add -t ext --disk 0:size=30g,provider=pvdr1,param1=val1 \
      --disk 1:size=40g,provider=pvdr2,param2=val2,param3=val3 -B maxmem=512 \
      -o debian-etch -n node1.example.com instance1.example.com


BATCH-CREATE
^^^^^^^^^^^^

| **batch-create**
| [{-I|\--iallocator} *instance allocator*]
| {instances\_file.json}

This command (similar to the Ganeti 1.2 **batcher** tool) submits
multiple instance creation jobs based on a definition file. This
file can contain all options which are valid when adding an instance
with the exception of the ``iallocator`` field. The IAllocator is,
for optimization purposes, only allowed to be set for the whole batch
operation using the ``--iallocator`` parameter.

The instance file must be a valid-formed JSON file, containing an
array of dictionaries with instance creation parameters. All parameters
(except ``iallocator``) which are valid for the instance creation
OP code are allowed. The most important ones are:

instance\_name
    The FQDN of the new instance.

disk\_template
    The disk template to use for the instance, the same as in the
    **add** command.

disks
    Array of disk specifications. Each entry describes one disk as a
    dictionary of disk parameters.

beparams
    A dictionary of backend parameters.

hypervisor
    The hypervisor for the instance.

hvparams
    A dictionary with the hypervisor options. If not passed, the default
    hypervisor options will be inherited.

nics
    List of NICs that will be created for the instance. Each entry
    should be a dict, with mac, ip, mode and link as possible keys.
    Please don't provide the "mac, ip, mode, link" parent keys if you
    use this method for specifying NICs.

pnode, snode
    The primary and optionally the secondary node to use for the
    instance (in case an iallocator script is not used). If those
    parameters are given, they have to be given consistently for all
    instances in the batch operation.

start
    whether to start the instance

ip\_check
    Skip the check for already-in-use instance; see the description in
    the **add** command for details.

name\_check
    Skip the name check for instances; see the description in the
    **add** command for details.

file\_storage\_dir, file\_driver
    Configuration for the file disk type, see the **add** command for
    details.


A simple definition for one instance can be (with most of the
parameters taken from the cluster defaults)::

    [
      {
        "mode": "create",
        "instance_name": "instance1.example.com",
        "disk_template": "drbd",
        "os_type": "debootstrap",
        "disks": [{"size":"1024"}],
        "nics": [{}],
        "hypervisor": "xen-pvm"
      },
      {
        "mode": "create",
        "instance_name": "instance2.example.com",
        "disk_template": "drbd",
        "os_type": "debootstrap",
        "disks": [{"size":"4096", "mode": "rw", "vg": "xenvg"}],
        "nics": [{}],
        "hypervisor": "xen-hvm",
        "hvparams": {"acpi": true},
        "beparams": {"maxmem": 512, "minmem": 256}
      }
    ]

The command will display the job id for each submitted instance, as
follows::

    # gnt-instance batch-create instances.json
    Submitted jobs 37, 38


Note: If the allocator is used for computing suitable nodes for the
instances, it will only take into account disk information for the
default disk template. That means, even if other disk templates are
specified for the instances, storage space information of these disk
templates will not be considered in the allocation computation.


REMOVE
^^^^^^

| **remove** [\--ignore-failures] [\--shutdown-timeout=*N*] [\--submit]
| [\--print-job-id] [\--force] {*instance*}

Remove an instance. This will remove all data from the instance and
there is *no way back*. If you are not sure if you use an instance
again, use **shutdown** first and leave it in the shutdown state for a
while.

The ``--ignore-failures`` option will cause the removal to proceed
even in the presence of errors during the removal of the instance
(e.g. during the shutdown or the disk removal). If this option is not
given, the command will stop at the first error.

The ``--shutdown-timeout`` is used to specify how much time to wait
before forcing the shutdown (e.g. ``xm destroy`` in Xen, killing the
kvm process for KVM, etc.). By default two minutes are given to each
instance to stop.

The ``--force`` option is used to skip the interactive confirmation.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Example::

    # gnt-instance remove instance1.example.com


LIST
^^^^

| **list**
| [\--no-headers] [\--separator=*SEPARATOR*] [\--units=*UNITS*] [-v]
| [{-o|\--output} *[+]FIELD,...*] [\--filter] [instance...]

Shows the currently configured instances with memory usage, disk
usage, the node they are running on, and their run status.

The ``--no-headers`` option will skip the initial header line. The
``--separator`` option takes an argument which denotes what will be
used between the output fields. Both these options are to help
scripting.

The units used to display the numeric values in the output varies,
depending on the options given. By default, the values will be
formatted in the most appropriate unit. If the ``--separator`` option
is given, then the values are shown in mebibytes to allow parsing by
scripts. In both cases, the ``--units`` option can be used to enforce
a given output unit.

The ``-v`` option activates verbose mode, which changes the display of
special field states (see **ganeti**\(7)).

The ``-o (--output)`` option takes a comma-separated list of output
fields. The available fields and their meaning are:

@QUERY_FIELDS_INSTANCE@

If the value of the option starts with the character ``+``, the new
field(s) will be added to the default list. This allows one to quickly
see the default list plus a few other fields, instead of retyping the
entire list of fields.

There is a subtle grouping about the available output fields: all
fields except for ``oper_state``, ``oper_ram``, ``oper_vcpus`` and
``status`` are configuration value and not run-time values. So if you
don't select any of the these fields, the query will be satisfied
instantly from the cluster configuration, without having to ask the
remote nodes for the data. This can be helpful for big clusters when
you only want some data and it makes sense to specify a reduced set of
output fields.

If exactly one argument is given and it appears to be a query filter
(see **ganeti**\(7)), the query result is filtered accordingly. For
ambiguous cases (e.g. a single field name as a filter) the ``--filter``
(``-F``) option forces the argument to be treated as a filter (e.g.
``gnt-instance list -F admin_state``).

The default output field list is: ``name``, ``os``, ``pnode``,
``admin_state``, ``oper_state``, ``oper_ram``.


LIST-FIELDS
^^^^^^^^^^^

**list-fields** [field...]

Lists available fields for instances.


INFO
^^^^

**info** [-s \| \--static] [\--roman] {\--all \| *instance*}

Show detailed information about the given instance(s). This is
different from **list** as it shows detailed data about the instance's
disks (especially useful for the drbd disk template).

If the option ``-s`` is used, only information available in the
configuration file is returned, without querying nodes, making the
operation faster.

Use the ``--all`` to get info about all instances, rather than
explicitly passing the ones you're interested in.

The ``--roman`` option can be used to cause envy among people who like
ancient cultures, but are stuck with non-latin-friendly cluster
virtualization technologies.

MODIFY
^^^^^^

| **modify**
| [{-H|\--hypervisor-parameters} *HYPERVISOR\_PARAMETERS*]
| [{-B|\--backend-parameters} *BACKEND\_PARAMETERS*]
| [{-m|\--runtime-memory} *SIZE*]
| [\--net add[:options...] \|
|  \--net [*N*:]add[,options...] \|
|  \--net [*ID*:]remove \|
|  \--net *ID*:modify[,options...]]
| [\--disk add:size=*SIZE*[,options...] \|
|  \--disk *N*:add,size=*SIZE*[,options...] \|
|  \--disk *N*:add,size=*SIZE*,provider=*PROVIDER*[,options...][,param=*value*... ] \|
|  \--disk *ID*:modify[,options...]
|  \--disk [*ID*:]remove]
| [{-t|\--disk-template} plain \| {-t|\--disk-template} drbd -n *new_secondary*] [\--no-wait-for-sync]
| [\--new-primary=*node*]
| [\--os-type=*OS* [\--force-variant]]
| [{-O|\--os-parameters} *param*=*value*... ]
| [--os-parameters-private *param*=*value*... ]
| [\--offline \| \--online]
| [\--submit] [\--print-job-id]
| [\--ignore-ipolicy]
| [\--hotplug]
| [\--hotplug-if-possible]
| {*instance*}

Modifies the memory size, number of vcpus, ip address, MAC address
and/or NIC parameters for an instance. It can also add and remove
disks and NICs to/from the instance. Note that you need to give at
least one of the arguments, otherwise the command complains.

The ``-H (--hypervisor-parameters)``, ``-B (--backend-parameters)``
and ``-O (--os-parameters)`` options specifies hypervisor, backend and
OS parameter options in the form of name=value[,...]. For details
which options can be specified, see the **add** command.

The ``-t (--disk-template)`` option will change the disk template of
the instance.  Currently only conversions between the plain and drbd
disk templates are supported, and the instance must be stopped before
attempting the conversion. When changing from the plain to the drbd
disk template, a new secondary node must be specified via the ``-n``
option. The option ``--no-wait-for-sync`` can be used when converting
to the ``drbd`` template in order to make the instance available for
startup before DRBD has finished resyncing.

The ``-m (--runtime-memory)`` option will change an instance's runtime
memory to the given size (in MB if a different suffix is not specified),
by ballooning it up or down to the new value.

The ``--disk add:size=*SIZE*,[options..]`` option adds a disk to the
instance, and ``--disk *N*:add:size=*SIZE*,[options..]`` will add a disk
to the the instance at a specific index. The available options are the
same as in the **add** command(``spindles``, ``mode``, ``name``, ``vg``,
``metavg``). Per default, gnt-instance waits for the disk mirror to sync.
If you do not want this behavior, use the ``--no-wait-for-sync`` option.
When adding an ExtStorage disk, the ``provider=*PROVIDER*`` option is
also mandatory and specifies the ExtStorage provider. Also, for
ExtStorage disks arbitrary parameters can be passed as additional comma
separated options, same as in the **add** command. The ``--disk remove``
option will remove the last disk of the instance. Use
``--disk `` *ID*``:remove`` to remove a disk by its identifier. *ID*
can be the index of the disk, the disks's name or the disks's UUID. The
``--disk *ID*:modify[,options...]`` will change the options of the disk.
Available options are:

mode
  The access mode. Either ``ro`` (read-only) or the default ``rw`` (read-write).

name
   This option specifies a name for the disk, which can be used as a disk
   identifier. An instance can not have two disks with the same name.

The ``--net *N*:add[,options..]`` will add a new network interface to
the instance. The available options are the same as in the **add**
command (``mac``, ``ip``, ``link``, ``mode``, ``network``). The
``--net *ID*,remove`` will remove the intances' NIC with *ID* identifier,
which can be the index of the NIC, the NIC's name or the NIC's UUID.
The ``--net *ID*:modify[,options..]`` option will change the parameters of
the instance network interface with the *ID* identifier.

The option ``-o (--os-type)`` will change the OS name for the instance
(without reinstallation). In case an OS variant is specified that is
not found, then by default the modification is refused, unless
``--force-variant`` is passed. An invalid OS will also be refused,
unless the ``--force`` option is given.

The option ``--new-primary`` will set the new primary node of an instance
assuming the disks have already been moved manually. Unless the ``--force``
option is given, it is verified that the instance is no longer running
on its current primary node.

The ``--online`` and ``--offline`` options are used to transition an
instance into and out of the ``offline`` state. An instance can be
turned offline only if it was previously down. The ``--online`` option
fails if the instance was not in the ``offline`` state, otherwise it
changes instance's state to ``down``. These modifications take effect
immediately.

If ``--ignore-ipolicy`` is given any instance policy violations occuring
during this operation are ignored.

If ``--hotplug`` is given any disk and NIC modifications will take
effect without the need of actual reboot. Please note that this feature
is currently supported only for KVM hypervisor and there are some
restrictions: a) KVM versions >= 1.0 support it b) instances with chroot
or uid pool security model do not support disk hotplug c) RBD disks with
userspace access mode can not be hotplugged (yet) d) if hotplug fails
(for any reason) a warning is printed but execution is continued e)
for existing NIC modification interactive verification is needed unless
``--force`` option is passed.

If ``--hotplug-if-possible`` is given then ganeti won't abort in case
hotplug is not supported. It will continue execution and modification
will take place after reboot. This covers use cases where instances are
not running or hypervisor is not KVM.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Most of the changes take effect at the next restart. If the instance is
running, there is no effect on the instance.

REINSTALL
^^^^^^^^^

| **reinstall** [{-o|\--os-type} *os-type*] [\--select-os] [-f *force*]
| [\--force-multiple]
| [\--instance \| \--node \| \--primary \| \--secondary \| \--all]
| [{-O|\--os-parameters} *OS\_PARAMETERS*] [\--submit] [\--print-job-id]
| {*instance*...}

Reinstalls the operating system on the given instance(s). The
instance(s) must be stopped when running this command. If the ``-o
(--os-type)`` is specified, the operating system is changed.

The ``--select-os`` option switches to an interactive OS reinstall.
The user is prompted to select the OS template from the list of
available OS templates. OS parameters can be overridden using ``-O
(--os-parameters)`` (more documentation for this option under the
**add** command).

Since this is a potentially dangerous command, the user will be
required to confirm this action, unless the ``-f`` flag is passed.
When multiple instances are selected (either by passing multiple
arguments or by using the ``--node``, ``--primary``, ``--secondary``
or ``--all`` options), the user must pass the ``--force-multiple``
options to skip the interactive confirmation.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

RENAME
^^^^^^

| **rename** [\--no-ip-check] [\--no-name-check] [\--submit] [\--print-job-id]
| {*instance*} {*new\_name*}

Renames the given instance. The instance must be stopped when running
this command. The requirements for the new name are the same as for
adding an instance: the new name must be resolvable and the IP it
resolves to must not be reachable (in order to prevent duplicate IPs
the next time the instance is started). The IP test can be skipped if
the ``--no-ip-check`` option is passed.

Note that you can rename an instance to its same name, to force
re-executing the os-specific rename script for that instance, if
needed.

The ``--no-name-check`` skips the check for the new instance name via
the resolver (e.g. in DNS or /etc/hosts, depending on your setup) and
that the resolved name matches the provided name. Since the name check
is used to compute the IP address, if you pass this option you must also
pass the ``--no-ip-check`` option.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Starting/stopping/connecting to console
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

STARTUP
^^^^^^^

| **startup**
| [\--force] [\--ignore-offline]
| [\--force-multiple] [\--no-remember]
| [\--instance \| \--node \| \--primary \| \--secondary \| \--all \|
| \--tags \| \--node-tags \| \--pri-node-tags \| \--sec-node-tags]
| [{-H|\--hypervisor-parameters} ``key=value...``]
| [{-B|\--backend-parameters} ``key=value...``]
| [\--submit] [\--print-job-id] [\--paused]
| {*name*...}

Starts one or more instances, depending on the following options.  The
four available modes are:

\--instance
    will start the instances given as arguments (at least one argument
    required); this is the default selection

\--node
    will start the instances who have the given node as either primary
    or secondary

\--primary
    will start all instances whose primary node is in the list of nodes
    passed as arguments (at least one node required)

\--secondary
    will start all instances whose secondary node is in the list of
    nodes passed as arguments (at least one node required)

\--all
    will start all instances in the cluster (no arguments accepted)

\--tags
    will start all instances in the cluster with the tags given as
    arguments

\--node-tags
    will start all instances in the cluster on nodes with the tags
    given as arguments

\--pri-node-tags
    will start all instances in the cluster on primary nodes with the
    tags given as arguments

\--sec-node-tags
    will start all instances in the cluster on secondary nodes with the
    tags given as arguments

Note that although you can pass more than one selection option, the
last one wins, so in order to guarantee the desired result, don't pass
more than one such option.

Use ``--force`` to start even if secondary disks are failing.
``--ignore-offline`` can be used to ignore offline primary nodes and
mark the instance as started even if the primary is not available.

The ``--force-multiple`` will skip the interactive confirmation in the
case the more than one instance will be affected.

The ``--no-remember`` option will perform the startup but not change
the state of the instance in the configuration file (if it was stopped
before, Ganeti will still think it needs to be stopped). This can be
used for testing, or for a one shot-start where you don't want the
watcher to restart the instance if it crashes.

The ``-H (--hypervisor-parameters)`` and ``-B (--backend-parameters)``
options specify temporary hypervisor and backend parameters that can
be used to start an instance with modified parameters. They can be
useful for quick testing without having to modify an instance back and
forth, e.g.::

    # gnt-instance start -H kernel_args="single" instance1
    # gnt-instance start -B maxmem=2048 instance2


The first form will start the instance instance1 in single-user mode,
and the instance instance2 with 2GB of RAM (this time only, unless
that is the actual instance memory size already). Note that the values
override the instance parameters (and not extend them): an instance
with "kernel\_args=ro" when started with -H kernel\_args=single will
result in "single", not "ro single".

The ``--paused`` option is only valid for Xen and kvm hypervisors.  This
pauses the instance at the start of bootup, awaiting ``gnt-instance
console`` to unpause it, allowing the entire boot process to be
monitored for debugging.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Example::

    # gnt-instance start instance1.example.com
    # gnt-instance start --node node1.example.com node2.example.com
    # gnt-instance start --all


SHUTDOWN
^^^^^^^^

| **shutdown**
| [\--timeout=*N*]
| [\--force] [\--force-multiple] [\--ignore-offline] [\--no-remember]
| [\--instance \| \--node \| \--primary \| \--secondary \| \--all \|
| \--tags \| \--node-tags \| \--pri-node-tags \| \--sec-node-tags]
| [\--submit] [\--print-job-id]
| {*name*...}

Stops one or more instances. If the instance cannot be cleanly stopped
during a hardcoded interval (currently 2 minutes), it will forcibly
stop the instance (equivalent to switching off the power on a physical
machine).

The ``--timeout`` is used to specify how much time to wait before
forcing the shutdown (e.g. ``xm destroy`` in Xen, killing the kvm
process for KVM, etc.). By default two minutes are given to each
instance to stop.

The ``--instance``, ``--node``, ``--primary``, ``--secondary``,
``--all``, ``--tags``, ``--node-tags``, ``--pri-node-tags`` and
``--sec-node-tags`` options are similar as for the **startup** command
and they influence the actual instances being shutdown.

``--ignore-offline`` can be used to ignore offline primary nodes and
force the instance to be marked as stopped. This option should be used
with care as it can lead to an inconsistent cluster state.

Use ``--force`` to be able to shutdown an instance even when it's marked
as offline. This is useful is an offline instance ends up in the
``ERROR_up`` state, for example.

The ``--no-remember`` option will perform the shutdown but not change
the state of the instance in the configuration file (if it was running
before, Ganeti will still thinks it needs to be running). This can be
useful for a cluster-wide shutdown, where some instances are marked as
up and some as down, and you don't want to change the running state:
you just need to disable the watcher, shutdown all instances with
``--no-remember``, and when the watcher is activated again it will
restore the correct runtime state for all instances.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Example::

    # gnt-instance shutdown instance1.example.com
    # gnt-instance shutdown --all


REBOOT
^^^^^^

| **reboot**
| [{-t|\--type} *REBOOT-TYPE*]
| [\--ignore-secondaries]
| [\--shutdown-timeout=*N*]
| [\--force-multiple]
| [\--instance \| \--node \| \--primary \| \--secondary \| \--all \|
| \--tags \| \--node-tags \| \--pri-node-tags \| \--sec-node-tags]
| [\--submit] [\--print-job-id]
| [*name*...]

Reboots one or more instances. The type of reboot depends on the value
of ``-t (--type)``. A soft reboot does a hypervisor reboot, a hard reboot
does a instance stop, recreates the hypervisor config for the instance
and starts the instance. A full reboot does the equivalent of
**gnt-instance shutdown && gnt-instance startup**.  The default is
hard reboot.

For the hard reboot the option ``--ignore-secondaries`` ignores errors
for the secondary node while re-assembling the instance disks.

The ``--instance``, ``--node``, ``--primary``, ``--secondary``,
``--all``, ``--tags``, ``--node-tags``, ``--pri-node-tags`` and
``--sec-node-tags`` options are similar as for the **startup** command
and they influence the actual instances being rebooted.

The ``--shutdown-timeout`` is used to specify how much time to wait
before forcing the shutdown (xm destroy in xen, killing the kvm
process, for kvm). By default two minutes are given to each instance
to stop.

The ``--force-multiple`` will skip the interactive confirmation in the
case the more than one instance will be affected.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Example::

    # gnt-instance reboot instance1.example.com
    # gnt-instance reboot --type=full instance1.example.com


CONSOLE
^^^^^^^

**console** [\--show-cmd] {*instance*}

Connects to the console of the given instance. If the instance is not
up, an error is returned. Use the ``--show-cmd`` option to display the
command instead of executing it.

For HVM instances, this will attempt to connect to the serial console
of the instance. To connect to the virtualized "physical" console of a
HVM instance, use a VNC client with the connection info from the
**info** command.

For Xen/kvm instances, if the instance is paused, this attempts to
unpause the instance after waiting a few seconds for the connection to
the console to be made.

Example::

    # gnt-instance console instance1.example.com


Disk management
~~~~~~~~~~~~~~~

REPLACE-DISKS
^^^^^^^^^^^^^

| **replace-disks** [\--submit] [\--print-job-id] [\--early-release]
| [\--ignore-ipolicy] {-p} [\--disks *idx*] {*instance*}

| **replace-disks** [\--submit] [\--print-job-id] [\--early-release]
| [\--ignore-ipolicy] {-s} [\--disks *idx*] {*instance*}

| **replace-disks** [\--submit] [\--print-job-id] [\--early-release]
| [\--ignore-ipolicy]
| {{-I\|\--iallocator} *name* \| {{-n|\--new-secondary} *node* } {*instance*}

| **replace-disks** [\--submit] [\--print-job-id] [\--early-release]
| [\--ignore-ipolicy] {-a\|\--auto} {*instance*}

This command is a generalized form for replacing disks. It is
currently only valid for the mirrored (DRBD) disk template.

The first form (when passing the ``-p`` option) will replace the disks
on the primary, while the second form (when passing the ``-s`` option
will replace the disks on the secondary node. For these two cases (as
the node doesn't change), it is possible to only run the replace for a
subset of the disks, using the option ``--disks`` which takes a list
of comma-delimited disk indices (zero-based), e.g. 0,2 to replace only
the first and third disks.

The third form (when passing either the ``--iallocator`` or the
``--new-secondary`` option) is designed to change secondary node of the
instance. Specifying ``--iallocator`` makes the new secondary be
selected automatically by the specified allocator plugin (use ``.`` to
indicate the default allocator), otherwise the new secondary node will
be the one chosen manually via the ``--new-secondary`` option.

Note that it is not possible to select an offline or drained node as a
new secondary.

The fourth form (when using ``--auto``) will automatically determine
which disks of an instance are faulty and replace them within the same
node. The ``--auto`` option works only when an instance has only
faulty disks on either the primary or secondary node; it doesn't work
when both sides have faulty disks.

The ``--early-release`` changes the code so that the old storage on
secondary node(s) is removed early (before the resync is completed)
and the internal Ganeti locks for the current (and new, if any)
secondary node are also released, thus allowing more parallelism in
the cluster operation. This should be used only when recovering from a
disk failure on the current secondary (thus the old storage is already
broken) or when the storage on the primary node is known to be fine
(thus we won't need the old storage for potential recovery).

The ``--ignore-ipolicy`` let the command ignore instance policy
violations if replace-disks changes groups and the instance would
violate the new groups instance policy.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

ACTIVATE-DISKS
^^^^^^^^^^^^^^

| **activate-disks** [\--submit] [\--print-job-id] [\--ignore-size]
| [\--wait-for-sync] {*instance*}

Activates the block devices of the given instance. If successful, the
command will show the location and name of the block devices::

    node1.example.com:disk/0:/dev/drbd0
    node1.example.com:disk/1:/dev/drbd1


In this example, *node1.example.com* is the name of the node on which
the devices have been activated. The *disk/0* and *disk/1* are the
Ganeti-names of the instance disks; how they are visible inside the
instance is hypervisor-specific. */dev/drbd0* and */dev/drbd1* are the
actual block devices as visible on the node.

The ``--ignore-size`` option can be used to activate disks ignoring
the currently configured size in Ganeti. This can be used in cases
where the configuration has gotten out of sync with the real-world
(e.g. after a partially-failed grow-disk operation or due to rounding
in LVM devices). This should not be used in normal cases, but only
when activate-disks fails without it.

The ``--wait-for-sync`` option will ensure that the command returns only
after the instance's disks are synchronised (mostly for DRBD); this can
be useful to ensure consistency, as otherwise there are no commands that
can wait until synchronisation is done. However when passing this
option, the command will have additional output, making it harder to
parse the disk information.

Note that it is safe to run this command while the instance is already
running.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

DEACTIVATE-DISKS
^^^^^^^^^^^^^^^^

**deactivate-disks** [-f] [\--submit] [\--print-job-id] {*instance*}

De-activates the block devices of the given instance. Note that if you
run this command for an instance with a drbd disk template, while it
is running, it will not be able to shutdown the block devices on the
primary node, but it will shutdown the block devices on the secondary
nodes, thus breaking the replication.

The ``-f``/``--force`` option will skip checks that the instance is
down; in case the hypervisor is confused and we can't talk to it,
normally Ganeti will refuse to deactivate the disks, but with this
option passed it will skip this check and directly try to deactivate
the disks. This can still fail due to the instance actually running or
other issues.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

GROW-DISK
^^^^^^^^^

| **grow-disk** [\--no-wait-for-sync] [\--submit] [\--print-job-id]
| [\--absolute]
| {*instance*} {*disk*} {*amount*}

Grows an instance's disk. This is only possible for instances having a
plain, drbd, file, sharedfile, rbd or ext disk template. For the ext
template to work, the ExtStorage provider should also support growing.
This means having a ``grow`` script that actually grows the volume of
the external shared storage.

Note that this command only change the block device size; it will not
grow the actual filesystems, partitions, etc. that live on that
disk. Usually, you will need to:

#. use **gnt-instance grow-disk**

#. reboot the instance (later, at a convenient time)

#. use a filesystem resizer, such as **ext2online**\(8) or
   **xfs\_growfs**\(8) to resize the filesystem, or use **fdisk**\(8) to
   change the partition table on the disk

The *disk* argument is the index of the instance disk to grow. The
*amount* argument is given as a number which can have a suffix (like the
disk size in instance create); if the suffix is missing, the value will
be interpreted as mebibytes.

By default, the *amount* value represents the desired increase in the
disk size (e.g. an amount of 1G will take a disk of size 3G to 4G). If
the optional ``--absolute`` parameter is passed, then the *amount*
argument doesn't represent the delta, but instead the desired final disk
size (e.g. an amount of 8G will take a disk of size 4G to 8G).

For instances with a drbd template, note that the disk grow operation
might complete on one node but fail on the other; this will leave the
instance with different-sized LVs on the two nodes, but this will not
create problems (except for unused space).

If you do not want gnt-instance to wait for the new disk region to be
synced, use the ``--no-wait-for-sync`` option.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Example (increase the first disk for instance1 by 16GiB)::

    # gnt-instance grow-disk instance1.example.com 0 16g

Example for increasing the disk size to a certain size::

   # gnt-instance grow-disk --absolute instance1.example.com 0 32g

Also note that disk shrinking is not supported; use **gnt-backup
export** and then **gnt-backup import** to reduce the disk size of an
instance.

RECREATE-DISKS
^^^^^^^^^^^^^^

| **recreate-disks** [\--submit] [\--print-job-id]
| [{-n node1:[node2] \| {-I\|\--iallocator *name*}}]
| [\--disk=*N*[:[size=*VAL*][,spindles=*VAL*][,mode=*ro\|rw*]]] {*instance*}

Recreates all or a subset of disks of the given instance.

Note that this functionality should only be used for missing disks; if
any of the given disks already exists, the operation will fail.  While
this is suboptimal, recreate-disks should hopefully not be needed in
normal operation and as such the impact of this is low.

If only a subset should be recreated, any number of ``disk`` options can
be specified. It expects a disk index and an optional list of disk
parameters to change. Only ``size``, ``spindles``, and ``mode`` can be
changed while recreating disks. To recreate all disks while changing
parameters on a subset only, a ``--disk`` option must be given for every
disk of the instance.

Optionally the instance's disks can be recreated on different
nodes. This can be useful if, for example, the original nodes of the
instance have gone down (and are marked offline), so we can't recreate
on the same nodes. To do this, pass the new node(s) via ``-n`` option,
with a syntax similar to the **add** command. The number of nodes
passed must equal the number of nodes that the instance currently
has. Note that changing nodes is only allowed when all disks are
replaced, e.g. when no ``--disk`` option is passed.

Another method of choosing which nodes to place the instance on is by
using the specified iallocator, passing the ``--iallocator`` option.
The primary and secondary nodes will be chosen by the specified
iallocator plugin, or by the default allocator if ``.`` is specified.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Recovery/moving
~~~~~~~~~~~~~~~

FAILOVER
^^^^^^^^

| **failover** [-f] [\--ignore-consistency] [\--ignore-ipolicy]
| [\--shutdown-timeout=*N*]
| [{-n|\--target-node} *node* \| {-I|\--iallocator} *name*]
| [\--cleanup]
| [\--submit] [\--print-job-id]
| {*instance*}

Failover will stop the instance (if running), change its primary node,
and if it was originally running it will start it again (on the new
primary). This works for instances with drbd template (in which case you
can only fail to the secondary node) and for externally mirrored
templates (sharedfile, blockdev, rbd and ext) (in which case you can
fail to any other node).

If the instance's disk template is of type sharedfile, blockdev, rbd or
ext, then you can explicitly specify the target node (which can be any
node) using the ``-n`` or ``--target-node`` option, or specify an
iallocator plugin using the ``-I`` or ``--iallocator`` option. If you
omit both, the default iallocator will be used to specify the target
node.

If the instance's disk template is of type drbd, the target node is
automatically selected as the drbd's secondary node. Changing the
secondary node is possible with a replace-disks operation.

Normally the failover will check the consistency of the disks before
failing over the instance. If you are trying to migrate instances off
a dead node, this will fail. Use the ``--ignore-consistency`` option
for this purpose. Note that this option can be dangerous as errors in
shutting down the instance will be ignored, resulting in possibly
having the instance running on two machines in parallel (on
disconnected DRBD drives).

The ``--shutdown-timeout`` is used to specify how much time to wait
before forcing the shutdown (xm destroy in xen, killing the kvm
process, for kvm). By default two minutes are given to each instance
to stop.

If ``--ignore-ipolicy`` is given any instance policy violations occuring
during this operation are ignored.

If the ``--cleanup`` option is passed, the operation changes from
performin a failover to attempting recovery from a failed previous failover.
In this mode, Ganeti checks if the instance runs on the correct node (and
updates its configuration if not) and ensures the instances' disks
are configured correctly.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Example::

    # gnt-instance failover instance1.example.com

For externally mirrored templates also ``-n`` is available::

    # gnt-instance failover -n node3.example.com instance1.example.com


MIGRATE
^^^^^^^

| **migrate** [-f] [\--allow-failover] [\--non-live]
| [\--migration-mode=live\|non-live] [\--ignore-ipolicy]
| [\--no-runtime-changes] [\--submit] [\--print-job-id]
| [{-n|\--target-node} *node* \| {-I|\--iallocator} *name*] {*instance*}

| **migrate** [-f] \--cleanup [\--submit] [\--print-job-id] {*instance*}

Migrate will move the instance to its secondary node without shutdown.
As with failover, it works for instances having the drbd disk template
or an externally mirrored disk template type such as sharedfile,
blockdev, rbd or ext.

If the instance's disk template is of type sharedfile, blockdev, rbd or
ext, then you can explicitly specify the target node (which can be any
node) using the ``-n`` or ``--target-node`` option, or specify an
iallocator plugin using the ``-I`` or ``--iallocator`` option. If you
omit both, the default iallocator will be used to specify the target
node.  Alternatively, the default iallocator can be requested by
specifying ``.`` as the name of the plugin.

If the instance's disk template is of type drbd, the target node is
automatically selected as the drbd's secondary node. Changing the
secondary node is possible with a replace-disks operation.

The migration command needs a perfectly healthy instance for drbd
instances, as we rely on the dual-master capability of drbd8 and the
disks of the instance are not allowed to be degraded.

The ``--non-live`` and ``--migration-mode=non-live`` options will
switch (for the hypervisors that support it) between a "fully live"
(i.e. the interruption is as minimal as possible) migration and one in
which the instance is frozen, its state saved and transported to the
remote node, and then resumed there. This all depends on the
hypervisor support for two different methods. In any case, it is not
an error to pass this parameter (it will just be ignored if the
hypervisor doesn't support it). The option ``--migration-mode=live``
option will request a fully-live migration. The default, when neither
option is passed, depends on the hypervisor parameters (and can be
viewed with the **gnt-cluster info** command).

If the ``--cleanup`` option is passed, the operation changes from
migration to attempting recovery from a failed previous migration. In
this mode, Ganeti checks if the instance runs on the correct node (and
updates its configuration if not) and ensures the instances' disks
are configured correctly. In this mode, the ``--non-live`` option is
ignored.

The option ``-f`` will skip the prompting for confirmation.

If ``--allow-failover`` is specified it tries to fallback to failover if
it already can determine that a migration won't work (e.g. if the
instance is shut down). Please note that the fallback will not happen
during execution. If a migration fails during execution it still fails.

If ``--ignore-ipolicy`` is given any instance policy violations occuring
during this operation are ignored.

The ``--no-runtime-changes`` option forbids migrate to alter an
instance's runtime before migrating it (eg. ballooning an instance
down because the target node doesn't have enough available memory).

If an instance has the backend parameter ``always_failover`` set to
true, then the migration is automatically converted into a failover.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Example (and expected output)::

    # gnt-instance migrate instance1
    Instance instance1 will be migrated. Note that migration
    might impact the instance if anything goes wrong (e.g. due to bugs in
    the hypervisor). Continue?
    y/[n]/?: y
    Migrating instance instance1.example.com
    * checking disk consistency between source and target
    * switching node node2.example.com to secondary mode
    * changing into standalone mode
    * changing disks into dual-master mode
    * wait until resync is done
    * preparing node2.example.com to accept the instance
    * migrating instance to node2.example.com
    * switching node node1.example.com to secondary mode
    * wait until resync is done
    * changing into standalone mode
    * changing disks into single-master mode
    * wait until resync is done
    * done
    #


MOVE
^^^^

| **move** [-f] [\--ignore-consistency]
| [-n *node*] [\--compress=*compression-mode*] [\--shutdown-timeout=*N*]
| [\--submit] [\--print-job-id] [\--ignore-ipolicy]
| {*instance*}

Move will move the instance to an arbitrary node in the cluster. This
works only for instances having a plain or file disk template.

Note that since this operation is done via data copy, it will take a
long time for big disks (similar to replace-disks for a drbd
instance).

The ``--compress`` option is used to specify which compression mode
is used during the move. Valid values are 'none' (the default) and
'gzip'.

The ``--shutdown-timeout`` is used to specify how much time to wait
before forcing the shutdown (e.g. ``xm destroy`` in XEN, killing the
kvm process for KVM, etc.). By default two minutes are given to each
instance to stop.

The ``--ignore-consistency`` option will make Ganeti ignore any errors
in trying to shutdown the instance on its node; useful if the
hypervisor is broken and you want to recover the data.

If ``--ignore-ipolicy`` is given any instance policy violations occuring
during this operation are ignored.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Example::

    # gnt-instance move -n node3.example.com instance1.example.com


CHANGE-GROUP
^^^^^^^^^^^^

| **change-group** [\--submit] [\--print-job-id]
| [\--iallocator *NAME*] [\--to *GROUP*...] {*instance*}

This command moves an instance to another node group. The move is
calculated by an iallocator, either given on the command line or as a
cluster default. Note that the iallocator does only consider disk
information of the default disk template, even if the instances'
disk templates differ from that.

If no specific destination groups are specified using ``--to``, all
groups except the one containing the instance are considered.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Example::

    # gnt-instance change-group -I hail --to rack2 inst1.example.com


Tags
~~~~

ADD-TAGS
^^^^^^^^

**add-tags** [\--from *file*] {*instancename*} {*tag*...}

Add tags to the given instance. If any of the tags contains invalid
characters, the entire operation will abort.

If the ``--from`` option is given, the list of tags will be extended
with the contents of that file (each line becomes a tag).  In this
case, there is not need to pass tags on the command line (if you do,
both sources will be used). A file name of ``-`` will be interpreted
as stdin.

LIST-TAGS
^^^^^^^^^

**list-tags** {*instancename*}

List the tags of the given instance.

REMOVE-TAGS
^^^^^^^^^^^

**remove-tags** [\--from *file*] {*instancename*} {*tag*...}

Remove tags from the given instance. If any of the tags are not
existing on the node, the entire operation will abort.

If the ``--from`` option is given, the list of tags to be removed will
be extended with the contents of that file (each line becomes a tag).
In this case, there is not need to pass tags on the command line (if
you do, tags from both sources will be removed). A file name of ``-``
will be interpreted as stdin.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
