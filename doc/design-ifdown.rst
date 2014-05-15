======================================
Design for adding ifdown script to KVM
======================================

.. contents:: :depth: 4

This is a design document about adding support for an ifdown script responsible
for deconfiguring network devices and cleanup changes made by the ifup script. The
first implementation will target KVM but it could be ported to Xen as well
especially when hotplug gets implemented.


Current state and shortcomings
==============================

Currently, KVM before instance startup, instance migration and NIC hotplug, it
creates a tap and invokes explicitly the kvm-ifup script with the relevant
environment (INTERFACE, MAC, IP, MODE, LINK, TAGS, and all the network info if
any; NETWORK\_SUBNET, NETWORK\_TAGS, etc).

For Xen we have the `vif-ganeti` script (associated with vif-script hypervisor
parameter). The main difference is that Xen calls it by itself by passing it as
an extra option in the configuration file.

This ifup script can do several things; bridge a tap to a bridge, add ip rules,
update a external DNS or DHCP server, enable proxy ARP or proxy NDP, issue
openvswitch commands, etc.  In general we can divide those actions in two
categories:

1) Commands that change the state of the host
2) Commands that change the state of external components.

Currently those changes do not get cleaned up or modified upon instance
shutdown, remove, migrate, or NIC hot-unplug. Thus we have stale entries in
hosts and most important might have stale/invalid configuration on external
components like routers that could affect connectivity.

A workaround could be hooks but:

1) During migrate hooks the environment is the one held in config data
and not in runtime files. The NIC configuration might have changed on
master but not on the running KVM process (unless hotplug is used).
Plus the NIC order in config data might not be the same one on the KVM
process.

2) On instance modification, changes are not available on hooks. With
other words we do not know the configuration before and after modification.

Since Ganeti is the orchestrator and is the one who explicitly configures
host devices (tap, vif) it should be the one responsible for cleanup/
deconfiguration. Especially on a SDN approach this kind of script might
be useful to cleanup flows in the cluster in order to ensure correct paths
without ping pongs between hosts or connectivity loss for the instance.


Proposed Changes
================

We add an new script, kvm-ifdown that is explicitly invoked after:

1) instance shutdown on primary node
2) successful instance migration on source node
3) failed instance migration on target node
4) successful NIC hot-remove on primary node

If an administrator's custom ifdown script exists (e.g. `kvm-ifdown-custom`),
the `kvm-ifdown` script executes that script, as happens with `kvm-ifup`.

Along with that change we should rename custom ifup script from
`kvm-vif-bridge` (which does not make any sense) to `kvm-ifup-custom`.

In contrary to `kvm-ifup`, one cannot rely on `kvm-ifdown` script to be
called. A node might die just after a successful migration or after an
instance shutdown. In that case, all "undo" operations will not be invoked.
Thus, this script should work "on a best effort basis" and the network
should not rely on the script being called or being successful. Additionally
it should modify *only* the node local dynamic configs (routes, arp entries,
SDN, firewalls, etc.), whereas static ones (DNS, DHCP, etc.) should be modified
via hooks.


Implementation Details
======================

1) Where to get the NIC info?

We cannot account on config data since it might have changed. So the only
place we keep our valid data is inside the runtime file. During instance
modifications (NIC hot-remove, hot-modify) we have the NIC object from
the RPC. We take its UUID and search for the corresponding entry in the
runtime file to get further info. After instance shutdown and migration
we just take all NICs from the runtime file and invoke the ifdown script
for each one

2) Where to find the corresponding TAP?

Currently TAP names are kept under
/var/run/ganeti/kvm-hypervisor/nics/<instance>/<nic\_index>.
This is not enough. As told above a NIC's index might change during instance's
life. An example will make things clear:

* The admin starts an instance with three NICs.
* The admin removes the second without hotplug.
* The admin removes the first with hotplug.

The index that will arrive with the RPC will be 1 and if we read the relevant
NIC file we will get the tap of the NIC that has been removed on second
step but is still existing in the KVM process.

So upon TAP creation we write another file with the same info but named
after the NIC's UUID. The one named after its index can be left
for compatibility (Ganeti does not use it; external tools might)
Obviously this info will not be available for old instances in the cluster.
The ifdown script should be aware of this corner case.

3) What should we cleanup/deconfigure?

Upon NIC hot-remove we obviously want to wipe everything. But on instance
migration we don't want to reset external configuration like DNS.  So we choose
to pass an extra positional argument to the ifdown script (it already has the
TAP name) that will reflect the context it was invoked with. Please note that
de-configuration of external components is not encouraged and should be
done via hooks. Still we could easily support it via this extra argument.

4) What will be the script environment?

In general the same environment passed to ifup script. Except instance's
tags. Those are the only info not kept in runtime file and it can
change between ifup and ifdown script execution. The ifdown
script must be aware of it and should cleanup everything that ifup script
might setup depending on instance tags (e.g. firewalls, etc)


Configuration Changes
~~~~~~~~~~~~~~~~~~~~~

1) The `kvm-ifdown` script will be an extra file installed under the same dir
   `kvm-ifup` resides. We could have a single script (and symbolic links to it)
   that shares the same code, where a second positional argument or an extra
   environment variable would define if we are bringing the interface up or
   down. Still this is not the best practice since it is not equivalent
   with how KVM uses `script` and `downscript` in the `netdev` option; scripts
   are different files that get the tap name as positional argument. Of course
   common code will go in `net-common` so that it can be sourced from either
   Xen or KVM specific scripts.

2) An extra file written upon TAP creation named after the NIC's UUID and
   including the TAP's name. Since this should be the correct file to keep
   backwards compatibility we create a symbolic link named after the NIC's
   index and pointing to this new file.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
