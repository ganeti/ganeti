Ganeti Instance Network Configuration
=====================================

.. contents::

Introduction
------------

Beginning with Ganeti 3.2 the instance networking configuration has
been refactored so that it is more accessible and easier to adapt to
custom network deployments. The per-mode network logic is split across
two directory trees:

- **Built-in scripts** live under
  ``@PKGLIBDIR@/network/<mode>/{up,down}``. They are versioned with the
  rest of Ganeti and are updated on every package upgrade.

- **User override scripts** live under
  ``@SYSCONFDIR@/ganeti/network/<mode>/{up,down}``. A script placed here takes
  precedence over the built-in and survives package upgrades unchanged.

This separation makes it straightforward to customise the setup for any
single mode without touching the others, and without risk of losing
local changes on upgrade.


Network Modes
-------------

Ganeti supports four different network modes. The mode is selected
via the ``mode`` NIC parameter (e.g.
``gnt-instance add -n node1 --net 0:mode=bridged,link=br0 ...``).
All modes accept the common NIC parameters ``mode``, ``link`` and
``vlan``; what each parameter means differs per mode and is described
below.


bridged
~~~~~~~

This is probably the most common network mode. It expects the host to
have layer 2 connectivity to one or multiple (v)lans. All instance
network interfaces are connected to one or more Linux bridge devices on
the host which must be configured outside of Ganeti. You may use both
VLAN-aware (KVM only) or VLAN-unaware bridges.

Parameters:

``link`` (required)
  Name of the Linux bridge device on the host (e.g. ``br0``).

``vlan`` (optional)
  VLAN configuration for use with VLAN-aware bridges. When set, the
  bridge must have ``vlan_filtering`` enabled and should normally also
  be configured with ``vlan_default_pvid 0`` to avoid an untagged VID 1
  leak — see `VLAN-aware bridge setup`_ for details. The format follows
  the notation used by ``gnt-instance``; see `VLAN parameter format`_
  for details.

The ``up`` script fixes the TAP device MAC address (setting the first
octet to ``fe`` to discourage the bridge from adopting it), brings the
interface up, matches its MTU to the bridge and adds it as a bridge
port. If ``vlan`` is set, VLAN filtering rules are configured on the
TAP and on all non-TAP bridge uplink ports.


.. _vlan-aware-bridge-setup:

VLAN-aware bridge setup
^^^^^^^^^^^^^^^^^^^^^^^

When a VLAN-aware bridge is created, the Linux kernel assigns VID 1 as
PVID / Egress Untagged to the bridge itself, and it auto-adds VID 1 with
the same attributes to every port subsequently joined to the bridge —
including the TAP devices that Ganeti creates for instance NICs.

Ganeti's ``up`` script configures the NIC's requested VLAN (with
``pvid untagged`` for access and hybrid ports) but does **not** remove
the kernel-added VID 1 from the TAP. As a consequence, an instance that
was configured as an "access port on VLAN *N*" will also receive any
untagged traffic that reaches the bridge on VID 1. For most deployments
this is surprising and undesirable.

The recommended way to avoid this is to configure the bridge with
``vlan_default_pvid 0`` in addition to ``vlan_filtering 1``. With no
default PVID, neither the bridge nor newly-added ports carry VID 1 by
default, and the VLAN configuration applied by Ganeti becomes the single
source of truth for each TAP.

Using ``iproute2`` (e.g. from an ifupdown ``post-up`` hook)::

    ip link set dev gnt-br type bridge \
        vlan_filtering 1 vlan_default_pvid 0

Using ``systemd-networkd`` (``/etc/systemd/network/gnt-br.netdev``)::

    [NetDev]
    Name=gnt-br
    Kind=bridge

    [Bridge]
    VLANFiltering=yes
    DefaultPVID=none

.. warning::
   If the host itself has an IP address on the bridge, disabling the
   default PVID (or otherwise removing VID 1) can break node
   connectivity unless another VLAN is configured to carry host
   traffic. Plan the migration accordingly.

.. note::
   ``vlan_default_pvid`` only affects ports added *after* the setting
   has been changed. Existing TAPs and uplinks keep their previously
   assigned VID 1 until it is removed explicitly (e.g.
   ``bridge vlan del dev <port> vid 1 master`` for ports, or
   ``bridge vlan del dev gnt-br vid 1 self`` for the bridge itself) or
   the port is detached and re-added.

Leaving the kernel default in place is a legitimate choice if you
deliberately want some instances to receive untagged traffic on VID 1.
In that case it is the administrator's responsibility to prune VID 1
from the TAPs of instances that should not see it, either via a custom
override script under
``@SYSCONFDIR@/ganeti/network/bridged/up`` or via out-of-band tooling.


routed
~~~~~~

In routed mode, the host acts as a router for the instance. A host
route is installed for the instance's IP address pointing at the TAP
device, and proxy ARP (IPv4) or proxy NDP (IPv6) is enabled so that
the host answers neighbour requests on behalf of the instance.

Parameters:

``ip`` (required, set on the NIC itself, not as a NIC parameter)
  The IP address of the instance. Routed mode will refuse to bring
  up an interface that has no IP address assigned.

``link`` (optional)
  Name of a routing table (as listed in ``/etc/iproute2/rt_tables``).
  When set, a policy rule is created to direct traffic arriving on the
  TAP device into this table, and the host route is installed there
  instead of the main table. This is useful for multi-homed setups or
  when you need to keep instance traffic in a separate routing domain.

The ``up`` script brings the interface up, installs the host route
(optionally in the specified table), and enables
``proxy_arp``/``forwarding`` (IPv4) and ``proxy_ndp``/``forwarding``
(IPv6) on the interface.


openvswitch
~~~~~~~~~~~

Open vSwitch mode connects instance interfaces to an OVS bridge.
This is suitable for environments that use OpenFlow-based switching
or need advanced features such as per-port VLAN tagging, tunnelling
or flow-based forwarding. Open vSwitch must be configured / managed
outside of Ganeti.

Parameters:

``link`` (required)
  Name of the Open vSwitch bridge (e.g. ``br-int``).

``vlan`` (optional)
  VLAN configuration. When set, the access VLAN is applied as the
  port tag and any trunk VLANs are configured via the OVS ``trunks``
  property. See `VLAN parameter format`_ for the notation.

The ``up`` script removes any stale OVS port for the interface,
brings the interface up, adds it to the OVS bridge, and applies
access/trunk VLAN settings as needed.

.. note::
   Open vSwitch mode is also available under Xen. In that case, the
   OVS bridge name (and optional VLAN suffix) is passed via the
   ``bridge`` argument in the Xen domain configuration.

.. _ext-mode:

ext (Custom / External Networking Scripts)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This network mode is specifically meant for situations where you want to
implement a custom network logic and not have Ganeti make any assumptions
about it. While you can also modify the specific ``up``/``down`` scripts
of the other network modes, Ganeti has specific assumptions for each one
(e.g. required parameters, allowed values) which might get in your way.

In ``ext`` mode, **no built-in scripts are provided**. You must place
your own ``up`` and ``down`` scripts in
``@SYSCONFDIR@/ganeti/network/ext/``. Starting or stopping a NIC in ``ext``
mode without the corresponding script present is a hard error. All
standard `environment variables`_ are available to the scripts.

.. note::
   ``ext`` mode is **not supported** for the Xen hypervisor.


.. _vlan-format:

VLAN parameter format
~~~~~~~~~~~~~~~~~~~~~

The ``vlan`` NIC parameter uses the following notation (shared by
``bridged`` and ``openvswitch`` modes):

``.VID``
  Access (untagged) port. A single VLAN ID prefixed with a dot.
  Example: ``.100``

``:VID[:VID2[:VID3...]]``
  Trunk (tagged) port. One or more VLAN IDs separated by colons,
  with a leading colon. Example: ``:100:200:300``

``.VID:VID2[:VID3...]``
  Hybrid port. The first (dot-prefixed) VLAN ID is the native
  (untagged) VLAN; the remaining colon-separated IDs are carried
  tagged. Example: ``.100:200:300``

.. note::
   For ``bridged`` mode, the access-port semantics above only hold when
   the bridge is configured with ``vlan_default_pvid 0``. Otherwise the
   kernel-assigned VID 1 remains present on each TAP in addition to the
   VLAN(s) requested here, and untagged traffic reaching the bridge
   will leak into the instance. See `VLAN-aware bridge setup`_.


Important Files and Folders
---------------------------

Script directory structure
~~~~~~~~~~~~~~~~~~~~~~~~~~

For the built-in modes (``bridged``, ``routed``, ``openvswitch``),
Ganeti ships ready-to-use scripts in the versioned library directory::

  @PKGLIBDIR@/network/
  +-- bridged/
  |   +-- up
  |   +-- down
  +-- routed/
  |   +-- up
  |   +-- down
  +-- openvswitch/
  |   +-- up
  |   +-- down

To override or extend the behaviour of any built-in mode, place a
replacement script in the corresponding sub-directory under
``@SYSCONFDIR@/ganeti/network/``. A script found there takes precedence over
the built-in::

  @SYSCONFDIR@/ganeti/network/          (user overrides and ext scripts)
  +-- bridged/
  |   +-- up                    ← overrides @PKGLIBDIR@/network/bridged/up
  |   +-- down                  ← overrides @PKGLIBDIR@/network/bridged/down
  +-- routed/
  |   +-- (same pattern)
  +-- openvswitch/
  |   +-- (same pattern)
  +-- ext/
      +-- up                    ← required; no built-in exists
      +-- down                  ← required; no built-in exists

All scripts are executed with the `environment variables`_ described
below.


Wrapper scripts
~~~~~~~~~~~~~~~

The per-mode scripts are not called directly by the hypervisor
drivers. Instead, a thin wrapper script dispatches to the correct
mode/action combination:

``kvm-nic-setup`` (KVM)
  Installed in ``@PKGLIBDIR@``.
  Called by Ganeti's KVM hypervisor driver before the instance starts
  (for ``up``) and after it stops or migrates away (for ``down``).
  The wrapper sources ``net-common``, performs basic sanity checks
  (``INTERFACE`` and ``MODE`` must be set), and then dispatches using
  the following lookup order:

  1. ``@SYSCONFDIR@/ganeti/network/${MODE}/${ACTION}`` (user override)
  2. ``@PKGLIBDIR@/network/${MODE}/${ACTION}`` (built-in)

  For ``ext`` mode, only step 1 is attempted; if the script is absent
  the wrapper exits with an error. For all other modes, a missing
  script at both locations is also a hard error.

``vif-ganeti`` (Xen)
  Installed in ``@PKGLIBDIR@``. Called by Xen itself (via the
  ``vif-script`` domain configuration parameter) when a VIF is
  brought up. It sources the NIC environment from a runtime file
  written by Ganeti under ``/var/run/ganeti/xen-hypervisor/nic/``
  and then dispatches to ``@SYSCONFDIR@/ganeti/network/${MODE}/up``.

  .. note::
     Xen currently only supports the ``up`` action. There is no
     ``down`` callback from Xen when a VIF is removed.

Both wrappers also support an override mechanism for full custom
control:

- **KVM:** If the interface is an instance communication TAP (name
  starts with ``gnt.com``) and ``@SYSCONFDIR@/ganeti/kvm-ifup-os`` exists,
  that script is executed instead.

- **Xen:** If ``@XEN_CONFIG_DIR@/scripts/vif-custom`` exists, it is
  executed instead of the normal dispatch logic.


.. _env-vars:

Environment Variables
---------------------

The network configuration scripts receive the following environment
variables. They are set by the hypervisor driver before executing the
wrapper script.

Variables that are always present
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``INSTANCE``
  The name of the instance whose NIC is being configured.

``MAC``
  The MAC address assigned to the instance NIC.

``MODE``
  The network mode: ``bridged``, ``routed``, ``openvswitch`` or
  ``ext``.

``INTERFACE``
  The name of the host-side TAP (KVM) or VIF (Xen) device.

``INTERFACE_INDEX``
  The zero-based sequence number of the NIC within the instance
  (``0``, ``1``, ``2``, ...).

``INTERFACE_UUID``
  The UUID of the NIC object.

``TAGS``
  A space-separated list of the instance's tags.

``ACTION``
  Either ``up`` or ``down``. For KVM, both actions are supported.
  For Xen, only ``up`` is currently used.


Variables that are conditionally present
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``IP``
  The IP address assigned to the NIC. Only set when the NIC has an
  IP address configured (mandatory for routed mode).

``INTERFACE_NAME``
  The user-defined name of the NIC (e.g. ``eth0``). Only set when a
  name has been assigned to the NIC.

``LINK``
  The value of the ``link`` NIC parameter. Its meaning depends on
  the mode: bridge device name (bridged), OVS bridge name
  (openvswitch), routing table name (routed).

``VLAN``
  The value of the ``vlan`` NIC parameter. Only set when the NIC
  has a VLAN configuration.

``BRIDGE``
  Set only in ``bridged`` mode; contains the same value as ``LINK``
  (the bridge device name). Provided for convenience.

``MIGRATION_PHASE``
  Set only during live migration on the destination node. The value is
  ``pre`` when the script is called before the migration starts, or
  ``post`` when it is called after the migration has completed
  successfully. Not set during normal instance start/stop or hot-plug.
  Currently only passed for ``routed`` (``post`` only) and ``ext``
  (``pre`` and ``post``) modes. See `Migration behaviour`_ for details.

``NETWORK_*``
  When the NIC is connected to a Ganeti network object, additional
  variables describing the network are exported. These include the
  network's name, subnet, gateway, tags and other properties as
  returned by the network object's hooks dictionary.


When are the scripts called?
----------------------------

KVM
~~~

The ``up`` script is called:

- Before an instance is started (once per NIC).
- During live migration on the destination node — see `Migration
  behaviour`_ below for per-mode details.
- When a NIC is hot-added to a running instance.

The ``down`` script is called:

- When an instance is shut down on its primary node.
- On the migration source after a successful migration.
- On the migration target after a failed migration (if the instance
  process is no longer alive).
- When a NIC is hot-removed from a running instance.

.. note::
   Down scripts are best-effort. They should only perform node-local
   cleanup of dynamic state (e.g. removing firewall rules) in an
   idempotent way. For static configuration (DNS records, DHCP
   leases) use Ganeti hooks instead.


.. _migration-behaviour:

Migration behaviour
~~~~~~~~~~~~~~~~~~~

During a live migration, Ganeti calls the ``up`` script on the
**destination** node once or twice depending on the NIC mode.
The ``MIGRATION_PHASE`` variable (see `Environment Variables`_) tells the
script which call it is in.

``bridged`` / ``ovs``
  The ``up`` script is called **before** the migration starts
  (``MIGRATION_PHASE`` is not set). The TAP is connected to the
  bridge/OVS port immediately so that the instance can continue sending
  and receiving traffic the moment it arrives. This is safe because
  bridged/switched networks forward only to the currently active MAC
  address, so having the port open on both nodes simultaneously causes
  no routing ambiguity.

``routed``
  The ``up`` script is called **after** the migration has completed
  (``MIGRATION_PHASE=post``). This avoids configuring/advertising a
  host route to the instance IP on the destination before the instance
  has actually moved. Because the route only appears after the migration
  finishes, the window of unreachability equals only the final VM
  switchover time plus network convergence rather than the full migration
  duration.

``ext``
  The ``up`` script is called **twice**:

  1. **Before** the migration starts, with ``MIGRATION_PHASE=pre``.
     This call is **non-fatal**: if the script is absent or exits
     non-zero, Ganeti logs a warning and continues.
  2. **After** the migration has completed, with
     ``MIGRATION_PHASE=post``. This call is also non-fatal.

  You only need to provide handling for the phase(s) that matter for
  your setup. The script can inspect ``MIGRATION_PHASE`` and take
  different actions, or ignore it entirely if only one phase is
  relevant and the actions are idempotent.

  .. rubric:: Choosing pre vs post for ext mode

  Use **pre-migration** (act when ``MIGRATION_PHASE=pre``) to prepare
  resources that are safe to have active on both nodes at the same time.
  Examples: reserving a switch port, setting up firewall rules that
  allow traffic to arrive once the VM lands, pre-staging NAT entries.
  Because the TAP device already exists at this point, any host-local
  work that references it (``ip link``, ``tc``, etc.) can be done
  immediately. 

  Use **post-migration** (act when ``MIGRATION_PHASE=post``) for
  anything that must be true on exactly one node at a time.  The
  primary example is **route announcement**: if your ext script
  installs a host route or announces a prefix via e.g. BGP, you must do
  this only after the migration completes (unless you can make sure that
  the route on the destination node never "wins" over the one originated
  from the source node).

  A possible pattern is to perform idempotent setup in ``pre`` (firewall
  rules, port reservations) and route-announcement in ``post``::

    case "$MIGRATION_PHASE" in
      pre)
        # Safe to do on both nodes simultaneously
        setup_firewall_rules "$INTERFACE" "$IP"
        ;;
      post)
        # Must only be active on one node at a time
        announce_bgp_route "$IP"
        ;;
      *)
        # Normal startup (no migration)
        setup_firewall_rules "$INTERFACE" "$IP"
        announce_bgp_route "$IP"
        ;;
    esac


Xen
~~~

The ``up`` script is called by Xen when the domain is created and
its VIF devices are initialised. There is currently no ``down``
callback from Xen.


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
