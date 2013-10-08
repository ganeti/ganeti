Ganeti walk-through
===================

Documents Ganeti version |version|

.. contents::

.. highlight:: shell-example

Introduction
------------

This document serves as a more example-oriented guide to Ganeti; while
the administration guide shows a conceptual approach, here you will find
a step-by-step example to managing instances and the cluster.

Our simulated, example cluster will have three machines, named
``node1``, ``node2``, ``node3``. Note that in real life machines will
usually have FQDNs but here we use short names for brevity. We will use
a secondary network for replication data, ``192.0.2.0/24``, with nodes
having the last octet the same as their index. The cluster name will be
``example-cluster``. All nodes have the same simulated hardware
configuration, two disks of 750GB, 32GB of memory and 4 CPUs.

On this cluster, we will create up to seven instances, named
``instance1`` to ``instance7``.


Cluster creation
----------------

Follow the :doc:`install` document and prepare the nodes. Then it's time
to initialise the cluster::

  $ gnt-cluster init -s %192.0.2.1% --enabled-hypervisors=xen-pvm %example-cluster%
  $

The creation was fine. Let's check that one node we have is functioning
correctly::

  $ gnt-node list
  Node  DTotal DFree MTotal MNode MFree Pinst Sinst
  node1   1.3T  1.3T  32.0G  1.0G 30.5G     0     0
  $ gnt-cluster verify
  Mon Oct 26 02:08:51 2009 * Verifying global settings
  Mon Oct 26 02:08:51 2009 * Gathering data (1 nodes)
  Mon Oct 26 02:08:52 2009 * Verifying node status
  Mon Oct 26 02:08:52 2009 * Verifying instance status
  Mon Oct 26 02:08:52 2009 * Verifying orphan volumes
  Mon Oct 26 02:08:52 2009 * Verifying remaining instances
  Mon Oct 26 02:08:52 2009 * Verifying N+1 Memory redundancy
  Mon Oct 26 02:08:52 2009 * Other Notes
  Mon Oct 26 02:08:52 2009 * Hooks Results
  $

Since this proceeded correctly, let's add the other two nodes::

  $ gnt-node add -s %192.0.2.2% %node2%
  -- WARNING --
  Performing this operation is going to replace the ssh daemon keypair
  on the target machine (node2) with the ones of the current one
  and grant full intra-cluster ssh root access to/from it

  Unable to verify hostkey of host xen-devi-5.fra.corp.google.com:
  f7:…. Do you want to accept it?
  y/[n]/?: %y%
  Mon Oct 26 02:11:53 2009  Authentication to node2 via public key failed, trying password
  root password:
  Mon Oct 26 02:11:54 2009  - INFO: Node will be a master candidate
  $ gnt-node add -s %192.0.2.3% %node3%
  -- WARNING --
  Performing this operation is going to replace the ssh daemon keypair
  on the target machine (node3) with the ones of the current one
  and grant full intra-cluster ssh root access to/from it

  …
  Mon Oct 26 02:12:43 2009  - INFO: Node will be a master candidate

Checking the cluster status again::

  $ gnt-node list
  Node  DTotal DFree MTotal MNode MFree Pinst Sinst
  node1   1.3T  1.3T  32.0G  1.0G 30.5G     0     0
  node2   1.3T  1.3T  32.0G  1.0G 30.5G     0     0
  node3   1.3T  1.3T  32.0G  1.0G 30.5G     0     0
  $ gnt-cluster verify
  Mon Oct 26 02:15:14 2009 * Verifying global settings
  Mon Oct 26 02:15:14 2009 * Gathering data (3 nodes)
  Mon Oct 26 02:15:16 2009 * Verifying node status
  Mon Oct 26 02:15:16 2009 * Verifying instance status
  Mon Oct 26 02:15:16 2009 * Verifying orphan volumes
  Mon Oct 26 02:15:16 2009 * Verifying remaining instances
  Mon Oct 26 02:15:16 2009 * Verifying N+1 Memory redundancy
  Mon Oct 26 02:15:16 2009 * Other Notes
  Mon Oct 26 02:15:16 2009 * Hooks Results
  $

And let's check that we have a valid OS::

  $ gnt-os list
  Name
  debootstrap
  node1#

Running a burn-in
-----------------

Now that the cluster is created, it is time to check that the hardware
works correctly, that the hypervisor can actually create instances,
etc. This is done via the debootstrap tool as described in the admin
guide. Similar output lines are replaced with ``…`` in the below log::

  $ /usr/lib/ganeti/tools/burnin -o debootstrap -p instance{1..5}
  - Testing global parameters
  - Creating instances
    * instance instance1
      on node1, node2
    * instance instance2
      on node2, node3
    …
    * instance instance5
      on node2, node3
    * Submitted job ID(s) 157, 158, 159, 160, 161
      waiting for job 157 for instance1
      …
      waiting for job 161 for instance5
  - Replacing disks on the same nodes
    * instance instance1
      run replace_on_secondary
      run replace_on_primary
    …
    * instance instance5
      run replace_on_secondary
      run replace_on_primary
    * Submitted job ID(s) 162, 163, 164, 165, 166
      waiting for job 162 for instance1
      …
  - Changing the secondary node
    * instance instance1
      run replace_new_secondary node3
    * instance instance2
      run replace_new_secondary node1
    …
    * instance instance5
      run replace_new_secondary node1
    * Submitted job ID(s) 167, 168, 169, 170, 171
      waiting for job 167 for instance1
      …
  - Growing disks
    * instance instance1
      increase disk/0 by 128 MB
    …
    * instance instance5
      increase disk/0 by 128 MB
    * Submitted job ID(s) 173, 174, 175, 176, 177
      waiting for job 173 for instance1
      …
  - Failing over instances
    * instance instance1
    …
    * instance instance5
    * Submitted job ID(s) 179, 180, 181, 182, 183
      waiting for job 179 for instance1
      …
  - Migrating instances
    * instance instance1
      migration and migration cleanup
    …
    * instance instance5
      migration and migration cleanup
    * Submitted job ID(s) 184, 185, 186, 187, 188
      waiting for job 184 for instance1
      …
  - Exporting and re-importing instances
    * instance instance1
      export to node node3
      remove instance
      import from node3 to node1, node2
      remove export
    …
    * instance instance5
      export to node node1
      remove instance
      import from node1 to node2, node3
      remove export
    * Submitted job ID(s) 196, 197, 198, 199, 200
      waiting for job 196 for instance1
      …
  - Reinstalling instances
    * instance instance1
      reinstall without passing the OS
      reinstall specifying the OS
    …
    * instance instance5
      reinstall without passing the OS
      reinstall specifying the OS
    * Submitted job ID(s) 203, 204, 205, 206, 207
      waiting for job 203 for instance1
      …
  - Rebooting instances
    * instance instance1
      reboot with type 'hard'
      reboot with type 'soft'
      reboot with type 'full'
    …
    * instance instance5
      reboot with type 'hard'
      reboot with type 'soft'
      reboot with type 'full'
    * Submitted job ID(s) 208, 209, 210, 211, 212
      waiting for job 208 for instance1
    …
  - Adding and removing disks
    * instance instance1
      adding a disk
      removing last disk
    …
    * instance instance5
      adding a disk
      removing last disk
    * Submitted job ID(s) 213, 214, 215, 216, 217
      waiting for job 213 for instance1
      …
  - Adding and removing NICs
    * instance instance1
      adding a NIC
      removing last NIC
    …
    * instance instance5
      adding a NIC
      removing last NIC
    * Submitted job ID(s) 218, 219, 220, 221, 222
      waiting for job 218 for instance1
      …
  - Activating/deactivating disks
    * instance instance1
      activate disks when online
      activate disks when offline
      deactivate disks (when offline)
    …
    * instance instance5
      activate disks when online
      activate disks when offline
      deactivate disks (when offline)
    * Submitted job ID(s) 223, 224, 225, 226, 227
      waiting for job 223 for instance1
      …
  - Stopping and starting instances
    * instance instance1
    …
    * instance instance5
    * Submitted job ID(s) 230, 231, 232, 233, 234
      waiting for job 230 for instance1
      …
  - Removing instances
    * instance instance1
    …
    * instance instance5
    * Submitted job ID(s) 235, 236, 237, 238, 239
      waiting for job 235 for instance1
      …
  $

You can see in the above what operations the burn-in does. Ideally, the
burn-in log would proceed successfully through all the steps and end
cleanly, without throwing errors.

Instance operations
-------------------

Creation
++++++++

At this point, Ganeti and the hardware seems to be functioning
correctly, so we'll follow up with creating the instances manually::

  $ gnt-instance add -t drbd -o debootstrap -s %256m% %instance1%
  Mon Oct 26 04:06:52 2009  - INFO: Selected nodes for instance instance1 via iallocator hail: node2, node3
  Mon Oct 26 04:06:53 2009 * creating instance disks...
  Mon Oct 26 04:06:57 2009 adding instance instance1 to cluster config
  Mon Oct 26 04:06:57 2009  - INFO: Waiting for instance instance1 to sync disks.
  Mon Oct 26 04:06:57 2009  - INFO: - device disk/0: 20.00\% done, 4 estimated seconds remaining
  Mon Oct 26 04:07:01 2009  - INFO: Instance instance1's disks are in sync.
  Mon Oct 26 04:07:01 2009 creating os for instance instance1 on node node2
  Mon Oct 26 04:07:01 2009 * running the instance OS create scripts...
  Mon Oct 26 04:07:14 2009 * starting instance...
  $ gnt-instance add -t drbd -o debootstrap -s %256m% -n %node1%:%node2% %instance2%
  Mon Oct 26 04:11:37 2009 * creating instance disks...
  Mon Oct 26 04:11:40 2009 adding instance instance2 to cluster config
  Mon Oct 26 04:11:41 2009  - INFO: Waiting for instance instance2 to sync disks.
  Mon Oct 26 04:11:41 2009  - INFO: - device disk/0: 35.40\% done, 1 estimated seconds remaining
  Mon Oct 26 04:11:42 2009  - INFO: - device disk/0: 58.50\% done, 1 estimated seconds remaining
  Mon Oct 26 04:11:43 2009  - INFO: - device disk/0: 86.20\% done, 0 estimated seconds remaining
  Mon Oct 26 04:11:44 2009  - INFO: - device disk/0: 92.40\% done, 0 estimated seconds remaining
  Mon Oct 26 04:11:44 2009  - INFO: - device disk/0: 97.00\% done, 0 estimated seconds remaining
  Mon Oct 26 04:11:44 2009  - INFO: Instance instance2's disks are in sync.
  Mon Oct 26 04:11:44 2009 creating os for instance instance2 on node node1
  Mon Oct 26 04:11:44 2009 * running the instance OS create scripts...
  Mon Oct 26 04:11:57 2009 * starting instance...
  $

The above shows one instance created via an iallocator script, and one
being created with manual node assignment. The other three instances
were also created and now it's time to check them::

  $ gnt-instance list
  Instance  Hypervisor OS          Primary_node Status  Memory
  instance1 xen-pvm    debootstrap node2        running   128M
  instance2 xen-pvm    debootstrap node1        running   128M
  instance3 xen-pvm    debootstrap node1        running   128M
  instance4 xen-pvm    debootstrap node3        running   128M
  instance5 xen-pvm    debootstrap node2        running   128M

Accessing instances
+++++++++++++++++++

Accessing an instance's console is easy::

  $ gnt-instance console %instance2%
  [    0.000000] Bootdata ok (command line is root=/dev/sda1 ro)
  [    0.000000] Linux version 2.6…
  [    0.000000] BIOS-provided physical RAM map:
  [    0.000000]  Xen: 0000000000000000 - 0000000008800000 (usable)
  [13138176.018071] Built 1 zonelists.  Total pages: 34816
  [13138176.018074] Kernel command line: root=/dev/sda1 ro
  [13138176.018694] Initializing CPU#0
  …
  Checking file systems...fsck 1.41.3 (12-Oct-2008)
  done.
  Setting kernel variables (/etc/sysctl.conf)...done.
  Mounting local filesystems...done.
  Activating swapfile swap...done.
  Setting up networking....
  Configuring network interfaces...done.
  Setting console screen modes and fonts.
  INIT: Entering runlevel: 2
  Starting enhanced syslogd: rsyslogd.
  Starting periodic command scheduler: crond.

  Debian GNU/Linux 5.0 instance2 tty1

  instance2 login:

At this moment you can login to the instance and, after configuring the
network (and doing this on all instances), we can check their
connectivity::

  $ fping %instance{1..5}%
  instance1 is alive
  instance2 is alive
  instance3 is alive
  instance4 is alive
  instance5 is alive
  $

Removal
+++++++

Removing unwanted instances is also easy::

  $ gnt-instance remove %instance5%
  This will remove the volumes of the instance instance5 (including
  mirrors), thus removing all the data of the instance. Continue?
  y/[n]/?: %y%
  $


Recovering from hardware failures
---------------------------------

Recovering from node failure
++++++++++++++++++++++++++++

We are now left with four instances. Assume that at this point, node3,
which has one primary and one secondary instance, crashes::

  $ gnt-node info %node3%
  Node name: node3
    primary ip: 198.51.100.1
    secondary ip: 192.0.2.3
    master candidate: True
    drained: False
    offline: False
    primary for instances:
      - instance4
    secondary for instances:
      - instance1
  $ fping %node3%
  node3 is unreachable

At this point, the primary instance of that node (instance4) is down,
but the secondary instance (instance1) is not affected except it has
lost disk redundancy::

  $ fping %instance{1,4}%
  instance1 is alive
  instance4 is unreachable
  $

If we try to check the status of instance4 via the instance info
command, it fails because it tries to contact node3 which is down::

  $ gnt-instance info %instance4%
  Failure: command execution error:
  Error checking node node3: Connection failed (113: No route to host)
  $

So we need to mark node3 as being *offline*, and thus Ganeti won't talk
to it anymore::

  $ gnt-node modify -O yes -f %node3%
  Mon Oct 26 04:34:12 2009  - WARNING: Not enough master candidates (desired 10, new value will be 2)
  Mon Oct 26 04:34:15 2009  - WARNING: Communication failure to node node3: Connection failed (113: No route to host)
  Modified node node3
   - offline -> True
   - master_candidate -> auto-demotion due to offline
  $

And now we can failover the instance::

  $ gnt-instance failover %instance4%
  Failover will happen to image instance4. This requires a shutdown of
  the instance. Continue?
  y/[n]/?: %y%
  Mon Oct 26 04:35:34 2009 * checking disk consistency between source and target
  Failure: command execution error:
  Disk disk/0 is degraded on target node, aborting failover.
  $ gnt-instance failover --ignore-consistency %instance4%
  Failover will happen to image instance4. This requires a shutdown of
  the instance. Continue?
  y/[n]/?: y
  Mon Oct 26 04:35:47 2009 * checking disk consistency between source and target
  Mon Oct 26 04:35:47 2009 * shutting down instance on source node
  Mon Oct 26 04:35:47 2009  - WARNING: Could not shutdown instance instance4 on node node3. Proceeding anyway. Please make sure node node3 is down. Error details: Node is marked offline
  Mon Oct 26 04:35:47 2009 * deactivating the instance's disks on source node
  Mon Oct 26 04:35:47 2009  - WARNING: Could not shutdown block device disk/0 on node node3: Node is marked offline
  Mon Oct 26 04:35:47 2009 * activating the instance's disks on target node
  Mon Oct 26 04:35:47 2009  - WARNING: Could not prepare block device disk/0 on node node3 (is_primary=False, pass=1): Node is marked offline
  Mon Oct 26 04:35:48 2009 * starting the instance on the target node
  $

Note in our first attempt, Ganeti refused to do the failover since it
wasn't sure what is the status of the instance's disks. We pass the
``--ignore-consistency`` flag and then we can failover::

  $ gnt-instance list
  Instance  Hypervisor OS          Primary_node Status  Memory
  instance1 xen-pvm    debootstrap node2        running   128M
  instance2 xen-pvm    debootstrap node1        running   128M
  instance3 xen-pvm    debootstrap node1        running   128M
  instance4 xen-pvm    debootstrap node1        running   128M
  $

But at this point, both instance1 and instance4 are without disk
redundancy::

  $ gnt-instance info %instance1%
  Instance name: instance1
  UUID: 45173e82-d1fa-417c-8758-7d582ab7eef4
  Serial number: 2
  Creation time: 2009-10-26 04:06:57
  Modification time: 2009-10-26 04:07:14
  State: configured to be up, actual state is up
    Nodes:
      - primary: node2
      - secondaries: node3
    Operating system: debootstrap
    Allocated network port: None
    Hypervisor: xen-pvm
      - root_path: default (/dev/sda1)
      - kernel_args: default (ro)
      - use_bootloader: default (False)
      - bootloader_args: default ()
      - bootloader_path: default ()
      - kernel_path: default (/boot/vmlinuz-2.6-xenU)
      - initrd_path: default ()
    Hardware:
      - VCPUs: 1
      - maxmem: 256MiB
      - minmem: 512MiB
      - NICs:
        - nic/0: MAC: aa:00:00:78:da:63, IP: None, mode: bridged, link: xen-br0
    Disks:
      - disk/0: drbd8, size 256M
        access mode: rw
        nodeA:       node2, minor=0
        nodeB:       node3, minor=0
        port:        11035
        auth key:    8e950e3cec6854b0181fbc3a6058657701f2d458
        on primary:  /dev/drbd0 (147:0) in sync, status *DEGRADED*
        child devices:
          - child 0: lvm, size 256M
            logical_id: xenvg/22459cf8-117d-4bea-a1aa-791667d07800.disk0_data
            on primary: /dev/xenvg/22459cf8-117d-4bea-a1aa-791667d07800.disk0_data (254:0)
          - child 1: lvm, size 128M
            logical_id: xenvg/22459cf8-117d-4bea-a1aa-791667d07800.disk0_meta
            on primary: /dev/xenvg/22459cf8-117d-4bea-a1aa-791667d07800.disk0_meta (254:1)

The output is similar for instance4. In order to recover this, we need
to run the node evacuate command which will change from the current
secondary node to a new one (in this case, we only have two working
nodes, so all instances will be end on nodes one and two)::

  $ gnt-node evacuate -I hail %node3%
  Relocate instance(s) 'instance1','instance4' from node
   node3 using iallocator hail?
  y/[n]/?: %y%
  Mon Oct 26 05:05:39 2009  - INFO: Selected new secondary for instance 'instance1': node1
  Mon Oct 26 05:05:40 2009  - INFO: Selected new secondary for instance 'instance4': node2
  Mon Oct 26 05:05:40 2009 Replacing disk(s) 0 for instance1
  Mon Oct 26 05:05:40 2009 STEP 1/6 Check device existence
  Mon Oct 26 05:05:40 2009  - INFO: Checking disk/0 on node2
  Mon Oct 26 05:05:40 2009  - INFO: Checking volume groups
  Mon Oct 26 05:05:40 2009 STEP 2/6 Check peer consistency
  Mon Oct 26 05:05:40 2009  - INFO: Checking disk/0 consistency on node node2
  Mon Oct 26 05:05:40 2009 STEP 3/6 Allocate new storage
  Mon Oct 26 05:05:40 2009  - INFO: Adding new local storage on node1 for disk/0
  Mon Oct 26 05:05:41 2009 STEP 4/6 Changing drbd configuration
  Mon Oct 26 05:05:41 2009  - INFO: activating a new drbd on node1 for disk/0
  Mon Oct 26 05:05:42 2009  - INFO: Shutting down drbd for disk/0 on old node
  Mon Oct 26 05:05:42 2009  - WARNING: Failed to shutdown drbd for disk/0 on oldnode: Node is marked offline
  Mon Oct 26 05:05:42 2009       Hint: Please cleanup this device manually as soon as possible
  Mon Oct 26 05:05:42 2009  - INFO: Detaching primary drbds from the network (=> standalone)
  Mon Oct 26 05:05:42 2009  - INFO: Updating instance configuration
  Mon Oct 26 05:05:45 2009  - INFO: Attaching primary drbds to new secondary (standalone => connected)
  Mon Oct 26 05:05:46 2009 STEP 5/6 Sync devices
  Mon Oct 26 05:05:46 2009  - INFO: Waiting for instance instance1 to sync disks.
  Mon Oct 26 05:05:46 2009  - INFO: - device disk/0: 13.90\% done, 7 estimated seconds remaining
  Mon Oct 26 05:05:53 2009  - INFO: Instance instance1's disks are in sync.
  Mon Oct 26 05:05:53 2009 STEP 6/6 Removing old storage
  Mon Oct 26 05:05:53 2009  - INFO: Remove logical volumes for 0
  Mon Oct 26 05:05:53 2009  - WARNING: Can't remove old LV: Node is marked offline
  Mon Oct 26 05:05:53 2009       Hint: remove unused LVs manually
  Mon Oct 26 05:05:53 2009  - WARNING: Can't remove old LV: Node is marked offline
  Mon Oct 26 05:05:53 2009       Hint: remove unused LVs manually
  Mon Oct 26 05:05:53 2009 Replacing disk(s) 0 for instance4
  Mon Oct 26 05:05:53 2009 STEP 1/6 Check device existence
  Mon Oct 26 05:05:53 2009  - INFO: Checking disk/0 on node1
  Mon Oct 26 05:05:53 2009  - INFO: Checking volume groups
  Mon Oct 26 05:05:53 2009 STEP 2/6 Check peer consistency
  Mon Oct 26 05:05:53 2009  - INFO: Checking disk/0 consistency on node node1
  Mon Oct 26 05:05:54 2009 STEP 3/6 Allocate new storage
  Mon Oct 26 05:05:54 2009  - INFO: Adding new local storage on node2 for disk/0
  Mon Oct 26 05:05:54 2009 STEP 4/6 Changing drbd configuration
  Mon Oct 26 05:05:54 2009  - INFO: activating a new drbd on node2 for disk/0
  Mon Oct 26 05:05:55 2009  - INFO: Shutting down drbd for disk/0 on old node
  Mon Oct 26 05:05:55 2009  - WARNING: Failed to shutdown drbd for disk/0 on oldnode: Node is marked offline
  Mon Oct 26 05:05:55 2009       Hint: Please cleanup this device manually as soon as possible
  Mon Oct 26 05:05:55 2009  - INFO: Detaching primary drbds from the network (=> standalone)
  Mon Oct 26 05:05:55 2009  - INFO: Updating instance configuration
  Mon Oct 26 05:05:55 2009  - INFO: Attaching primary drbds to new secondary (standalone => connected)
  Mon Oct 26 05:05:56 2009 STEP 5/6 Sync devices
  Mon Oct 26 05:05:56 2009  - INFO: Waiting for instance instance4 to sync disks.
  Mon Oct 26 05:05:56 2009  - INFO: - device disk/0: 12.40\% done, 8 estimated seconds remaining
  Mon Oct 26 05:06:04 2009  - INFO: Instance instance4's disks are in sync.
  Mon Oct 26 05:06:04 2009 STEP 6/6 Removing old storage
  Mon Oct 26 05:06:04 2009  - INFO: Remove logical volumes for 0
  Mon Oct 26 05:06:04 2009  - WARNING: Can't remove old LV: Node is marked offline
  Mon Oct 26 05:06:04 2009       Hint: remove unused LVs manually
  Mon Oct 26 05:06:04 2009  - WARNING: Can't remove old LV: Node is marked offline
  Mon Oct 26 05:06:04 2009       Hint: remove unused LVs manually
  $

And now node3 is completely free of instances and can be repaired::

  $ gnt-node list
  Node  DTotal DFree MTotal MNode MFree Pinst Sinst
  node1   1.3T  1.3T  32.0G  1.0G 30.2G     3     1
  node2   1.3T  1.3T  32.0G  1.0G 30.4G     1     3
  node3      ?     ?      ?     ?     ?     0     0

Re-adding a node to the cluster
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Let's say node3 has been repaired and is now ready to be
reused. Re-adding it is simple::

  $ gnt-node add --readd %node3%
  The authenticity of host 'node3 (198.51.100.1)' can't be established.
  RSA key fingerprint is 9f:2e:5a:2e:e0:bd:00:09:e4:5c:32:f2:27:57:7a:f4.
  Are you sure you want to continue connecting (yes/no)? yes
  Mon Oct 26 05:27:39 2009  - INFO: Readding a node, the offline/drained flags were reset
  Mon Oct 26 05:27:39 2009  - INFO: Node will be a master candidate

And it is now working again::

  $ gnt-node list
  Node  DTotal DFree MTotal MNode MFree Pinst Sinst
  node1   1.3T  1.3T  32.0G  1.0G 30.2G     3     1
  node2   1.3T  1.3T  32.0G  1.0G 30.4G     1     3
  node3   1.3T  1.3T  32.0G  1.0G 30.4G     0     0

.. note:: If Ganeti has been built with the htools
   component enabled, you can shuffle the instances around to have a
   better use of the nodes.

Disk failures
+++++++++++++

A disk failure is simpler than a full node failure. First, a single disk
failure should not cause data-loss for any redundant instance; only the
performance of some instances might be reduced due to more network
traffic.

Let take the cluster status in the above listing, and check what volumes
are in use::

  $ gnt-node volumes -o phys,instance %node2%
  PhysDev   Instance
  /dev/sdb1 instance4
  /dev/sdb1 instance4
  /dev/sdb1 instance1
  /dev/sdb1 instance1
  /dev/sdb1 instance3
  /dev/sdb1 instance3
  /dev/sdb1 instance2
  /dev/sdb1 instance2
  $

You can see that all instances on node2 have logical volumes on
``/dev/sdb1``. Let's simulate a disk failure on that disk::

  $ ssh node2
  # on node2
  $ echo offline > /sys/block/sdb/device/state
  $ vgs
    /dev/sdb1: read failed after 0 of 4096 at 0: Input/output error
    /dev/sdb1: read failed after 0 of 4096 at 750153695232: Input/output error
    /dev/sdb1: read failed after 0 of 4096 at 0: Input/output error
    Couldn't find device with uuid '954bJA-mNL0-7ydj-sdpW-nc2C-ZrCi-zFp91c'.
    Couldn't find all physical volumes for volume group xenvg.
    /dev/sdb1: read failed after 0 of 4096 at 0: Input/output error
    /dev/sdb1: read failed after 0 of 4096 at 0: Input/output error
    Couldn't find device with uuid '954bJA-mNL0-7ydj-sdpW-nc2C-ZrCi-zFp91c'.
    Couldn't find all physical volumes for volume group xenvg.
    Volume group xenvg not found
  $

At this point, the node is broken and if we are to examine
instance2 we get (simplified output shown)::

  $ gnt-instance info %instance2%
  Instance name: instance2
  State: configured to be up, actual state is up
    Nodes:
      - primary: node1
      - secondaries: node2
    Disks:
      - disk/0: drbd8, size 256M
        on primary:   /dev/drbd0 (147:0) in sync, status ok
        on secondary: /dev/drbd1 (147:1) in sync, status *DEGRADED* *MISSING DISK*

This instance has a secondary only on node2. Let's verify a primary
instance of node2::

  $ gnt-instance info %instance1%
  Instance name: instance1
  State: configured to be up, actual state is up
    Nodes:
      - primary: node2
      - secondaries: node1
    Disks:
      - disk/0: drbd8, size 256M
        on primary:   /dev/drbd0 (147:0) in sync, status *DEGRADED* *MISSING DISK*
        on secondary: /dev/drbd3 (147:3) in sync, status ok
  $ gnt-instance console %instance1%

  Debian GNU/Linux 5.0 instance1 tty1

  instance1 login: root
  Last login: Tue Oct 27 01:24:09 UTC 2009 on tty1
  instance1:~# date > test
  instance1:~# sync
  instance1:~# cat test
  Tue Oct 27 01:25:20 UTC 2009
  instance1:~# dmesg|tail
  [5439785.235448] NET: Registered protocol family 15
  [5439785.235489] 802.1Q VLAN Support v1.8 Ben Greear <greearb@candelatech.com>
  [5439785.235495] All bugs added by David S. Miller <davem@redhat.com>
  [5439785.235517] XENBUS: Device with no driver: device/console/0
  [5439785.236576] kjournald starting.  Commit interval 5 seconds
  [5439785.236588] EXT3-fs: mounted filesystem with ordered data mode.
  [5439785.236625] VFS: Mounted root (ext3 filesystem) readonly.
  [5439785.236663] Freeing unused kernel memory: 172k freed
  [5439787.533779] EXT3 FS on sda1, internal journal
  [5440655.065431] eth0: no IPv6 routers present
  instance1:~#

As you can see, the instance is running fine and doesn't see any disk
issues. It is now time to fix node2 and re-establish redundancy for the
involved instances.

.. note:: For Ganeti 2.0 we need to fix manually the volume group on
   node2 by running ``vgreduce --removemissing xenvg``

::

  $ gnt-node repair-storage %node2% lvm-vg %xenvg%
  Mon Oct 26 18:14:03 2009 Repairing storage unit 'xenvg' on node2 ...
  $ ssh %node2% vgs
  VG    #PV #LV #SN Attr   VSize   VFree
  xenvg   1   8   0 wz--n- 673.84G 673.84G
  $

This has removed the 'bad' disk from the volume group, which is now left
with only one PV. We can now replace the disks for the involved
instances::

  $ for i in %instance{1..4}%; do gnt-instance replace-disks -a $i; done
  Mon Oct 26 18:15:38 2009 Replacing disk(s) 0 for instance1
  Mon Oct 26 18:15:38 2009 STEP 1/6 Check device existence
  Mon Oct 26 18:15:38 2009  - INFO: Checking disk/0 on node1
  Mon Oct 26 18:15:38 2009  - INFO: Checking disk/0 on node2
  Mon Oct 26 18:15:38 2009  - INFO: Checking volume groups
  Mon Oct 26 18:15:38 2009 STEP 2/6 Check peer consistency
  Mon Oct 26 18:15:38 2009  - INFO: Checking disk/0 consistency on node node1
  Mon Oct 26 18:15:39 2009 STEP 3/6 Allocate new storage
  Mon Oct 26 18:15:39 2009  - INFO: Adding storage on node2 for disk/0
  Mon Oct 26 18:15:39 2009 STEP 4/6 Changing drbd configuration
  Mon Oct 26 18:15:39 2009  - INFO: Detaching disk/0 drbd from local storage
  Mon Oct 26 18:15:40 2009  - INFO: Renaming the old LVs on the target node
  Mon Oct 26 18:15:40 2009  - INFO: Renaming the new LVs on the target node
  Mon Oct 26 18:15:40 2009  - INFO: Adding new mirror component on node2
  Mon Oct 26 18:15:41 2009 STEP 5/6 Sync devices
  Mon Oct 26 18:15:41 2009  - INFO: Waiting for instance instance1 to sync disks.
  Mon Oct 26 18:15:41 2009  - INFO: - device disk/0: 12.40\% done, 9 estimated seconds remaining
  Mon Oct 26 18:15:50 2009  - INFO: Instance instance1's disks are in sync.
  Mon Oct 26 18:15:50 2009 STEP 6/6 Removing old storage
  Mon Oct 26 18:15:50 2009  - INFO: Remove logical volumes for disk/0
  Mon Oct 26 18:15:52 2009 Replacing disk(s) 0 for instance2
  Mon Oct 26 18:15:52 2009 STEP 1/6 Check device existence
  …
  Mon Oct 26 18:16:01 2009 STEP 6/6 Removing old storage
  Mon Oct 26 18:16:01 2009  - INFO: Remove logical volumes for disk/0
  Mon Oct 26 18:16:02 2009 Replacing disk(s) 0 for instance3
  Mon Oct 26 18:16:02 2009 STEP 1/6 Check device existence
  …
  Mon Oct 26 18:16:09 2009 STEP 6/6 Removing old storage
  Mon Oct 26 18:16:09 2009  - INFO: Remove logical volumes for disk/0
  Mon Oct 26 18:16:10 2009 Replacing disk(s) 0 for instance4
  Mon Oct 26 18:16:10 2009 STEP 1/6 Check device existence
  …
  Mon Oct 26 18:16:18 2009 STEP 6/6 Removing old storage
  Mon Oct 26 18:16:18 2009  - INFO: Remove logical volumes for disk/0
  $

As this point, all instances should be healthy again.

.. note:: Ganeti 2.0 doesn't have the ``-a`` option to replace-disks, so
   for it you have to run the loop twice, once over primary instances
   with argument ``-p`` and once secondary instances with argument
   ``-s``, but otherwise the operations are similar::

     $ gnt-instance replace-disks -p instance1
     …
     $ for i in %instance{2..4}%; do gnt-instance replace-disks -s $i; done

Common cluster problems
-----------------------

There are a number of small issues that might appear on a cluster that
can be solved easily as long as the issue is properly identified. For
this exercise we will consider the case of node3, which was broken
previously and re-added to the cluster without reinstallation. Running
cluster verify on the cluster reports::

  $ gnt-cluster verify
  Mon Oct 26 18:30:08 2009 * Verifying global settings
  Mon Oct 26 18:30:08 2009 * Gathering data (3 nodes)
  Mon Oct 26 18:30:10 2009 * Verifying node status
  Mon Oct 26 18:30:10 2009   - ERROR: node node3: unallocated drbd minor 0 is in use
  Mon Oct 26 18:30:10 2009   - ERROR: node node3: unallocated drbd minor 1 is in use
  Mon Oct 26 18:30:10 2009 * Verifying instance status
  Mon Oct 26 18:30:10 2009   - ERROR: instance instance4: instance should not run on node node3
  Mon Oct 26 18:30:10 2009 * Verifying orphan volumes
  Mon Oct 26 18:30:10 2009   - ERROR: node node3: volume 22459cf8-117d-4bea-a1aa-791667d07800.disk0_data is unknown
  Mon Oct 26 18:30:10 2009   - ERROR: node node3: volume 1aaf4716-e57f-4101-a8d6-03af5da9dc50.disk0_data is unknown
  Mon Oct 26 18:30:10 2009   - ERROR: node node3: volume 1aaf4716-e57f-4101-a8d6-03af5da9dc50.disk0_meta is unknown
  Mon Oct 26 18:30:10 2009   - ERROR: node node3: volume 22459cf8-117d-4bea-a1aa-791667d07800.disk0_meta is unknown
  Mon Oct 26 18:30:10 2009 * Verifying remaining instances
  Mon Oct 26 18:30:10 2009 * Verifying N+1 Memory redundancy
  Mon Oct 26 18:30:10 2009 * Other Notes
  Mon Oct 26 18:30:10 2009 * Hooks Results
  $

Instance status
+++++++++++++++

As you can see, *instance4* has a copy running on node3, because we
forced the failover when node3 failed. This case is dangerous as the
instance will have the same IP and MAC address, wreaking havoc on the
network environment and anyone who tries to use it.

Ganeti doesn't directly handle this case. It is recommended to logon to
node3 and run::

  $ xm destroy %instance4%

Unallocated DRBD minors
+++++++++++++++++++++++

There are still unallocated DRBD minors on node3. Again, these are not
handled by Ganeti directly and need to be cleaned up via DRBD commands::

  $ ssh %node3%
  # on node 3
  $ drbdsetup /dev/drbd%0% down
  $ drbdsetup /dev/drbd%1% down
  $

Orphan volumes
++++++++++++++

At this point, the only remaining problem should be the so-called
*orphan* volumes. This can happen also in the case of an aborted
disk-replace, or similar situation where Ganeti was not able to recover
automatically. Here you need to remove them manually via LVM commands::

  $ ssh %node3%
  # on node3
  $ lvremove %xenvg%
  Do you really want to remove active logical volume "22459cf8-117d-4bea-a1aa-791667d07800.disk0_data"? [y/n]: %y%
    Logical volume "22459cf8-117d-4bea-a1aa-791667d07800.disk0_data" successfully removed
  Do you really want to remove active logical volume "22459cf8-117d-4bea-a1aa-791667d07800.disk0_meta"? [y/n]: %y%
    Logical volume "22459cf8-117d-4bea-a1aa-791667d07800.disk0_meta" successfully removed
  Do you really want to remove active logical volume "1aaf4716-e57f-4101-a8d6-03af5da9dc50.disk0_data"? [y/n]: %y%
    Logical volume "1aaf4716-e57f-4101-a8d6-03af5da9dc50.disk0_data" successfully removed
  Do you really want to remove active logical volume "1aaf4716-e57f-4101-a8d6-03af5da9dc50.disk0_meta"? [y/n]: %y%
    Logical volume "1aaf4716-e57f-4101-a8d6-03af5da9dc50.disk0_meta" successfully removed
  node3#

At this point cluster verify shouldn't complain anymore::

  $ gnt-cluster verify
  Mon Oct 26 18:37:51 2009 * Verifying global settings
  Mon Oct 26 18:37:51 2009 * Gathering data (3 nodes)
  Mon Oct 26 18:37:53 2009 * Verifying node status
  Mon Oct 26 18:37:53 2009 * Verifying instance status
  Mon Oct 26 18:37:53 2009 * Verifying orphan volumes
  Mon Oct 26 18:37:53 2009 * Verifying remaining instances
  Mon Oct 26 18:37:53 2009 * Verifying N+1 Memory redundancy
  Mon Oct 26 18:37:53 2009 * Other Notes
  Mon Oct 26 18:37:53 2009 * Hooks Results
  $

N+1 errors
++++++++++

Since redundant instances in Ganeti have a primary/secondary model, it
is needed to leave aside on each node enough memory so that if one of
its peer node fails, all the secondary instances that have that node as
primary can be relocated. More specifically, if instance2 has node1 as
primary and node2 as secondary (and node1 and node2 do not have any
other instances in this layout), then it means that node2 must have
enough free memory so that if node1 fails, we can failover instance2
without any other operations (for reducing the downtime window). Let's
increase the memory of the current instances to 4G, and add three new
instances, two on node2:node3 with 8GB of RAM and one on node1:node2,
with 12GB of RAM (numbers chosen so that we run out of memory)::

  $ gnt-instance modify -B memory=%4G% %instance1%
  Modified instance instance1
   - be/maxmem -> 4096
   - be/minmem -> 4096
  Please don't forget that these parameters take effect only at the next start of the instance.
  $ gnt-instance modify …

  $ gnt-instance add -t drbd -n %node2%:%node3% -s %512m% -B memory=%8G% -o %debootstrap% %instance5%
  …
  $ gnt-instance add -t drbd -n %node2%:%node3% -s %512m% -B memory=%8G% -o %debootstrap% %instance6%
  …
  $ gnt-instance add -t drbd -n %node1%:%node2% -s %512m% -B memory=%8G% -o %debootstrap% %instance7%
  $ gnt-instance reboot --all
  The reboot will operate on 7 instances.
  Do you want to continue?
  Affected instances:
    instance1
    instance2
    instance3
    instance4
    instance5
    instance6
    instance7
  y/[n]/?: %y%
  Submitted jobs 677, 678, 679, 680, 681, 682, 683
  Waiting for job 677 for instance1...
  Waiting for job 678 for instance2...
  Waiting for job 679 for instance3...
  Waiting for job 680 for instance4...
  Waiting for job 681 for instance5...
  Waiting for job 682 for instance6...
  Waiting for job 683 for instance7...
  $

We rebooted the instances for the memory changes to have effect. Now the
cluster looks like::

  $ gnt-node list
  Node  DTotal DFree MTotal MNode MFree Pinst Sinst
  node1   1.3T  1.3T  32.0G  1.0G  6.5G     4     1
  node2   1.3T  1.3T  32.0G  1.0G 10.5G     3     4
  node3   1.3T  1.3T  32.0G  1.0G 30.5G     0     2
  $ gnt-cluster verify
  Mon Oct 26 18:59:36 2009 * Verifying global settings
  Mon Oct 26 18:59:36 2009 * Gathering data (3 nodes)
  Mon Oct 26 18:59:37 2009 * Verifying node status
  Mon Oct 26 18:59:37 2009 * Verifying instance status
  Mon Oct 26 18:59:37 2009 * Verifying orphan volumes
  Mon Oct 26 18:59:37 2009 * Verifying remaining instances
  Mon Oct 26 18:59:37 2009 * Verifying N+1 Memory redundancy
  Mon Oct 26 18:59:37 2009   - ERROR: node node2: not enough memory to accommodate instance failovers should node node1 fail
  Mon Oct 26 18:59:37 2009 * Other Notes
  Mon Oct 26 18:59:37 2009 * Hooks Results
  $

The cluster verify error above shows that if node1 fails, node2 will not
have enough memory to failover all primary instances on node1 to it. To
solve this, you have a number of options:

- try to manually move instances around (but this can become complicated
  for any non-trivial cluster)
- try to reduce the minimum memory of some instances on the source node
  of the N+1 failure (in the example above ``node1``): this will allow
  it to start and be failed over/migrated with less than its maximum
  memory
- try to reduce the runtime/maximum memory of some instances on the
  destination node of the N+1 failure (in the example above ``node2``)
  to create additional available node memory (check the :doc:`admin`
  guide for what Ganeti will and won't automatically do in regards to
  instance runtime memory modification)
- if Ganeti has been built with the htools package enabled, you can run
  the ``hbal`` tool which will try to compute an automated cluster
  solution that complies with the N+1 rule

Network issues
++++++++++++++

In case a node has problems with the network (usually the secondary
network, as problems with the primary network will render the node
unusable for ganeti commands), it will show up in cluster verify as::

  $ gnt-cluster verify
  Mon Oct 26 19:07:19 2009 * Verifying global settings
  Mon Oct 26 19:07:19 2009 * Gathering data (3 nodes)
  Mon Oct 26 19:07:23 2009 * Verifying node status
  Mon Oct 26 19:07:23 2009   - ERROR: node node1: tcp communication with node 'node3': failure using the secondary interface(s)
  Mon Oct 26 19:07:23 2009   - ERROR: node node2: tcp communication with node 'node3': failure using the secondary interface(s)
  Mon Oct 26 19:07:23 2009   - ERROR: node node3: tcp communication with node 'node1': failure using the secondary interface(s)
  Mon Oct 26 19:07:23 2009   - ERROR: node node3: tcp communication with node 'node2': failure using the secondary interface(s)
  Mon Oct 26 19:07:23 2009   - ERROR: node node3: tcp communication with node 'node3': failure using the secondary interface(s)
  Mon Oct 26 19:07:23 2009 * Verifying instance status
  Mon Oct 26 19:07:23 2009 * Verifying orphan volumes
  Mon Oct 26 19:07:23 2009 * Verifying remaining instances
  Mon Oct 26 19:07:23 2009 * Verifying N+1 Memory redundancy
  Mon Oct 26 19:07:23 2009 * Other Notes
  Mon Oct 26 19:07:23 2009 * Hooks Results
  $

This shows that both node1 and node2 have problems contacting node3 over
the secondary network, and node3 has problems contacting them. From this
output is can be deduced that since node1 and node2 can communicate
between themselves, node3 is the one having problems, and you need to
investigate its network settings/connection.

Migration problems
++++++++++++++++++

Since live migration can sometimes fail and leave the instance in an
inconsistent state, Ganeti provides a ``--cleanup`` argument to the
migrate command that does:

- check on which node the instance is actually running (has the
  command failed before or after the actual migration?)
- reconfigure the DRBD disks accordingly

It is always safe to run this command as long as the instance has good
data on its primary node (i.e. not showing as degraded). If so, you can
simply run::

  $ gnt-instance migrate --cleanup %instance1%
  Instance instance1 will be recovered from a failed migration. Note
  that the migration procedure (including cleanup) is **experimental**
  in this version. This might impact the instance if anything goes
  wrong. Continue?
  y/[n]/?: %y%
  Mon Oct 26 19:13:49 2009 Migrating instance instance1
  Mon Oct 26 19:13:49 2009 * checking where the instance actually runs (if this hangs, the hypervisor might be in a bad state)
  Mon Oct 26 19:13:49 2009 * instance confirmed to be running on its primary node (node2)
  Mon Oct 26 19:13:49 2009 * switching node node1 to secondary mode
  Mon Oct 26 19:13:50 2009 * wait until resync is done
  Mon Oct 26 19:13:50 2009 * changing into standalone mode
  Mon Oct 26 19:13:50 2009 * changing disks into single-master mode
  Mon Oct 26 19:13:50 2009 * wait until resync is done
  Mon Oct 26 19:13:51 2009 * done
  $

In use disks at instance shutdown
+++++++++++++++++++++++++++++++++

If you see something like the following when trying to shutdown or
deactivate disks for an instance::

  $ gnt-instance shutdown %instance1%
  Mon Oct 26 19:16:23 2009  - WARNING: Could not shutdown block device disk/0 on node node2: drbd0: can't shutdown drbd device: /dev/drbd0: State change failed: (-12) Device is held open by someone\n

It most likely means something is holding open the underlying DRBD
device. This can be bad if the instance is not running, as it might mean
that there was concurrent access from both the node and the instance to
the disks, but not always (e.g. you could only have had the partitions
activated via ``kpartx``).

To troubleshoot this issue you need to follow standard Linux practices,
and pay attention to the hypervisor being used:

- check if (in the above example) ``/dev/drbd0`` on node2 is being
  mounted somewhere (``cat /proc/mounts``)
- check if the device is not being used by device mapper itself:
  ``dmsetup ls`` and look for entries of the form ``drbd0pX``, and if so
  remove them with either ``kpartx -d`` or ``dmsetup remove``

For Xen, check if it's not using the disks itself::

  $ xenstore-ls /local/domain/%0%/backend/vbd|grep -e "domain =" -e physical-device
  domain = "instance2"
  physical-device = "93:0"
  domain = "instance3"
  physical-device = "93:1"
  domain = "instance4"
  physical-device = "93:2"
  $

You can see in the above output that the node exports three disks, to
three instances. The ``physical-device`` key is in major:minor format in
hexadecimal, and ``0x93`` represents DRBD's major number. Thus we can
see from the above that instance2 has /dev/drbd0, instance3 /dev/drbd1,
and instance4 /dev/drbd2.

LUXI version mismatch
+++++++++++++++++++++

LUXI is the protocol used for communication between clients and the
master daemon. Starting in Ganeti 2.3, the peers exchange their version
in each message. When they don't match, an error is raised::

  $ gnt-node modify -O yes %node3%
  Unhandled Ganeti error: LUXI version mismatch, server 2020000, request 2030000

Usually this means that server and client are from different Ganeti
versions or import their libraries from different, consistent paths
(e.g. an older version installed in another place). You can print the
import path for Ganeti's modules using the following command (note that
depending on your setup you might have to use an explicit version in the
Python command, e.g. ``python2.6``)::

  python -c 'import ganeti; print ganeti.__file__'

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
