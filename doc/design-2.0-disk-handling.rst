Ganeti 2.0 disk handling changes
================================

Objective
---------

Change the storage options available and the details of the
implementation such that we overcome some design limitations present
in Ganeti 1.x.

Background
----------

The storage options available in Ganeti 1.x were introduced based on
then-current software (DRBD 0.7 and later DRBD 8) and the estimated
usage patters. However, experience has later shown that some
assumptions made initially are not true and that more flexibility is
needed.

One main assupmtion made was that disk failures should be treated as 'rare'
events, and that each of them needs to be manually handled in order to ensure
data safety; however, both these assumptions are false:

- disk failures can be a common occurence, based on usage patterns or cluster
  size
- our disk setup is robust enough (referring to DRBD8 + LVM) that we could
  automate more of the recovery

Note that we still don't have fully-automated disk recovery as a goal, but our
goal is to reduce the manual work needed.

Overview
--------

We plan the following main changes:

- DRBD8 is much more flexible and stable than its previous version (0.7),
  such that removing the support for the ``remote_raid1`` template and
  focusing only on DRBD8 is easier

- dynamic discovery of DRBD devices is not actually needed in a cluster that
  where the DRBD namespace is controlled by Ganeti; switching to a static
  assignment (done at either instance creation time or change secondary time)
  will change the disk activation time from O(n) to O(1), which on big
  clusters is a significant gain

- remove the hard dependency on LVM (currently all available storage types are
  ultimately backed by LVM volumes) by introducing file-based storage

Additionally, a number of smaller enhancements are also planned:
- support variable number of disks
- support read-only disks

Future enhancements in the 2.x series, which do not require base design
changes, might include:

- enhancement of the LVM allocation method in order to try to keep
  all of an instance's virtual disks on the same physical
  disks

- add support for DRBD8 authentication at handshake time in
  order to ensure each device connects to the correct peer

- remove the restrictions on failover only to the secondary
  which creates very strict rules on cluster allocation

Detailed Design
---------------

DRBD minor allocation
~~~~~~~~~~~~~~~~~~~~~

Currently, when trying to identify or activate a new DRBD (or MD)
device, the code scans all in-use devices in order to see if we find
one that looks similar to our parameters and is already in the desired
state or not. Since this needs external commands to be run, it is very
slow when more than a few devices are already present.

Therefore, we will change the discovery model from dynamic to
static. When a new device is logically created (added to the
configuration) a free minor number is computed from the list of
devices that should exist on that node and assigned to that
device.

At device activation, if the minor is already in use, we check if
it has our parameters; if not so, we just destroy the device (if
possible, otherwise we abort) and start it with our own
parameters.

This means that we in effect take ownership of the minor space for
that device type; if there's a user-created drbd minor, it will be
automatically removed.

The change will have the effect of reducing the number of external
commands run per device from a constant number times the index of the
first free DRBD minor to just a constant number.

Removal of obsolete device types (md, drbd7)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

We need to remove these device types because of two issues. First,
drbd7 has bad failure modes in case of dual failures (both network and
disk - it cannot propagate the error up the device stack and instead
just panics. Second, due to the assymetry between primary and
secondary in md+drbd mode, we cannot do live failover (not even if we
had md+drbd8).

File-based storage support
~~~~~~~~~~~~~~~~~~~~~~~~~~

This is covered by a separate design doc (<em>Vinales</em>) and
would allow us to get rid of the hard requirement for testing
clusters; it would also allow people who have SAN storage to do live
failover taking advantage of their storage solution.

Variable number of disks
~~~~~~~~~~~~~~~~~~~~~~~~

In order to support high-security scenarios (for example read-only sda
and read-write sdb), we need to make a fully flexibly disk
definition. This has less impact that it might look at first sight:
only the instance creation has hardcoded number of disks, not the disk
handling code. The block device handling and most of the instance
handling code is already working with "the instance's disks" as
opposed to "the two disks of the instance", but some pieces are not
(e.g. import/export) and the code needs a review to ensure safety.

The objective is to be able to specify the number of disks at
instance creation, and to be able to toggle from read-only to
read-write a disk afterwards.

Better LVM allocation
~~~~~~~~~~~~~~~~~~~~~

Currently, the LV to PV allocation mechanism is a very simple one: at
each new request for a logical volume, tell LVM to allocate the volume
in order based on the amount of free space. This is good for
simplicity and for keeping the usage equally spread over the available
physical disks, however it introduces a problem that an instance could
end up with its (currently) two drives on two physical disks, or
(worse) that the data and metadata for a DRBD device end up on
different drives.

This is bad because it causes unneeded ``replace-disks`` operations in
case of a physical failure.

The solution is to batch allocations for an instance and make the LVM
handling code try to allocate as close as possible all the storage of
one instance. We will still allow the logical volumes to spill over to
additional disks as needed.

Note that this clustered allocation can only be attempted at initial
instance creation, or at change secondary node time. At add disk time,
or at replacing individual disks, it's not easy enough to compute the
current disk map so we'll not attempt the clustering.

DRBD8 peer authentication at handshake
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

DRBD8 has a new feature that allow authentication of the peer at
connect time. We can use this to prevent connecting to the wrong peer
more that securing the connection. Even though we never had issues
with wrong connections, it would be good to implement this.


LVM self-repair (optional)
~~~~~~~~~~~~~~~~~~~~~~~~~~

The complete failure of a physical disk is very tedious to
troubleshoot, mainly because of the many failure modes and the many
steps needed. We can safely automate some of the steps, more
specifically the ``vgreduce --removemissing`` using the following
method:

#. check if all nodes have consistent volume groups
#. if yes, and previous status was yes, do nothing
#. if yes, and previous status was no, save status and restart
#. if no, and previous status was no, do nothing
#. if no, and previous status was yes:
    #. if more than one node is inconsistent, do nothing
    #. if only one node is incosistent:
        #. run ``vgreduce --removemissing``
        #. log this occurence in the ganeti log in a form that
           can be used for monitoring
        #. [FUTURE] run ``replace-disks`` for all
           instances affected

Failover to any node
~~~~~~~~~~~~~~~~~~~~

With a modified disk activation sequence, we can implement the
*failover to any* functionality, removing many of the layout
restrictions of a cluster:

- the need to reserve memory on the current secondary: this gets reduced to
  a must to reserve memory anywhere on the cluster

- the need to first failover and then replace secondary for an
  instance: with failover-to-any, we can directly failover to
  another node, which also does the replace disks at the same
  step

In the following, we denote the current primary by P1, the current
secondary by S1, and the new primary and secondaries by P2 and S2. P2
is fixed to the node the user chooses, but the choice of S2 can be
made between P1 and S1. This choice can be constrained, depending on
which of P1 and S1 has failed.

- if P1 has failed, then S1 must become S2, and live migration is not possible
- if S1 has failed, then P1 must become S2, and live migration could be
  possible (in theory, but this is not a design goal for 2.0)

The algorithm for performing the failover is straightforward:

- verify that S2 (the node the user has chosen to keep as secondary) has
  valid data (is consistent)

- tear down the current DRBD association and setup a drbd pairing between
  P2 (P2 is indicated by the user) and S2; since P2 has no data, it will
  start resyncing from S2

- as soon as P2 is in state SyncTarget (i.e. after the resync has started
  but before it has finished), we can promote it to primary role (r/w)
  and start the instance on P2

- as soon as the P2⇐S2 sync has finished, we can remove
  the old data on the old node that has not been chosen for
  S2

Caveats: during the P2⇐S2 sync, a (non-transient) network error
will cause I/O errors on the instance, so (if a longer instance
downtime is acceptable) we can postpone the restart of the instance
until the resync is done. However, disk I/O errors on S2 will cause
dataloss, since we don't have a good copy of the data anymore, so in
this case waiting for the sync to complete is not an option. As such,
it is recommended that this feature is used only in conjunction with
proper disk monitoring.


Live migration note: While failover-to-any is possible for all choices
of S2, migration-to-any is possible only if we keep P1 as S2.

Caveats
-------

The dynamic device model, while more complex, has an advantage: it
will not reuse by mistake another's instance DRBD device, since it
always looks for either our own or a free one.

The static one, in contrast, will assume that given a minor number N,
it's ours and we can take over. This needs careful implementation such
that if the minor is in use, either we are able to cleanly shut it
down, or we abort the startup. Otherwise, it could be that we start
syncing between two instance's disks, causing dataloss.

Security Considerations
-----------------------

The changes will not affect the security model of Ganeti.
