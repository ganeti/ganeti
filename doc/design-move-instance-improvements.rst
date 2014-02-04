========================================
Instance move improvements
========================================

.. contents:: :depth: 3

Ganeti provides tools for moving instances within and between clusters. Through
special export and import calls, a new instance is created with the disk data of
the existing one.

The tools work correctly and reliably, but depending on bandwidth and priority,
an instance disk of considerable size requires a long time to transfer. The
length of the transfer is inconvenient at best, but the problem becomes only
worse if excessive locking causes a move operation to be delayed for a longer
period of time, or to block other operations.

The performance of moves is a complex topic, with available bandwidth,
compression, and encryption all being candidates for choke points that bog down
a transfer. Depending on the environment a move is performed in, tuning these
can have significant performance benefits, but Ganeti does not expose many
options needed for such tuning. The details of what to expose and what tradeoffs
can be made will be presented in this document.

Apart from existing functionality, some beneficial features can be introduced to
help with instance moves. Zeroing empty space on instance disks can be useful
for drastically improving the qualities of compression, effectively not needing
to transfer unused disk space during moves. Compression itself can be improved
by using different tools. The encryption used can be weakened or eliminated for
certain moves. Using opportunistic locking during instance moves results in
greater parallelization. As all of these approaches aim to tackle two different
aspects of the problem, they do not exclude each other and will be presented
independently.

The performance of Ganeti moves
===============================

In the current implementation, there are three possible factors limiting the
speed of an instance move. The first is the network bandwidth, which Ganeti can
exploit better by using compression. The second is the encryption, which is
obligatory, and which can throttle an otherwise fast connection. The third is
surprisingly the compression, which can cause the connection to be
underutilized.

Example 1: some numbers present during an intra-cluster instance move:

* Network bandwidth: 105MB/s, courtesy of a gigabit switch

* Encryption performance: 40MB/s, provided by OpenSSL

* Compression performance: 22.3MB/s input, 7.1MB/s gzip compressed output

As can be seen in this example, the obligatory encryption results in 62% of
available bandwidth being wasted, while using compression further lowers the
throughput to 55% of what the encryption would allow. The following sections
will talk about these numbers in more detail, and suggest improvements and best
practices.

Encryption and Ganeti security
++++++++++++++++++++++++++++++

Turning compression and encryption off would allow for an immediate improvement,
and while that is possible for compression, there are good reasons why
encryption is currently not a feature a user can disable.

While it is impossible to secure instance data if an attacker gains SSH access
to a node, the RAPI was designed to never allow user data to be accessed through
it in case of being compromised. If moves could be performed unencrypted, this
property would be broken. Instance moves can take place in environments which
may be hostile, and where unencrypted traffic could be intercepted. As they can
be instigated through the RAPI, an attacker could access all data on all
instances in a cluster by moving them unencrypted and intercepting the data in
flight. This is one of the few situations where the current speed of instance
moves could be considered a perk.

The performance of encryption can be increased by either using a less secure
form of encryption, including no encryption, or using a faster encryption
algorithm. The example listed above utilizes AES-256, one of the few ciphers
that Ganeti deems secure enough to use. AES-128, also allowed by Ganeti's
current settings, is weaker but 46% faster. A cipher that is not allowed due to
its flaws, such as RC4, could offer a 208% increase in speed. On the other hand,
using an OS capable of utilizing the AES_NI chip present on modern hardware
can double the performance of AES, making it the best tradeoff between security
and performance.

Ganeti cannot and should not detect all the factors listed above, but should
rather give its users some leeway in what to choose. A precedent already exists,
as intra-cluster DRBD replication is already performed unencrypted, albeit on a
separate VLAN. For intra-cluster moves, Ganeti should allow its users to set
OpenSSL ciphers at will, while still enforcing high-security settings for moves
between clusters.

Thus, two settings will be introduced:

* a cluster-level setting called ``--allow-cipher-bypassing``, a boolean that
  cannot be set over RAPI

* a gnt-instance move setting called ``--ciphers-to-use``, bypassing the default
  cipher list with given ciphers, filtered to ensure no other OpenSSL options
  are passed in within

This change will serve to address the issues with moving non-redundant instances
within the cluster, while keeping Ganeti security at its current level.

Compression
+++++++++++

Support for disk compression during instance moves was partially present before,
but cleaned up and unified under the ``--compress`` option only as of Ganeti
2.11. The only option offered by Ganeti is gzip with no options passed to it,
resulting in a good compression ratio, but bad compression speed.

As compression can affect the speed of instance moves significantly, it is
worthwhile to explore alternatives. To test compression tool performance, an 8GB
drive filled with data matching the expected usage patterns (taken from a
workstation) was compressed by using various tools with various settings. The
two top performers were ``lzop`` and, surprisingly, ``gzip``. The improvement in
the performance of ``gzip`` was obtained by explicitly optimizing for speed
rather than compression.

* ``gzip -6``: 22.3MB/s in, 7.1MB/s out
* ``gzip -1``: 44.1MB/s in, 15.1MB/s out
* ``lzop``: 71.9MB/s in, 28.1MB/s out

If encryption is the limiting factor, and as in the example, limits the
bandwidth to 40MB/s, ``lzop`` allows for an effective 79% increase in transfer
speed. The fast ``gzip`` would also prove to be beneficial, but much less than
``lzop``. It should also be noted that as a rule of thumb, tools with a lower
compression ratio had a lesser workload, with ``lzop`` straining the CPU much
less than any of the competitors.

With the test results present here, it is clear that ``lzop`` would be a very
worthwhile addition to the compression options present in Ganeti, yet the
problem is that it is not available by default on all distributions, as the
option's presence might imply. In general, Ganeti may know how to use several
tools, and check for their presence, but should add some way of at least hinting
at which tools are available.

Additionally, the user might want to use a tool that Ganeti did not account for.
Allowing the tool to be named is also helpful, both for cases when multiple
custom tools are to be used, and for distinguishing between various tools in
case of e.g. inter-cluster moves.

To this end, the ``--compression-tools`` cluster parameter will be added to
Ganeti. It contains a list of names of compression tools that can be supplied as
the parameter of ``--compress``, and by default it contains all the tools
Ganeti knows how to use. The user can change the list as desired, removing
entries that are not or should not be available on the cluster, and adding
custom tools.

Every custom tool is identified by its name, and Ganeti expects the name to
correspond to a script invoking the compression tool. Without arguments, the
script compresses input on stdin, outputting it on stdout. With the -d argument,
the script does the same, only while decompressing. The -h argument is used to
check for the presence of the script, and in this case, only the error code is
examined. This syntax matches the ``gzip`` syntax well, which should allow most
compression tools to be adapted to it easily.

Ganeti will not allow arbitrary parameters to be passed to a compression tool,
and will restrict the names to contain only a small but assuredly safe subset of
characters - alphanumeric values and dashes and underscores. This minimizes the
risk of security issues that could arise from an attacker smuggling a malicious
command through RAPI. Common variations, like the speed/compression tradeoff of
``gzip``, will be handled by aliases, e.g. ``gzip-fast`` or ``gzip-slow``.

It should also be noted that for some purposes - e.g. the writing of OVF files,
``gzip`` is the only allowed means of compression, and an appropriate error
message should be displayed if the user attempts to use one of the other
provided tools.

Zeroing instance disks
======================

While compression lowers the amount of data sent, further reductions can be
achieved by taking advantage of the structure of the disk - namely, sending only
used disk sectors.

There is no direct way to achieve this, as it would require that the
move-instance tool is aware of the structure of the file system. Mounting the
filesystem is not an option, primarily due to security issues. A disk primed to
take advantage of a disk driver exploit could cause an attacker to breach
instance isolation and gain control of a Ganeti node.

An indirect way for this performance gain to be achieved is the zeroing of any
hard disk space not in use. While this primarily means empty space, swap
partitions can be zeroed as well.

Sequences of zeroes can be compressed and thus transferred very efficiently, all
without the host knowing that these are empty space. This approach can also be
dangerous if a sparse disk is zeroed in this way, causing ballooning. As Ganeti
does not seem to make special concessions for moving sparse disks, the only
difference should be the disk space utilization on the current node.

Zeroing approaches
++++++++++++++++++

Zeroing is a feasible approach, but the node cannot perform it as it cannot
mount the disk. Only virtualization-based options remain, and of those, using
Ganeti's own virtualization capabilities makes the most sense. There are two
ways of doing this - creating a new helper instance, temporary or persistent, or
reusing the target instance.

Both approaches have their disadvantages. Creating a new helper instance
requires managing its lifecycle, taking special care to make sure no helper
instance remains left over due to a failed operation. Even if this were to be
taken care of, disks are not yet separate entities in Ganeti, making the
temporary transfer of disks between instances hard to implement and even harder
to make robust. The reuse can be done by modifying the OS running on the
instance to perform the zeroing itself when notified via the new instance
communication mechanism, but this approach is neither generic, nor particularly
safe. There is no guarantee that the zeroing operation will not interfere with
the normal operation of the instance, nor that it will be completed if a
user-initiated shutdown occurs.

A better solution can be found by combining the two approaches - re-using the
virtualized environment, but with a specifically crafted OS image. With the
instance shut down as it should be in preparation for the move, it can be
extended with an additional disk with the OS image on it. By prepending the
disk and changing some instance parameters, the instance can boot from it. The
OS can be configured to perform the zeroing on startup, attempting to mount any
partitions with a filesystem present, and creating and deleting a zero-filled
file on them. After the zeroing is complete, the OS should shut down, and the
master should note the shutdown and restore the instance to its previous state.

Note that the requirements above are very similar to the notion of a helper VM
suggested in the OS install document. Some potentially unsafe actions are
performed within a virtualized environment, acting on disks that belong or will
belong to the instance. The mechanisms used will thus be developed with both
approaches in mind.

Implementation
++++++++++++++

There are two components to this solution - the Ganeti changes needed to boot
the OS, and the OS image used for the zeroing. Due to the variety of filesystems
and architectures that instances can use, no single ready-to-run disk image can
satisfy the needs of all the Ganeti users. Instead, the instance-debootstrap
scripts can be used to generate a zeroing-capable OS image. This might not be
ideal, as there are lightweight distributions that take up less space and boot
up more quickly. Generating those with the right set of drivers for the
virtualization platform of choice is not easy. Thus we do not provide a script
for this purpose, but the user is free to provide any OS image which performs
the necessary steps: zero out all virtualization-provided devices on startup,
shutdown immediately. The cluster-wide parameter controlling the image to be
used would be called ``--zeroing-image``.

The modifications to Ganeti code needed are minor. The zeroing functionality
should be implemented as an extension of the instance export, and exposed as the
``--zero-free-space option``. Prior to beginning the export, the instance
configuration is temporarily extended with a new read-only disk of sufficient
size to host the zeroing image, and the changes necessary for the image to be
used as the boot drive. The temporary nature of the configuration changes
requires that they are not propagated to other nodes. While this would normally
not be feasible with an instance using a disk template offering multi-node
redundancy, experiments with the code have shown that the restriction on
diverse disk templates can be bypassed to temporarily allow a plain
disk-template disk to host the zeroing image. Given that one of the planned
changes in Ganeti is to have instance disks as separate entities, with no
restriction on templates, this assumption is useful rather than harmful by
asserting the desired behavior. The image is dumped to the disk, and the
instance is started up.

Once the instance is started up, the zeroing will proceed until completion, when
a self-initiated shutdown will occur. The instance-shutdown detection
capabilities of 2.11 should prevent the watcher from restarting the instance
once this happens, allowing the host to take it as a sign the zeroing was
completed. Either way, the host waits until the instance is shut down, or a
timeout has been reached and the instance is forcibly shut down. As the time
needed to zero an instance is dependent on the size of the disk of the instance,
the user can provide a fixed and a per-size timeout, recommended to be set to
twice the maximum write speed of the device hosting the instance.

Better progress monitoring can be implemented with the instance-host
communication channel proposed by the OS install design document. The first
version will most likely use only the shutdown detection, and will be improved
to account for the available communication channel at a later time.

After the shutdown, the temporary disk is destroyed and the instance
configuration is reverted to its original state. The very same action is done if
any error is encountered during the zeroing process. In the case that the
zeroing is interrupted while the zero-filled file is being written, the file may
remain on the disk of the instance. The script that performs the zeroing will be
made to react to system signals by deleting the zero-filled file, but there is
little else that can be done to recover.

When to use zeroing
+++++++++++++++++++

The question of when it is useful to use zeroing is hard to answer because the
effectiveness of the approach depends on many factors. All compression tools
compress zeroes to almost nothingness, but compressing them takes time. If the
time needed to compress zeroes were equal to zero, the approach would boil down
to whether it is faster to zero unused space out, performing writes to disk, or
to transfer it compressed. For the example used above, the average compression
ratio, and write speeds of current disk drives, the answer would almost
unanimously be yes.

With a more realistic setup, where zeroes take time to compress, yet less time
than ordinary data, the gains depend on the previously mentioned tradeoff and
the free space available. Zeroing will definitely lessen the amount of bandwidth
used, but it can lead to the connection being underutilized due to the time
spent compressing data. It is up to the user to make these tradeoffs, but
zeroing should be seen primarily as a means of further reducing the amount of
data sent while increasing disk activity, with possible speed gains that should
not be relied upon.

In the future, the VM created for zeroing could also undertake other tasks
related to the move, such as compression and encryption, and produce a stream
of data rather than just modifying the disk. This would lessen the strain on
the resources of the hypervisor, both disk I/O and CPU usage, and allow moves to
obey the resource constraints placed on the instance being moved.

Lock reduction
==============

An instance move as executed by the move-instance tool consists of several
preparatory RAPI calls, leading up to two long-lasting opcodes: OpCreateInstance
and OpBackupExport. While OpBackupExport locks only the instance, the locks of
OpCreateInstance require more attention.

When executed, this opcode attempts to lock all nodes on which the instance may
be created and obtain shared locks on the groups they belong to. In the case
that an IAllocator is used, this means all nodes must be locked. Any operation
that requires a node lock to be present can delay the move operation, and there
is no shortage of these.

The concept of opportunistic locking has been introduced to remedy exactly this
situation, allowing the IAllocator to lock as many nodes as possible. Depending
whether the allocation can be made on these nodes, the operation either proceeds
as expected, or fails noting that it is temporarily infeasible. The failure case
would change the semantics of the move-instance tool, which is expected to fail
only if the move is impossible. To yield the benefits of opportunistic locking
yet satisfy this constraint, the move-instance tool can be extended with the
--opportunistic-tries and --opportunistic-try-delay options. A number of
opportunistic instance creations are attempted, with a delay between attempts.
The delay is slightly altered every time to avoid timing issues. Should all
attempts fail, a normal instance creation is requested, which blocks until all
the locks can be acquired.

While it may seem excessive to grab so many node locks, the early release
mechanism is used to make the situation less dire, releasing all nodes that were
not chosen as candidates for allocation. This is taken to the extreme as all the
locks acquired are released prior to the start of the transfer, barring the
newly-acquired lock over the new instance. This works because all operations
that alter the node in a way which could affect the transfer:

* are prevented by the instance lock or instance presence, e.g. gnt-node remove,
  gnt-node evacuate,

* do not interrupt the transfer, e.g. a PV on the node can be set as
  unallocatable, and the transfer still proceeds as expected,

* do not care, e.g. a gnt-node powercycle explicitly ignores all locks.

This invariant should be kept in mind, and perhaps verified through tests.

All in all, there is very little space to reduce the number of locks used, and
the only improvement that can be made is introducing opportunistic locking as an
option of move-instance.

Introduction of changes
=======================

All the changes noted will be implemented in Ganeti 2.12, in the way described
in the previous chapters. They will be implemented as separate changes, first
the lock reduction, then the instance zeroing, then the compression
improvements, and finally the encryption changes.
