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
1. Implement functions into gnt-network to manage Open vSwitch through Ganeti gnt-network 
   should be able to create, modify and delete vSwitches. The resulting configuration shall 
   automatically be done on all members of the node group. Connecting Ethernet devices to
   vSwitches should be managed through this interface as well.

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

Configuration changes
+++++++++++++++++++++
Instances shall be extended with configuration options for

- VLAN-ID
- port type (access port, trunk, hybrid)
- maximum bandwidth
- maximum burst rate

New configuration objects need to be created for the Open vSwitch configuration.

All these configuration changes need to be made available on the whole node group.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
