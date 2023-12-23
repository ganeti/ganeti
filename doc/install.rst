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
This documentation will use Debian Bookworm as an example system but the
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

Any system supported by your Linux distribution is fine. Please note that 
official testing is only performed in amd64 environments.

Ganeti offers multiple storage options which may or may not be shared
between two or more nodes. Please note that also with non-shared storage
backends Ganeti is able to move instances between cluster nodes for you.
However, there will be no high-availability features and no live-migration.

Please not that your nodes should all share the same hardware configuration
with regards to CPU, storage throughput and network. Different CPU models will
require you to emulate a common subset of e.g. CPU flags (hence wasting
performance). Different storage systems or NIC speeds will slow down faster
nodes in replicated environments (e.g. with the DRBD, Ceph or GlusterFS
backends).

Installing the base system
++++++++++++++++++++++++++

**Mandatory** on all nodes.

It is advised to start with a clean, minimal install of the operating
system. 

If you plan on using the ``plain`` or ``drbd`` storage backends
please make sure to configure LVM and create a volume group with at least
20GiB of storage assigned.

If you plan on using ``file`` please make sure to have enough available
disk space on your root partition or (**recommended**) a dedicated filesystem
mounted that will hold your instances. We do not recommend any specific type
of filesystem at this time.

If you plan on using ``sharedfile`` please make sure all your nodes have
access to the shared storage (e.g. NFS). 

If you plan on using ``rbd`` (Ceph) or ``gluster`` you need to setup that
first. This will not be covered by this document. 

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
live system are Xen (both in PVM and HVM mode) and KVM. Supported Xen
versions are: 3.0.3 and later 3.x versions, and 4.x (tested up to 4.1).
Supported KVM versions are 72 and above.

Please follow your distribution's recommended way to install and set up
Xen, or install Xen from the upstream source, if you wish, following
their manual. For KVM, make sure you have a KVM-enabled kernel and the
KVM tools.

After installing Xen, you need to reboot into your new system. On some
distributions this might involve configuring GRUB appropriately, whereas
others will configure it automatically when you install the respective
kernels. For KVM no reboot should be necessary.

.. admonition:: Xen on Debian

   Under Debian you can install the relevant ``xen-system-amd64``
   package, which will pull in both the hypervisor and the relevant
   kernel. 

.. admonition:: KVM on Debian

   It should be sufficient to install the packages ``qemu-kvm`` and
   ``qemu-utils``.

Xen settings
~~~~~~~~~~~~

Some useful best practices for Xen are to restrict the amount of memory
dom0 has available, and pin the dom0 to a limited number of CPUs.
Instructions for how to achieve this for various toolstacks can be found
on the Xen wiki_.

.. _wiki: http://wiki.xenproject.org/wiki/Xen_Project_Best_Practices

It is recommended that you disable Xen's automatic save of virtual
machines at system shutdown and subsequent restore of them at reboot.
To obtain this make sure the variable ``XENDOMAINS_SAVE`` in the file
``/etc/default/xendomains`` is set to an empty value.

You may need to restart the Xen daemon for some of these settings to
take effect. The best way to do this depends on your distribution.


Selecting the instance kernel
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

After you have installed Xen, you need to tell Ganeti exactly what
kernel to use for the instances it will create. This is done by creating
a symlink from your actual kernel to ``/boot/vmlinuz-3-xenU``, and one
from your initrd to ``/boot/initrd-3-xenU`` [#defkernel]_. Note that
if you don't use an initrd for the domU kernel, you don't need to create
the initrd symlink.

.. _configure-lvm-label:

Configuring LVM
+++++++++++++++

**Mandatory** on all nodes if you want to use ``plain`` or ``DRBD``
storage backends.

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

Optional: it is recommended to only scan relevant devices for LVM signatures.
Otherwise the LVM on your node might find LVM signatures *inside* your
instance's disks and activate them on the node!

This can be accomplished by editing ``/etc/lvm/lvm.conf`` and adding your
devices as regular expression to the ``global_filter`` variable, like this:

.. code-block:: text

  global_filter = [ "a|^/dev/(sd|nvme).+$|", "r/.*/" ]

Note that with Ganeti a helper script is provided - ``lvmstrap`` which
will erase and configure as LVM any not in-use disk on your system. This
is dangerous and it's recommended to read its ``--help`` output if you
want to use it.

Installing DRBD
+++++++++++++++

DRBD_ is one option if you want to use the high-availability (HA) features
of Ganeti, but optional if you don't require them or only run Ganeti on
single-node clusters. You can upgrade a non-HA cluster to an HA one later,
but you might need to convert all your instances to DRBD to take advantage
of the new features.

.. _DRBD: http://www.drbd.org/

Supported DRBD versions: 8.0-8.4. It's recommended to have at least
version 8.0.12. Note that for version 8.2 and newer it is needed to pass
the ``usermode_helper=/bin/true`` parameter to the module, either by
configuring ``/etc/modules`` or when inserting it manually. When using
Xen and DRBD 8.3.2 or higher with Xen, it is recommended_ to use the
``disable_sendpage=1`` setting as well.

.. _recommended: https://docs.linbit.com/docs/users-guide-8.4/#s-xen-drbd-mod-params

.. admonition:: Debian

   On Debian, you only need to install the drbd utils with the
   following command, making sure you are running the target (Xen or
   KVM) kernel::

     $ apt-get install drbd8-utils

   Then to configure it for Ganeti::

     $ echo "options drbd minor_count=128 usermode_helper=/bin/true" \
        > /etc/modprobe.d/drbd.conf
     $ echo "drbd" >> /etc/modules
     $ depmod -a
     $ modprobe drbd

Installing RBD
++++++++++++++

Another way of making use of Ganeti's high-availability features is to
configure and install RBD_ (Ceph) on all of your nodes.

.. _RBD: https://ceph.com/en/users/getting-started/

Documenting the steps required to use RBD is out of scope for this document.
Please refer to your distribution's documentation or to the official Ceph
documentation to find the optimal way to install RBD in your environment.


Installing Gluster
++++++++++++++++++

For GlusterFS_ integration, Ganeti requires that ``mount.glusterfs`` is
installed on each and every node. On Debian systems, you can satisfy this
requirement with the ``glusterfs-client`` package. Further steps for optimal
GlusterFS configuration are out of scope for this document. Please refer to
your distribution's documentation or to the official GlusterFS documentation
to find the optimal way to install GlusterFS in your environment.

.. _GlusterFS: https://docs.gluster.org/en/latest/Quick-Start-Guide/Quickstart/

Other required software
+++++++++++++++++++++++

If you plan on building Ganeti yourself, please install all (build) dependencies
as noted in the `INSTALL` file. If you use your distribution's packages there
is nothing more to do here.

Setting up the environment for Ganeti
-------------------------------------

Configuring the network
+++++++++++++++++++++++

**Mandatory** on all nodes.

Ganeti can operate on a single network interface but you can also split
this into up to three separate interfaces:

.. admonition:: The main interface

  This interface will hold your Ganeti node's main/public IP address and this
  is where you will most likely SSH in for management. A cluster also has a
  dedicated cluster IP address which will be configured by Ganeti on the master
  node on this interface.

.. admonition:: The replication interface

  This optional interface will only be used for replication (e.g. DRBD) 
  and live migration traffic. If not configured, said traffic will use the
  main interface. You need to make sure all nodes are connected to this network
  and can reach each other.

.. admonition:: The instance network

  You will most likely use a bridge to connect your instances to the outside
  world. While you *could* make this bridge your main interface you can also
  configure the bridge to use a separate interface and hence separate instance
  traffic from replication and management/cluster traffic. With vlan-aware
  bridges (only supported with KVM) you can provision instances easily on
  different vlans without altering your node's configuration (e.g. create one
  bridge per vlan).

You can use plain network interfaces or make use of the linux bonding driver
to achieve redundant connectivity for each of the above.

In additional to "bridged mode" Ganeti also supports "routed mode" or
"openvswitch mode" for your instance network.

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

It is recommended to use a dedicated network interface for your instances

.. admonition:: Bridging under Debian

   The recommended way to configure the bridge is to edit your
   ``/etc/network/interfaces`` file and substitute your normal
   Ethernet stanza with the following snippet if you want to
   have instance traffic on your main network interface::

    auto gnt-bridge
    iface gnt-bridge inet static
      address %YOUR_IP_ADDRESS%/%YOUR_PREFIX%
      gateway %YOUR_GATEWAY%
      bridge_ports eth0
      bridge_stp off
      bridge_waitport 0
      bridge_fd 0

   The following configures a bridge to a dedicated interface
   (``eth1``) and also enables vlan-aware bridging::

    auto gnt-bridge
    iface gnt-bridge inet manual
      bridge_ports eth1
      bridge_vlan_aware yes
      bridge_stp off
      bridge_waitport 0
      bridge_fd 0

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

Installing Ganeti
+++++++++++++++++

**Mandatory** on all nodes.

.. admonition:: Use distribution packages

  If possible use your distribution's packages. For Debian you only need
  to install ``ganeti`` and ``ganeti-3.0``.

It's now time to install the Ganeti software itself.  Download the
source from the project page at `<https://github.com/ganeti/ganeti/releases>`_,
and install it (replace 3.0.2 with the latest version)::

  $ tar xvzf ganeti-%3.0.2%.tar.gz
  $ cd ganeti-%3.0.2%
  $ ./configure --localstatedir=/var --sysconfdir=/etc
  $ make
  $ make install
  $ mkdir /srv/ganeti/ /srv/ganeti/os /srv/ganeti/export

You also need to copy the file ``doc/examples/ganeti.initd`` from the
source archive to ``/etc/init.d/ganeti`` and register it with your
distribution's startup scripts, for example in Debian::

  $ chmod +x /etc/init.d/ganeti
  $ update-rc.d ganeti defaults 20 80

There are also unit files provided for use with systemd: ``doc/examples/systemd``

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
- an init script or systemd unit files for automatic startup of Ganeti daemons
- provided but not installed automatically by ``make install`` is a bash
  completion script that hopefully will ease working with the many
  cluster commands

Installing the Operating System support packages
++++++++++++++++++++++++++++++++++++++++++++++++

**Mandatory** on all nodes.

To be able to install instances you need to have an Operating System
installation script. An example OS that works under Debian and can
install Debian and Ubuntu instace OSes is provided on the project web
site. Download it from the project page and follow the instructions in
the ``README`` file.  Here is the installation procedure (replace 0.14
with the latest version that is compatible with your ganeti version)::

  $ cd /usr/local/src/
  $ wget https://github.com/ganeti/instance-debootstrap/archive/v%0.16%.tar.gz
  $ tar xzf v%0.16%.tar.gz
  $ cd instance-debootstrap-%0.16%
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

Please refer to the ``README`` file of ``ganeti-instance-debootstrap`` for
further documentation.

.. admonition:: no-op OS Provider

  On Debian you can also install ``ganeti-os-noop``. This dummy OS provider
  will not do anything and can be used to e.g. bootstrap KVM instances using
  PXE boot.

Alternatively, you can create your own OS definitions. See the manpage
:manpage:`ganeti-os-interface(7)`.

Initializing the cluster
++++++++++++++++++++++++

**Mandatory** once per cluster, on the first node.

The last step is to initialize the cluster. After you have repeated the
above process on all of your nodes and choose one as the master. Make sure
there is a SSH key pair on the master node (optionally generating one using
``ssh-keygen``). Before we can run the command ``gnt-cluster init``, we need
to decide how this cluster is supposed to operate.

.. admonition:: Hypervisor selection

  Choose which hypervisor to enable::

    --enabled-hypervisor kvm [or xen-pvm, xen-hvm]

.. admonition:: LVM

  If you have LVM included in your setup, you may need to specify your volume
  group's name::

   --vg-name vg-ganeti

.. admonition:: Network

  You need to specify your main network interface (e.g. where your node's main
  IP address resides). Ganeti will use this interface to configure the cluster
  IP address on the master node::

   --master-netdev eth0

  Each Ganeti cluster has a name which needs to resolve to an available IP on
  your node's IP network. Ganeti will resolve the IP address by itself but you
  need to specify the netmask that goes along with it::

   --master-netmask 24

  You should also configure the default network, the following configures your
  instances to use 'bridged mode' with ``gnt-bridge`` as default bridge::

   --nic-parameters mode=bridged,link=gnt-bridge

.. admonition:: Storage

  You can enable multiple storage backends (comma separated), but choose at
  least one::

   --enabled-disk-templates drbd [,plain,file,...]

  Please note that most storage backends require additional parameters -
  refer to :manpage:`gnt-cluster(8)` for additional details.

.. admonition:: iAllocator

  While you *can* place your instances manually on your cluster it is recommended
  to use an iallocator script for this. Ganeti ships ``hail`` as a built-in
  solution and it should be enabled by default::

   --default-iallocator hail

.. admonition:: Hypervisor parameters

  It is a good practice to set sane default hypervisor parameters for all of your
  instances (they can still be overriden at instance level later). The following
  configures KVM for full boot emulation and makes all of the node's CPU features
  available to the guest (if you plan on using live migration all CPUs on your
  cluster need to be the same for this to work!)::

   --hypervisor-parameters kvm:kernel_path=,initrd_path=,cpu_type=host

  Please refer to :manpage:`gnt-instance(8)` for a full list of hypervisor
  parameters and their values/defaults.


Finally execute::

  $ gnt-cluster init [your parameters here] %CLUSTERNAME%

The *CLUSTERNAME* is a hostname, which must be resolvable (e.g. it must
exist in DNS or in ``/etc/hosts``) by all the nodes in the cluster. You
must choose a name different from any of the nodes names for a
multi-node cluster. In general the best choice is to have a unique name
for a cluster, even if it consists of only one machine, as you will be
able to expand it later without any problems. Please note that the
hostname used for this must resolve to an IP address reserved
**exclusively** for this purpose, and cannot be the name of the first
(master) node.

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
