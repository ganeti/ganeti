========================
Support for Open vSwitch
========================

.. contents:: :depth: 3

This is a design document detailing the implementation of support for
Open vSwitch in the Ganeti tool chain.

Current state and shortcomings
==============================

At the moment Ganeti's support for Open vSwitch is very basic and
limited to connecting instances to an existing vSwitch.

The shortcomings of this approach are:

1. The full functionality (VLANs, QoS and trunking) of Open vSwitch is not used.

2. Open vSwitch cannot be managed centrally.

Proposed changes
----------------
1. Implement functions into gnt-cluster and gnt-node to manage Open vSwitch through Ganeti.
   It should be possible to create, modify and delete vSwitches. The resulting configuration
   shall automatically be done on all members of the node group, if possible. Connecting Ethernet 
   devices to vSwitches should be managed through this interface as well.

2. Implement VLAN-capabilities: Instances shall have additional information for every NIC: VLAN-ID
   and port type. These are used to determine their type of connection to Open vSwitch. This will
   require modifying the methods for instance creation and modification

3. Implement NIC bonding: Functions to bond NICs for performance improvement, load-balancing and
   failover should be added. It is preferable to have a configuration option to determine the
   type of the trunk, as there are different types of trunks (LACP dynamic and static, different
   failover and load-balancing mechanisms)

4. Set QoS level on per instance basis: Instances shall have an additional information: maximum
   bandwidth and maximum burst. This helps to balance the bandwidth needs between the VMs and to
   ensure fair sharing of the bandwidth.

Automatic configuration of OpenvSwitches
++++++++++++++++++++++++++++++++++++++++
Ideally, the OpenvSwitch configuration should be done automatically.

This needs to be done on node level, since each node can be individual and a setting on cluster / node group
level would be too global is thus not wanted. 

The task that each node needs to do is:
  ``ovs-vsctl addbr <switchname>`` with <switchname> defaulting to constants.DEFAULT_OVS
  ``ovs-vsctl add-port <switchname> <ethernet device>`` optional: connection to the outside

This will give us 2 parameters, that are needed for the OpenvSwitch Setup:
  switchname: Which will default to constants.DEFAULT_OVS when not given
  ethernet device: Which will default to None when not given, might be more than one (NIC bonding)

These parameters should be set at node level for individuality, _but_ can have defined defaults on cluster
and node group level, which can be inherited and thus allow a cluster or node group wide configuration.
If a node is setup without parameters, it should use the settings from the parent node group or cluster. If none
are given there, defaults should be used.

As a first step, this will be implemented for using 1 ethernet device only. Functions for nic bonding will be added
later on.

Configuration changes for VLANs
+++++++++++++++++++++++++++++++
nicparams shall be extended by a value "vlan" that will store the VLAN information for each NIC.
This parameter will only be used if nicparams[constants.NIC_MODE] == constants.NIC_MODE_OVS,
since it doesn't make sense in other modes.

Each VLAN the NIC belongs to shall be stored in this single value. The format of storing this information
is the same as the one which is used in Xen 4.3, since Xen 4.3 comes with functionality to support
OpenvSwitch.

This parameter will, at first, only be implemented for Xen and will have no effects on other hypervisors.
Support for KVM will be added in the future.

Example:
switch1 will connect the VM to the default VLAN of the switch1.
switch1.3 means that the VM is connected to an access port of VLAN 3.
switch1.2:10:20 means that the VM is connected to a hybrid port on switch1, carrying VLANs 2 untagged and 
VLANs 10 and 20 tagged.
switch1:44:55 means that the VM is connected to a trunk port on switch1, carrying VLANS 44 and 55

This configuration string is split at the dot or colon respectively and stored in nicparams[constants.NIC_LINK] 
and nicparams[constants.NIC_VLAN] respectively. Dot or colon are stored as well in nicparams[constants.NIC_VLAN].

For Xen hypervisors, this information can be concatenated again and stored in the vif config as
the bridge parameter and will be fully compatible with vif-openvswitch as of Xen 4.3.

Users of older Xen versions should be able to grab vif-openvswitch from the Xen repo and use it
(tested in 4.2).

gnt-instance modify shall be able to add or remove single VLANs from the vlan string without users needing
to specify the complete new string.

NIC bonding
+++++++++++
To be done

Configuration changes for QoS
+++++++++++++++++++++++++++++
Instances shall be extended with configuration options for

- maximum bandwidth
- maximum burst rate

New configuration objects need to be created for the Open vSwitch configuration.

All these configuration changes need to be made available on the whole node group.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
