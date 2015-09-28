===============
MacVTap support
===============

.. contents:: :depth: 3

This is a design document detailing the implementation of `MacVTap`
support in Ganeti. The initial implementation targets the KVM
hypervisor, but it is intended to be ported to the XEN hypervisor as
well.

Current state and shortcomings
==============================

Currently, Ganeti provides a number of options for networking a virtual
machine, that are the ``bridged``, ``routed``, and ``openvswitch``
modes.  ``MacVTap``, is another virtual network interface in Linux, that
is not supported by Ganeti and that could be added to the currently
supported solutions. It is an interface that acts as a regular TUN/TAP
device, and thus it is transparently supported by QEMU. Because of its
design, it can greatly simplify Ganeti setups using bridged instances.

In brief, the MacVTap interface is based on the ``MacVLan`` Linux
driver, which basically allows a single physical interface to be
associated with multiple IPs and MAC addresses. It is meant to replace
the combination of the TUN/TAP and bridge drivers with a more
lightweight setup that doesn't require any extra configuration on the
host. MacVTap driver is supposed to be more efficient than using a
regular bridge.  Unlike bridges, it doesn't need to do STP or to
discover/learn MAC addresses of other connected devices on a given
domain, as it it knows every MAC address it can receive. In fact, it
introduces a bridge-like behavior for virtual machines but without the
need to have a real bridge setup on the host. Instead, each virtual
interface extends an existing network device by attaching directly to
it, having its own MAC address, and providing a separate virtual
interface to be used by the userspace processes. The MacVTap MAC address
is used on the external network and the guest OS cannot spoof or change
that address.

Background
==========

This section provides some extra information for the MacVTap interface,
that we took into account for the rest of this design document.

MacVTap modes of operation
--------------------------

A MacVTap device can operate in one of four modes, just like the MacVLan
driver does. These modes determine how the tap endpoints communicate
between each other providing various levels of isolation between them.
Those modes are the following:

* `VEPA (Virtual Ethernet Port Aggregator) mode`: The default mode that
  is compatible with virtualization-enabled switches. The communication
  between endpoints on the same lower device, happens through the
  external switch.

* `Bridge mode`: It works almost like a traditional bridge, connecting
  all endpoints directly to each other.

* `Private mode`: An endpoint in this mode can never communicate to any
  other endpoint on the same lower device.

* `Passthru mode`: This mode was added later to work on some limitations
  on MacVLans (more details here_).

MacVTap internals
-----------------

The creation of a MacVTap device is *not* done by opening the
`/dev/net/tun` device and issuing a corresponding `ioctl()` to register
a network device as happens in tap devices. Instead, there are two ways
to create a MacVTap device. The first one is using the `rtnetlink(7)`
interface directly, just like the `libvirt` or the `iproute2` utilities
do, and the second one is to use the high-level `ip-link` command. Since
creating a MacVTap interface programmatically using the netlink protocol
is a bit more complicated than creating a normal TUN/TAP device, we
propose using the ip-link tool for the MacVTap handling, which it is
much simpler and straightforward in use, and also fulfills all our
needs. Additionally, since Ganeti already depends on `iproute2` being
installed in the system, this does not introduces an extra dependency.

The following example, creates a MacVTap device using the `ip-link`
tool, named `macvtap0`, operating in `bridge` mode, and which is using
`eth0` as its lower device:

::

  ip link add link eth0 name macvtap0 address 1a:36:1b:aa:b3:77 type macvtap mode bridge

Once a MacVTap interface is created, an actual character device appears
under `/dev`, called ``/dev/tapXX``, where ``XX`` is the interface index
of the device.

Proposed changes
================

In order to be able to create instances using the MacVTap device driver,
we propose some modifications that affect the ``nicparams`` slot of the
Ganeti's configuration ``NIC`` object, and also the code part regarding
to the KVM hypervisor, as detailed in the following sections.

Configuration changes
---------------------

The nicparams ``mode`` attribute will be extended to support the
``macvtap`` mode. When using the MacVTap mode, the ``link`` attribute
will specify the network device where the MacVTap interfaces will be
attached to, the *lower device*. Note that the lower device should
exists, otherwise the operation will fail. If no link is specified, the
cluster-wide default NIC `link` param will be used instead.

We propose the MacVTap mode to be configurable, and so the nicparams
object will be extended with an extra slot named ``mvtap_mode``. This
parameter will only be used if the network mode is set to MacVTap since
it does not make sense in other modes, similarly to the `vlan` slot of
the `openvswitch` mode.

Below there is a snippet of some of the ``gnt-network`` commands'
output:

Network connection
~~~~~~~~~~~~~~~~~~

::

  gnt-network connect -N mode=macvtap,link=eth0,mvtap_mode=bridge vtap-net vtap_group

Network listing
~~~~~~~~~~~~~~~

::

  gnt-network list

  Network  Subnet           Gateway       MacPrefix GroupList
  br-net   10.48.1.0/24     10.48.1.254   -         default (bridged, br0, , )
  vtap-net 192.168.100.0/24 192.168.100.1 -         vtap_group (macvtap, eth0, , bridge)

Network information
~~~~~~~~~~~~~~~~~~~

::

  gnt-network info

  Network name: vtap-net
  UUID: 4f139b48-3f08-46b1-911f-d37de7e12dcf
  Serial number: 1
  Subnet: 192.168.100.0/28
  Gateway: 192.168.100.1
  IPv6 Subnet: 2001:db8:2ffc::/64
  IPv6 Gateway: 2001:db8:2ffc::1
  Mac Prefix: None
  size: 16
  free: 10 (62.50%)
  usage map:
        0 XXXXX..........X                                   63
         (X) used    (.) free
  externally reserved IPs:
    192.168.100.0, 192.168.100.1, 192.168.100.15
  connected to node groups:
    vtap_group (mode:macvtap link:eth0 vlan: mvtap_mode:bridge)
  used by 2 instances:
    inst1.example.com: 0:192.168.100.2
    inst2.example.com: 0:192.168.100.3


Hypervisor changes
------------------

A new method will be introduced in the KVM's `netdev.py` module, named
``OpenVTap``, similar to the ``OpenTap`` method, that will be
responsible for creating a MacVTap device using the `ip-link` command,
and returning its file descriptor. The ``OpenVtap`` method will receive
as arguments the network's `link`, the mode of the MacVTap device
(``mvtap_mode``), and also the ``interface name`` of the device to be
created, otherwise we will not be able to retrieve it, and so opening
the created device.

Since we want the names among the MacVTap devices to be unique on the
same node, we will make use of the existing ``_GenerateKvmTapName``
method to generate device names but with some modifications, to be
adapted to our needs. This method is actually a wrapper over the
``GenerateTapName`` method which currently is being used to generate TAP
interface names for NICs meant to be used in instance communication
using the ``gnt.com`` prefix. We propose extending this method to
generate names for the MacVTap interface too, using the ``vtap`` prefix.
To do so, we could add an extra boolean argument in that method, named
`inst_comm`, to differentiate the two cases, so that the method will
return the appropriate name depending on its usage. This argument will
be optional and defaulted to `True`, to not affect the existing API.

Currently, the `OpenTap` method handles the `vhost-net`, `mq`, and the
`vnet_hdr` features. The `vhost-net` feature will be normally supported
for the MacVTap devices too, and so is the `multiqueue` feature, which
can be enabled using the `numrxqueues` and `numtxqueues` parameters of
the `ip-link` command. The only drawback seems to be the `vnet_hdr`
feature modification. For a MacVTap device this flag is enabled by
default, and it can not be disabled if a user requests to.

A last hypervisor change will be the introduction of a new method named
``_RemoveStaleMacvtapDevs`` that will remove any remaining MacVTap
devices, and which is detailed in the following section.

Tools changes
-------------

Some of the Ganeti tools should also be extended to support MacVTap
devices. Those are the ``kvm-ifup`` and ``net-common`` scripts. These
modifications will include a new method named ``setup_macvtap`` that
will simply change the device status to `UP` just before and instance is
started:

::

  ip link set $INTERFACE up

As mentioned in the `Background` section, MacVTap devices are
persistent. So, we have to manually delete the MacVTap device after an
instance shutdown. To do so, we propose creating a ``kvm-ifdown``
script, that will be invoked after an instance shutdown in order to
remove the relevant MacVTap devices. The ``kvm-ifdown`` script should
explicitly call the following commands and currently will be functional
for MacVTap NICs only:

::

  ip link set $INTERFACE down
  ip link delete $INTERFACE

To be able to call the `kvm-ifdown` script we should extend the KVM's
``_ConfigureNIC`` method with an extra argument that is the name of the
script to be invoked, instead of calling by default the `kvm-ifup`
script, as it currently happens.

The invocation of the `kvm-ifdown` script will be made through a
separate method that we will create, named ``_RemoveStaleMacvtapDevs``.
This method will read the NIC runtime files of an instance and will
remove any devices using the MacVTap interface. This method will be
included in the ``CleanupInstance`` method in order to cover all the
cases where an instance using MacVTap NICs needs to be cleaned up.

Besides the instance shutdown, there are a couple of cases where the
MacVTap NICs will need to be cleaned up too. In case of an internal
instance shutdown, where the ``kvmd`` is not enabled, the instance will
be in ``ERROR_DOWN`` state. In that case, when the instance is started
either by the `ganeti-watcher` or by the admin, the ``CleanupInstance``
method, and consequently the `kvm-ifdown` script, will not be called and
so the MacVTap NICs will have to manually be deleted. Otherwise starting
the instance will result in more than one MacVTap devices using the same
MAC address. An instance migration is another case where deleting an
instance will keep stale MacVTap devices on the source node.  In order
to solve those potential issues, we will explicitly call the
``_RemoveStaleMacvtapDevs`` method after a successful instance migration
on the source node, and also before creating a new device for a NIC that
is using the MacVTap interface to remove any stale devices.

.. _here: http://thread.gmane.org/gmane.comp.emulators.kvm.devel/61824/)

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
