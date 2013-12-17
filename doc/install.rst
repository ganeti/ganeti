Ganeti installation tutorial
============================

Documents Ganeti version |version|

.. contents::

.. highlight:: shell-example

Introduction
------------

Ganeti is a cluster virtualization management system based on Xen or
KVM. This document explains how to bootstrap a Ganeti node (Xen *dom0*,
the host Linux system for KVM), create a running cluster and install
virtual instances (Xen *domUs*, KVM guests).  You need to repeat most of
the steps in this document for every node you want to install, but of
course we recommend creating some semi-automatic procedure if you plan
to deploy Ganeti on a medium/large scale.

A basic Ganeti terminology glossary is provided in the introductory
section of the :doc:`admin`. Please refer to that document if you are
uncertain about the terms we are using.

Ganeti has been developed for Linux and should be distribution-agnostic.
This documentation will use Debian Squeeze as an example system but the
examples can be translated to any other distribution. You are expected
to be familiar with your distribution, its package management system,
and Xen or KVM before trying to use Ganeti.

This document is divided into two main sections:

- Installation of the base system and base components

- Configuration of the environment for Ganeti

Each of these is divided into sub-sections. While a full Ganeti system
will need all of the steps specified, some are not strictly required for
every environment. Which ones they are, and why, is specified in the
corresponding sections.

Installing the base system and base components
----------------------------------------------

Hardware requirements
+++++++++++++++++++++

Any system supported by your Linux distribution is fine. 64-bit systems
are better as they can support more memory.

Any disk drive recognized by Linux (``IDE``/``SCSI``/``SATA``/etc.) is
supported in Ganeti. Note that no shared storage (e.g. ``SAN``) is
needed to get high-availability features (but of course, one can be used
to store the images). Whilte it is highly recommended to use more than
one disk drive in order to improve speed, Ganeti also works with one
disk per machine.

Installing the base system
++++++++++++++++++++++++++

**Mandatory** on all nodes.

It is advised to start with a clean, minimal install of the operating
system. The only requirement you need to be aware of at this stage is to
partition leaving enough space for a big (**minimum** 20GiB) LVM volume
group which will then host your instance filesystems, if you want to use
all Ganeti features. The volume group name Ganeti uses (by default) is
``xenvg``.

You can also use file-based storage only, without LVM, but this setup is
not detailed in this document.

If you choose to use RBD-based instances, there's no need for LVM
provisioning. However, this feature is experimental, and is not yet
recommended for production clusters.

While you can use an existing system, please note that the Ganeti
installation is intrusive in terms of changes to the system
configuration, and it's best to use a newly-installed system without
important data on it.

Also, for best results, it's advised that the nodes have as much as
possible the same hardware and software configuration. This will make
administration much easier.

Hostname issues
~~~~~~~~~~~~~~~

Note that Ganeti requires the hostnames of the systems (i.e. what the
``hostname`` command outputs to be a fully-qualified name, not a short
name. In other words, you should use *node1.example.com* as a hostname
and not just *node1*.

.. admonition:: Debian

   Debian usually configures the hostname differently than you need it
   for Ganeti. For example, this is what it puts in ``/etc/hosts`` in
   certain situations::

     127.0.0.1       localhost
     127.0.1.1       node1.example.com node1

   but for Ganeti you need to have::

     127.0.0.1       localhost
     192.0.2.1       node1.example.com node1

   replacing ``192.0.2.1`` with your node's address. Also, the file
   ``/etc/hostname`` which configures the hostname of the system
   should contain ``node1.example.com`` and not just ``node1`` (you
   need to run the command ``/etc/init.d/hostname.sh start`` after
   changing the file).

.. admonition:: Why a fully qualified host name

   Although most distributions use only the short name in the
   /etc/hostname file, we still think Ganeti nodes should use the full
   name. The reason for this is that calling 'hostname --fqdn' requires
   the resolver library to work and is a 'guess' via heuristics at what
   is your domain name. Since Ganeti can be used among other things to
   host DNS servers, we don't want to depend on them as much as
   possible, and we'd rather have the uname() syscall return the full
   node name.

   We haven't ever found any breakage in using a full hostname on a
   Linux system, and anyway we recommend to have only a minimal
   installation on Ganeti nodes, and to use instances (or other
   dedicated machines) to run the rest of your network services. By
   doing this you can change the /etc/hostname file to contain an FQDN
   without the fear of breaking anything unrelated.


Installing The Hypervisor
+++++++++++++++++++++++++

**Mandatory** on all nodes.

While Ganeti is developed with the ability to modularly run on different
virtualization environments in mind the only two currently useable on a
live system are Xen and KVM. Supported Xen versions are: 3.0.3 and later
3.x versions, and 4.x (tested up to 4.1).  Supported KVM versions are 72
and above.

Please follow your distribution's recommended way to install and set up
Xen, or install Xen from the upstream source, if you wish, following
their manual. For KVM, make sure you have a KVM-enabled kernel and the
KVM tools.

After installing Xen, you need to reboot into your new system. On some
distributions this might involve configuring GRUB appropriately, whereas
others will configure it automatically when you install the respective
kernels. For KVM no reboot should be necessary.

.. admonition:: Xen on Debian

   Under Debian you can install the relevant ``xen-linux-system``
   package, which will pull in both the hypervisor and the relevant
   kernel. Also, if you are installing a 32-bit system, you should
   install the ``libc6-xen`` package (run ``apt-get install
   libc6-xen``).

Xen settings
~~~~~~~~~~~~

It's recommended that dom0 is restricted to a low amount of memory
(512MiB or 1GiB is reasonable) and that memory ballooning is disabled in
the file ``/etc/xen/xend-config.sxp`` by setting the value
``dom0-min-mem`` to 0, like this::

  (dom0-min-mem 0)

For optimum performance when running both CPU and I/O intensive
instances, it's also recommended that the dom0 is restricted to one CPU
only. For example you can add ``dom0_max_vcpus=1,dom0_vcpus_pin`` to your
kernels boot command line and set ``dom0-cpus`` in
``/etc/xen/xend-config.sxp`` like this::

  (dom0-cpus 1)

It is recommended that you disable xen's automatic save of virtual
machines at system shutdown and subsequent restore of them at reboot.
To obtain this make sure the variable ``XENDOMAINS_SAVE`` in the file
``/etc/default/xendomains`` is set to an empty value.

If you want to use live migration make sure you have, in the xen config
file, something that allows the nodes to migrate instances between each
other. For example:

.. code-block:: text

  (xend-relocation-server yes)
  (xend-relocation-port 8002)
  (xend-relocation-address '')
  (xend-relocation-hosts-allow '^192\\.0\\.2\\.[0-9]+$')


The second line assumes that the hypervisor parameter
``migration_port`` is set 8002, otherwise modify it to match. The last
line assumes that all your nodes have secondary IPs in the
192.0.2.0/24 network, adjust it accordingly to your setup.

If you want to run HVM instances too with Ganeti and want VNC access to
the console of your instances, set the following two entries in
``/etc/xen/xend-config.sxp``:

.. code-block:: text

  (vnc-listen '0.0.0.0') (vncpasswd '')

You need to restart the Xen daemon for these settings to take effect::

  $ /etc/init.d/xend restart

Selecting the instance kernel
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

After you have installed Xen, you need to tell Ganeti exactly what
kernel to use for the instances it will create. This is done by creating
a symlink from your actual kernel to ``/boot/vmlinuz-3-xenU``, and one
from your initrd to ``/boot/initrd-3-xenU`` [#defkernel]_. Note that
if you don't use an initrd for the domU kernel, you don't need to create
the initrd symlink.

.. admonition:: Debian

   After installation of the ``xen-linux-system`` package, you need to
   run (replace the exact version number with the one you have)::

     $ cd /boot
     $ ln -s vmlinuz-%2.6.26-1%-xen-amd64 vmlinuz-3-xenU
     $ ln -s initrd.img-%2.6.26-1%-xen-amd64 initrd-3-xenU

   By default, the initrd doesn't contain the Xen block drivers needed
   to mount the root device, so it is recommended to update the initrd
   by following these two steps:

   - edit ``/etc/initramfs-tools/modules`` and add ``xen_blkfront``
   - run ``update-initramfs -u``

Installing DRBD
+++++++++++++++

Recommended on all nodes: DRBD_ is required if you want to use the high
availability (HA) features of Ganeti, but optional if you don't require
them or only run Ganeti on single-node clusters. You can upgrade a
non-HA cluster to an HA one later, but you might need to convert all
your instances to DRBD to take advantage of the new features.

.. _DRBD: http://www.drbd.org/

Supported DRBD versions: 8.0-8.3. It's recommended to have at least
version 8.0.12. Note that for version 8.2 and newer it is needed to pass
the ``usermode_helper=/bin/true`` parameter to the module, either by
configuring ``/etc/modules`` or when inserting it manually.

Now the bad news: unless your distribution already provides it
installing DRBD might involve recompiling your kernel or anyway fiddling
with it. Hopefully at least the Xen-ified kernel source to start from
will be provided (if you intend to use Xen).

The good news is that you don't need to configure DRBD at all. Ganeti
will do it for you for every instance you set up.  If you have the DRBD
utils installed and the module in your kernel you're fine. Please check
that your system is configured to load the module at every boot, and
that it passes the following option to the module:
``minor_count=NUMBER``. We recommend that you use 128 as the value of
the minor_count - this will allow you to use up to 64 instances in total
per node (both primary and secondary, when using only one disk per
instance). You can increase the number up to 255 if you need more
instances on a node.


.. admonition:: Debian

   On Debian, you can just install (build) the DRBD module with the
   following commands, making sure you are running the target (Xen or
   KVM) kernel::

     $ apt-get install drbd8-source drbd8-utils
     $ m-a update
     $ m-a a-i drbd8

   Or on newer versions, if the kernel already has modules:

     $ apt-get install drbd8-utils

   Then to configure it for Ganeti::

     $ echo drbd minor_count=128 usermode_helper=/bin/true >> /etc/modules
     $ depmod -a
     $ modprobe drbd minor_count=128 usermode_helper=/bin/true

   It is also recommended that you comment out the default resources (if any)
   in the ``/etc/drbd.conf`` file, so that the init script doesn't try to
   configure any drbd devices. You can do this by prefixing all
   *resource* lines in the file with the keyword *skip*, like this:

   .. code-block:: text

     skip {
       resource r0 {
         ...
       }
     }

     skip {
       resource "r1" {
         ...
       }
     }

Installing RBD
++++++++++++++

Recommended on all nodes: RBD_ is required if you want to create
instances with RBD disks residing inside a RADOS cluster (make use of
the rbd disk template). RBD-based instances can failover or migrate to
any other node in the ganeti cluster, enabling you to exploit of all
Ganeti's high availabilily (HA) features.

.. attention::
   Be careful though: rbd is still experimental! For now it is
   recommended only for testing purposes.  No sensitive data should be
   stored there.

.. _RBD: http://ceph.newdream.net/

You will need the ``rbd`` and ``libceph`` kernel modules, the RBD/Ceph
userspace utils (ceph-common Debian package) and an appropriate
Ceph/RADOS configuration file on every VM-capable node.

You will also need a working RADOS Cluster accessible by the above
nodes.

RADOS Cluster
~~~~~~~~~~~~~

You will need a working RADOS Cluster accesible by all VM-capable nodes
to use the RBD template. For more information on setting up a RADOS
Cluster, refer to the `official docs <http://ceph.newdream.net/>`_.

If you want to use a pool for storing RBD disk images other than the
default (``rbd``), you should first create the pool in the RADOS
Cluster, and then set the corresponding rbd disk parameter named
``pool``.

Kernel Modules
~~~~~~~~~~~~~~

Unless your distribution already provides it, you might need to compile
the ``rbd`` and ``libceph`` modules from source. You will need Linux
Kernel 3.2 or above for the kernel modules. Alternatively you will have
to build them as external modules (from Linux Kernel source 3.2 or
above), if you want to run a less recent kernel, or your kernel doesn't
include them.

Userspace Utils
~~~~~~~~~~~~~~~

The RBD template has been tested with ``ceph-common`` v0.38 and
above. We recommend using the latest version of ``ceph-common``.

.. admonition:: Debian

   On Debian, you can just install the RBD/Ceph userspace utils with
   the following command::

      $ apt-get install ceph-common

KVM userspace access
~~~~~~~~~~~~~~~~~~~~

If your cluster uses a sufficiently new version of KVM (you will need at
least QEMU 0.14 with RBD support compiled in), you can take advantage of
KVM's native support for ceph in order to have better performance and
avoid potential deadlocks_ in low memory scenarios.

.. _deadlocks: http://tracker.ceph.com/issues/3076

To initialize a cluster with support for this feature, use a command
such as::

  $ gnt-cluster init \
      --enabled-disk-templates rbd \
      --ipolicy-disk-templates rbd \
      --enabled-hypervisors=kvm \
      -D rbd:access=userspace

(You may want to enable more templates than just ``rbd``.)

You can also change this setting on a live cluster by giving the same
switches to ``gnt-cluster modify``, or change those settings at the node
group level with ``gnt-group modify``.

Configuration file
~~~~~~~~~~~~~~~~~~

You should also provide an appropriate configuration file
(``ceph.conf``) in ``/etc/ceph``. For the rbd userspace utils, you'll
only need to specify the IP addresses of the RADOS Cluster monitors.

.. admonition:: ceph.conf

   Sample configuration file:

   .. code-block:: text

    [mon.a]
           host = example_monitor_host1
           mon addr = 1.2.3.4:6789
    [mon.b]
           host = example_monitor_host2
           mon addr = 1.2.3.5:6789
    [mon.c]
           host = example_monitor_host3
           mon addr = 1.2.3.6:6789

For more information, please see the `Ceph Docs
<http://ceph.newdream.net/docs/latest/>`_

Installing Gluster
++++++++++++++++++

For Gluster integration, Ganeti requires that ``mount.glusterfs`` is
installed on each and every node. On Debian Wheezy and newer, you can
satisfy this requirement with the ``glusterfs-client`` package; see
`this guide
<http://gluster.org/community/documentation/index.php/Gluster_3.2:_Installing_the_Gluster_Native_Client>`_
for details.

KVM userspace access
~~~~~~~~~~~~~~~~~~~~

If your cluster uses a sufficiently new version of KVM (you will need at
least QEMU 1.3 with Gluster support compiled in), you can take advantage
of KVM's native support for gluster in order to have better performance
and avoid potential deadlocks in low memory scenarios.

Please be aware that QEMU 1.3 was released in December 3, 2012, and as
such this feature is not available out of the box in any distribution
older than Ubuntu 13.04; this excludes Ubuntu 12.04 LTS and Debian
Wheezy.

Other required software
+++++++++++++++++++++++

Please install all software requirements mentioned in :doc:`install-quick`.
If you want to build Ganeti from source, don't forget to follow the steps
required for that as well.

Setting up the environment for Ganeti
-------------------------------------

Configuring the network
+++++++++++++++++++++++

**Mandatory** on all nodes.

You can run Ganeti either in "bridged mode", "routed mode" or
"openvswitch mode". In bridged mode, the default, the instances network
interfaces will be attached to a software bridge running in dom0. Xen by
default creates such a bridge at startup, but your distribution might
have a different way to do things, and you'll definitely need to
manually set it up under KVM.

Beware that the default name Ganeti uses is ``xen-br0`` (which was used
in Xen 2.0) while Xen 3.0 uses ``xenbr0`` by default. See the
`Initializing the cluster`_ section to learn how to choose a different
bridge, or not to use one at all and use "routed mode".

In order to use "routed mode" under Xen, you'll need to change the
relevant parameters in the Xen config file. Under KVM instead, no config
change is necessary, but you still need to set up your network
interfaces correctly.

By default, under KVM, the "link" parameter you specify per-nic will
represent, if non-empty, a different routing table name or number to use
for your instances. This allows isolation between different instance
groups, and different routing policies between node traffic and instance
traffic.

You will need to configure your routing table basic routes and rules
outside of ganeti. The vif scripts will only add /32 routes to your
instances, through their interface, in the table you specified (under
KVM, and in the main table under Xen).

Also for "openvswitch mode" under Xen a custom network script is needed.
Under KVM everything should work, but you'll need to configure your
switches outside of Ganeti (as for bridges).

.. admonition:: Bridging issues with certain kernels

    Some kernel versions (e.g. 2.6.32) have an issue where the bridge
    will automatically change its ``MAC`` address to the lower-numbered
    slave on port addition and removal. This means that, depending on
    the ``MAC`` address of the actual NIC on the node and the addresses
    of the instances, it could be that starting, stopping or migrating
    instances will lead to timeouts due to the address of the bridge
    (and thus node itself) changing.

    To prevent this, it's enough to set the bridge manually to a
    specific ``MAC`` address, which will disable this automatic address
    change. In Debian, this can be done as follows in the bridge
    configuration snippet::

      up ip link set addr $(cat /sys/class/net/$IFACE/address) dev $IFACE

    which will "set" the bridge address to the initial one, disallowing
    changes.

.. admonition:: Bridging under Debian

   The recommended way to configure the Xen bridge is to edit your
   ``/etc/network/interfaces`` file and substitute your normal
   Ethernet stanza with the following snippet::

     auto xen-br0
     iface xen-br0 inet static
        address %YOUR_IP_ADDRESS%
        netmask %YOUR_NETMASK%
        network %YOUR_NETWORK%
        broadcast %YOUR_BROADCAST_ADDRESS%
        gateway %YOUR_GATEWAY%
        bridge_ports eth0
        bridge_stp off
        bridge_fd 0
        # example for setting manually the bridge address to the eth0 NIC
        up ip link set addr $(cat /sys/class/net/eth0/address) dev $IFACE

The following commands need to be executed on the local console::

  $ ifdown eth0
  $ ifup xen-br0

To check if the bridge is setup, use the ``ip`` and ``brctl show``
commands::

  $ ip a show xen-br0
  9: xen-br0: <BROADCAST,MULTICAST,UP,10000> mtu 1500 qdisc noqueue
      link/ether 00:20:fc:1e:d5:5d brd ff:ff:ff:ff:ff:ff
      inet 10.1.1.200/24 brd 10.1.1.255 scope global xen-br0
      inet6 fe80::220:fcff:fe1e:d55d/64 scope link
         valid_lft forever preferred_lft forever

  $ brctl show xen-br0
  bridge name     bridge id               STP enabled     interfaces
  xen-br0         8000.0020fc1ed55d       no              eth0

In order to have a custom and more advanced networking configuration in Xen
which can vary among instances, after having successfully installed Ganeti
you have to create a symbolic link to the vif-script provided by Ganeti
inside /etc/xen/scripts (assuming you installed Ganeti under /usr/lib)::

  $ ln -s /usr/lib/ganeti/vif-ganeti /etc/xen/scripts/vif-ganeti

This has to be done on all nodes. Afterwards you can set the ``vif_script``
hypervisor parameter to point to that script by::

  $ gnt-cluster modify -H xen-pvm:vif_script=/etc/xen/scripts/vif-ganeti

Having this hypervisor parameter you are able to create your own scripts
and create instances with different networking configurations.

.. _configure-lvm-label:

Configuring LVM
+++++++++++++++

**Mandatory** on all nodes.

The volume group is required to be at least 20GiB.

If you haven't configured your LVM volume group at install time you need
to do it before trying to initialize the Ganeti cluster. This is done by
formatting the devices/partitions you want to use for it and then adding
them to the relevant volume group::

  $ pvcreate /dev/%sda3%
  $ vgcreate xenvg /dev/%sda3%

or::

  $ pvcreate /dev/%sdb1%
  $ pvcreate /dev/%sdc1%
  $ vgcreate xenvg /dev/%sdb1% /dev/%sdc1%

If you want to add a device later you can do so with the *vgextend*
command::

  $ pvcreate /dev/%sdd1%
  $ vgextend xenvg /dev/%sdd1%

Optional: it is recommended to configure LVM not to scan the DRBD
devices for physical volumes. This can be accomplished by editing
``/etc/lvm/lvm.conf`` and adding the ``/dev/drbd[0-9]+`` regular
expression to the ``filter`` variable, like this:

.. code-block:: text

  filter = ["r|/dev/cdrom|", "r|/dev/drbd[0-9]+|" ]

Note that with Ganeti a helper script is provided - ``lvmstrap`` which
will erase and configure as LVM any not in-use disk on your system. This
is dangerous and it's recommended to read its ``--help`` output if you
want to use it.

Installing Ganeti
+++++++++++++++++

**Mandatory** on all nodes.

It's now time to install the Ganeti software itself.  Download the
source from the project page at `<http://code.google.com/p/ganeti/>`_,
and install it (replace 2.6.0 with the latest version)::

  $ tar xvzf ganeti-%2.6.0%.tar.gz
  $ cd ganeti-%2.6.0%
  $ ./configure --localstatedir=/var --sysconfdir=/etc
  $ make
  $ make install
  $ mkdir /srv/ganeti/ /srv/ganeti/os /srv/ganeti/export

You also need to copy the file ``doc/examples/ganeti.initd`` from the
source archive to ``/etc/init.d/ganeti`` and register it with your
distribution's startup scripts, for example in Debian::

  $ chmod +x /etc/init.d/ganeti
  $ update-rc.d ganeti defaults 20 80

In order to automatically restart failed instances, you need to setup a
cron job run the *ganeti-watcher* command. A sample cron file is
provided in the source at ``doc/examples/ganeti.cron`` and you can copy
that (eventually altering the path) to ``/etc/cron.d/ganeti``. Finally,
a sample logrotate snippet is provided in the source at
``doc/examples/ganeti.logrotate`` and you can copy it to
``/etc/logrotate.d/ganeti`` to have Ganeti's logs rotated automatically.

What gets installed
~~~~~~~~~~~~~~~~~~~

The above ``make install`` invocation, or installing via your
distribution mechanisms, will install on the system:

- a set of python libraries under the *ganeti* namespace (depending on
  the python version this can be located in either
  ``lib/python-$ver/site-packages`` or various other locations)
- a set of programs under ``/usr/local/sbin`` or ``/usr/sbin``
- if the htools component was enabled, a set of programs under
  ``/usr/local/bin`` or ``/usr/bin/``
- man pages for the above programs
- a set of tools under the ``lib/ganeti/tools`` directory
- an example iallocator script (see the admin guide for details) under
  ``lib/ganeti/iallocators``
- a cron job that is needed for cluster maintenance
- an init script for automatic startup of Ganeti daemons
- provided but not installed automatically by ``make install`` is a bash
  completion script that hopefully will ease working with the many
  cluster commands

Installing the Operating System support packages
++++++++++++++++++++++++++++++++++++++++++++++++

**Mandatory** on all nodes.

To be able to install instances you need to have an Operating System
installation script. An example OS that works under Debian and can
install Debian and Ubuntu instace OSes is provided on the project web
site.  Download it from the project page and follow the instructions in
the ``README`` file.  Here is the installation procedure (replace 0.12
with the latest version that is compatible with your ganeti version)::

  $ cd /usr/local/src/
  $ wget http://ganeti.googlecode.com/files/ganeti-instance-debootstrap-%0.12%.tar.gz
  $ tar xzf ganeti-instance-debootstrap-%0.12%.tar.gz
  $ cd ganeti-instance-debootstrap-%0.12%
  $ ./configure --with-os-dir=/srv/ganeti/os
  $ make
  $ make install

In order to use this OS definition, you need to have internet access
from your nodes and have the *debootstrap*, *dump* and *restore*
commands installed on all nodes. Also, if the OS is configured to
partition the instance's disk in
``/etc/default/ganeti-instance-debootstrap``, you will need *kpartx*
installed.

.. admonition:: Debian

   Use this command on all nodes to install the required packages::

     $ apt-get install debootstrap dump kpartx

   Or alternatively install the OS definition from the Debian package::

     $ apt-get install ganeti-instance-debootstrap

.. admonition:: KVM

   In order for debootstrap instances to be able to shutdown cleanly
   they must install have basic ACPI support inside the instance. Which
   packages are needed depend on the exact flavor of Debian or Ubuntu
   which you're installing, but the example defaults file has a
   commented out configuration line that works for Debian Lenny and
   Squeeze::

     EXTRA_PKGS="acpi-support-base,console-tools,udev"

   ``kbd`` can be used instead of ``console-tools``, and more packages
   can be added, of course, if needed.

Please refer to the ``README`` file of ``ganeti-instance-debootstrap`` for
further documentation.

Alternatively, you can create your own OS definitions. See the manpage
:manpage:`ganeti-os-interface(7)`.

Initializing the cluster
++++++++++++++++++++++++

**Mandatory** once per cluster, on the first node.

The last step is to initialize the cluster. After you have repeated the
above process on all of your nodes and choose one as the master. Make sure
there is a SSH key pair on the master node (optionally generating one using
``ssh-keygen``). Finally execute::

  $ gnt-cluster init %CLUSTERNAME%

The *CLUSTERNAME* is a hostname, which must be resolvable (e.g. it must
exist in DNS or in ``/etc/hosts``) by all the nodes in the cluster. You
must choose a name different from any of the nodes names for a
multi-node cluster. In general the best choice is to have a unique name
for a cluster, even if it consists of only one machine, as you will be
able to expand it later without any problems. Please note that the
hostname used for this must resolve to an IP address reserved
**exclusively** for this purpose, and cannot be the name of the first
(master) node.

If you want to use a bridge which is not ``xen-br0``, or no bridge at
all, change it with the ``--nic-parameters`` option. For example to
bridge on br0 you can add::

  --nic-parameters link=br0

Or to not bridge at all, and use a separate routing table::

  --nic-parameters mode=routed,link=100

If you don't have a ``xen-br0`` interface you also have to specify a
different network interface which will get the cluster IP, on the master
node, by using the ``--master-netdev <device>`` option.

You can use a different name than ``xenvg`` for the volume group (but
note that the name must be identical on all nodes). In this case you
need to specify it by passing the *--vg-name <VGNAME>* option to
``gnt-cluster init``.

To set up the cluster as an Xen HVM cluster, use the
``--enabled-hypervisors=xen-hvm`` option to enable the HVM hypervisor
(you can also add ``,xen-pvm`` to enable the PVM one too). You will also
need to create the VNC cluster password file
``/etc/ganeti/vnc-cluster-password`` which contains one line with the
default VNC password for the cluster.

To setup the cluster for KVM-only usage (KVM and Xen cannot be mixed),
pass ``--enabled-hypervisors=kvm`` to the init command.

You can also invoke the command with the ``--help`` option in order to
see all the possibilities.

Hypervisor/Network/Cluster parameters
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Please note that the default hypervisor/network/cluster parameters may
not be the correct one for your environment. Carefully check them, and
change them either at cluster init time, or later with ``gnt-cluster
modify``.

Your instance types, networking environment, hypervisor type and version
may all affect what kind of parameters should be used on your cluster.

.. admonition:: KVM

  Instances are by default configured to use a host kernel, and to be
  reached via serial console, which works nice for Linux paravirtualized
  instances. If you want fully virtualized instances you may want to
  handle their kernel inside the instance, and to use VNC.

  Some versions of KVM have a bug that will make an instance hang when
  configured to use the serial console (which is the default) unless a
  connection is made to it within about 2 seconds of the instance's
  startup. For such case it's recommended to disable the
  ``serial_console`` option.


Joining the nodes to the cluster
++++++++++++++++++++++++++++++++

**Mandatory** for all the other nodes.

After you have initialized your cluster you need to join the other nodes
to it. You can do so by executing the following command on the master
node::

  $ gnt-node add %NODENAME%

Separate replication network
++++++++++++++++++++++++++++

**Optional**

Ganeti uses DRBD to mirror the disk of the virtual instances between
nodes. To use a dedicated network interface for this (in order to
improve performance or to enhance security) you need to configure an
additional interface for each node.  Use the *-s* option with
``gnt-cluster init`` and ``gnt-node add`` to specify the IP address of
this secondary interface to use for each node. Note that if you
specified this option at cluster setup time, you must afterwards use it
for every node add operation.

Testing the setup
+++++++++++++++++

Execute the ``gnt-node list`` command to see all nodes in the cluster::

  $ gnt-node list
  Node              DTotal  DFree MTotal MNode MFree Pinst Sinst
  node1.example.com 197404 197404   2047  1896   125     0     0

The above shows a couple of things:

- The various Ganeti daemons can talk to each other
- Ganeti can examine the storage of the node (DTotal/DFree)
- Ganeti can talk to the selected hypervisor (MTotal/MNode/MFree)

Cluster burnin
~~~~~~~~~~~~~~

With Ganeti a tool called :command:`burnin` is provided that can test
most of the Ganeti functionality. The tool is installed under the
``lib/ganeti/tools`` directory (either under ``/usr`` or ``/usr/local``
based on the installation method). See more details under
:ref:`burnin-label`.

Further steps
-------------

You can now proceed either to the :doc:`admin`, or read the manpages of
the various commands (:manpage:`ganeti(7)`, :manpage:`gnt-cluster(8)`,
:manpage:`gnt-node(8)`, :manpage:`gnt-instance(8)`,
:manpage:`gnt-job(8)`).

.. rubric:: Footnotes

.. [#defkernel] The kernel and initrd paths can be changed at either
   cluster level (which changes the default for all instances) or at
   instance level.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
