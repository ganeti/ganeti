=================
Ganeti 2.2 design
=================

This document describes the major changes in Ganeti 2.2 compared to
the 2.1 version.

The 2.2 version will be a relatively small release. Its main aim is to
avoid changing too much of the core code, while addressing issues and
adding new features and improvements over 2.1, in a timely fashion.

.. contents:: :depth: 4

As for 2.1 we divide the 2.2 design into three areas:

- core changes, which affect the master daemon/job queue/locking or
  all/most logical units
- logical unit/feature changes
- external interface changes (e.g. command line, OS API, hooks, ...)


Core changes
============

Master Daemon Scaling improvements
----------------------------------

Current state and shortcomings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Currently the Ganeti master daemon is based on four sets of threads:

- The main thread (1 thread) just accepts connections on the master
  socket
- The client worker pool (16 threads) handles those connections,
  one thread per connected socket, parses luxi requests, and sends data
  back to the clients
- The job queue worker pool (25 threads) executes the actual jobs
  submitted by the clients
- The rpc worker pool (10 threads) interacts with the nodes via
  http-based-rpc

This means that every masterd currently runs 52 threads to do its job.
Being able to reduce the number of thread sets would make the master's
architecture a lot simpler. Moreover having less threads can help
decrease lock contention, log pollution and memory usage.
Also, with the current architecture, masterd suffers from quite a few
scalability issues:

Core daemon connection handling
+++++++++++++++++++++++++++++++

Since the 16 client worker threads handle one connection each, it's very
easy to exhaust them, by just connecting to masterd 16 times and not
sending any data. While we could perhaps make those pools resizable,
increasing the number of threads won't help with lock contention nor
with better handling long running operations making sure the client is
informed that everything is proceeding, and doesn't need to time out.

Wait for job change
+++++++++++++++++++

The REQ_WAIT_FOR_JOB_CHANGE luxi operation makes the relevant client
thread block on its job for a relatively long time. This is another
easy way to exhaust the 16 client threads, and a place where clients
often time out, moreover this operation is negative for the job queue
lock contention (see below).

Job Queue lock
++++++++++++++

The job queue lock is quite heavily contended, and certain easily
reproducible workloads show that's it's very easy to put masterd in
trouble: for example running ~15 background instance reinstall jobs,
results in a master daemon that, even without having finished the
client worker threads, can't answer simple job list requests, or
submit more jobs.

Currently the job queue lock is an exclusive non-fair lock insulating
the following job queue methods (called by the client workers).

  - AddNode
  - RemoveNode
  - SubmitJob
  - SubmitManyJobs
  - WaitForJobChanges
  - CancelJob
  - ArchiveJob
  - AutoArchiveJobs
  - QueryJobs
  - Shutdown

Moreover the job queue lock is acquired outside of the job queue in two
other classes:

  - jqueue._JobQueueWorker (in RunTask) before executing the opcode, after
    finishing its executing and when handling an exception.
  - jqueue._OpExecCallbacks (in NotifyStart and Feedback) when the
    processor (mcpu.Processor) is about to start working on the opcode
    (after acquiring the necessary locks) and when any data is sent back
    via the feedback function.

Of those the major critical points are:

  - Submit[Many]Job, QueryJobs, WaitForJobChanges, which can easily slow
    down and block client threads up to making the respective clients
    time out.
  - The code paths in NotifyStart, Feedback, and RunTask, which slow
    down job processing between clients and otherwise non-related jobs.

To increase the pain:

  - WaitForJobChanges is a bad offender because it's implemented with a
    notified condition which awakes waiting threads, who then try to
    acquire the global lock again
  - Many should-be-fast code paths are slowed down by replicating the
    change to remote nodes, and thus waiting, with the lock held, on
    remote rpcs to complete (starting, finishing, and submitting jobs)

Proposed changes
~~~~~~~~~~~~~~~~

In order to be able to interact with the master daemon even when it's
under heavy load, and  to make it simpler to add core functionality
(such as an asynchronous rpc client) we propose three subsequent levels
of changes to the master core architecture.

After making this change we'll be able to re-evaluate the size of our
thread pool, if we see that we can make most threads in the client
worker pool always idle. In the future we should also investigate making
the rpc client asynchronous as well, so that we can make masterd a lot
smaller in number of threads, and memory size, and thus also easier to
understand, debug, and scale.

Connection handling
+++++++++++++++++++

We'll move the main thread of ganeti-masterd to asyncore, so that it can
share the mainloop code with all other Ganeti daemons. Then all luxi
clients will be asyncore clients, and I/O to/from them will be handled
by the master thread asynchronously. Data will be read from the client
sockets as it becomes available, and kept in a buffer, then when a
complete message is found, it's passed to a client worker thread for
parsing and processing. The client worker thread is responsible for
serializing the reply, which can then be sent asynchronously by the main
thread on the socket.

Wait for job change
+++++++++++++++++++

The REQ_WAIT_FOR_JOB_CHANGE luxi request is changed to be
subscription-based, so that the executing thread doesn't have to be
waiting for the changes to arrive. Threads producing messages (job queue
executors) will make sure that when there is a change another thread is
awakened and delivers it to the waiting clients. This can be either a
dedicated "wait for job changes" thread or pool, or one of the client
workers, depending on what's easier to implement. In either case the
main asyncore thread will only be involved in pushing of the actual
data, and not in fetching/serializing it.

Other features to look at, when implementing this code are:

  - Possibility not to need the job lock to know which updates to push:
    if the thread producing the data pushed a copy of the update for the
    waiting clients, the thread sending it won't need to acquire the
    lock again to fetch the actual data.
  - Possibility to signal clients about to time out, when no update has
    been received, not to despair and to keep waiting (luxi level
    keepalive).
  - Possibility to defer updates if they are too frequent, providing
    them at a maximum rate (lower priority).

Job Queue lock
++++++++++++++

In order to decrease the job queue lock contention, we will change the
code paths in the following ways, initially:

  - A per-job lock will be introduced. All operations affecting only one
    job (for example feedback, starting/finishing notifications,
    subscribing to or watching a job) will only require the job lock.
    This should be a leaf lock, but if a situation arises in which it
    must be acquired together with the global job queue lock the global
    one must always be acquired last (for the global section).
  - The locks will be converted to a sharedlock. Any read-only operation
    will be able to proceed in parallel.
  - During remote update (which happens already per-job) we'll drop the
    job lock level to shared mode, so that activities reading the lock
    (for example job change notifications or QueryJobs calls) will be
    able to proceed in parallel.
  - The wait for job changes improvements proposed above will be
    implemented.

In the future other improvements may include splitting off some of the
work (eg replication of a job to remote nodes) to a separate thread pool
or asynchronous thread, not tied with the code path for answering client
requests or the one executing the "real" work. This can be discussed
again after we used the more granular job queue in production and tested
its benefits.


Inter-cluster instance moves
----------------------------

Current state and shortcomings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

With the current design of Ganeti, moving whole instances between
different clusters involves a lot of manual work. There are several ways
to move instances, one of them being to export the instance, manually
copying all data to the new cluster before importing it again. Manual
changes to the instances configuration, such as the IP address, may be
necessary in the new environment. The goal is to improve and automate
this process in Ganeti 2.2.

Proposed changes
~~~~~~~~~~~~~~~~

Authorization, Authentication and Security
++++++++++++++++++++++++++++++++++++++++++

Until now, each Ganeti cluster was a self-contained entity and wouldn't
talk to other Ganeti clusters. Nodes within clusters only had to trust
the other nodes in the same cluster and the network used for replication
was trusted, too (hence the ability the use a separate, local network
for replication).

For inter-cluster instance transfers this model must be weakened. Nodes
in one cluster will have to talk to nodes in other clusters, sometimes
in other locations and, very important, via untrusted network
connections.

Various option have been considered for securing and authenticating the
data transfer from one machine to another. To reduce the risk of
accidentally overwriting data due to software bugs, authenticating the
arriving data was considered critical. Eventually we decided to use
socat's OpenSSL options (``OPENSSL:``, ``OPENSSL-LISTEN:`` et al), which
provide us with encryption, authentication and authorization when used
with separate keys and certificates.

Combinations of OpenSSH, GnuPG and Netcat were deemed too complex to set
up from within Ganeti. Any solution involving OpenSSH would require a
dedicated user with a home directory and likely automated modifications
to the user's ``$HOME/.ssh/authorized_keys`` file. When using Netcat,
GnuPG or another encryption method would be necessary to transfer the
data over an untrusted network. socat combines both in one program and
is already a dependency.

Each of the two clusters will have to generate an RSA key. The public
parts are exchanged between the clusters by a third party, such as an
administrator or a system interacting with Ganeti via the remote API
("third party" from here on). After receiving each other's public key,
the clusters can start talking to each other.

All encrypted connections must be verified on both sides. Neither side
may accept unverified certificates. The generated certificate should
only be valid for the time necessary to move the instance.

For additional protection of the instance data, the two clusters can
verify the certificates and destination information exchanged via the
third party by checking an HMAC signature using a key shared among the
involved clusters. By default this secret key will be a random string
unique to the cluster, generated by running SHA1 over 20 bytes read from
``/dev/urandom`` and the administrator must synchronize the secrets
between clusters before instances can be moved. If the third party does
not know the secret, it can't forge the certificates or redirect the
data. Unless disabled by a new cluster parameter, verifying the HMAC
signatures must be mandatory. The HMAC signature for X509 certificates
will be prepended to the certificate similar to an :rfc:`822` header and
only covers the certificate (from ``-----BEGIN CERTIFICATE-----`` to
``-----END CERTIFICATE-----``). The header name will be
``X-Ganeti-Signature`` and its value will have the format
``$salt/$hash`` (salt and hash separated by slash). The salt may only
contain characters in the range ``[a-zA-Z0-9]``.

On the web, the destination cluster would be equivalent to an HTTPS
server requiring verifiable client certificates. The browser would be
equivalent to the source cluster and must verify the server's
certificate while providing a client certificate to the server.

Copying data
++++++++++++

To simplify the implementation, we decided to operate at a block-device
level only, allowing us to easily support non-DRBD instance moves.

Intra-cluster instance moves will re-use the existing export and import
scripts supplied by instance OS definitions. Unlike simply copying the
raw data, this allows one to use filesystem-specific utilities to dump
only used parts of the disk and to exclude certain disks from the move.
Compression should be used to further reduce the amount of data
transferred.

The export scripts writes all data to stdout and the import script reads
it from stdin again. To avoid copying data and reduce disk space
consumption, everything is read from the disk and sent over the network
directly, where it'll be written to the new block device directly again.

Workflow
++++++++

#. Third party tells source cluster to shut down instance, asks for the
   instance specification and for the public part of an encryption key

   - Instance information can already be retrieved using an existing API
     (``OpInstanceQueryData``).
   - An RSA encryption key and a corresponding self-signed X509
     certificate is generated using the "openssl" command. This key will
     be used to encrypt the data sent to the destination cluster.

     - Private keys never leave the cluster.
     - The public part (the X509 certificate) is signed using HMAC with
       salting and a secret shared between Ganeti clusters.

#. Third party tells destination cluster to create an instance with the
   same specifications as on source cluster and to prepare for an
   instance move with the key received from the source cluster and
   receives the public part of the destination's encryption key

   - The current API to create instances (``OpInstanceCreate``) will be
     extended to support an import from a remote cluster.
   - A valid, unexpired X509 certificate signed with the destination
     cluster's secret will be required. By verifying the signature, we
     know the third party didn't modify the certificate.

     - The private keys never leave their cluster, hence the third party
       can not decrypt or intercept the instance's data by modifying the
       IP address or port sent by the destination cluster.

   - The destination cluster generates another key and certificate,
     signs and sends it to the third party, who will have to pass it to
     the API for exporting an instance (``OpBackupExport``). This
     certificate is used to ensure we're sending the disk data to the
     correct destination cluster.
   - Once a disk can be imported, the API sends the destination
     information (IP address and TCP port) together with an HMAC
     signature to the third party.

#. Third party hands public part of the destination's encryption key
   together with all necessary information to source cluster and tells
   it to start the move

   - The existing API for exporting instances (``OpBackupExport``)
     will be extended to export instances to remote clusters.

#. Source cluster connects to destination cluster for each disk and
   transfers its data using the instance OS definition's export and
   import scripts

   - Before starting, the source cluster must verify the HMAC signature
     of the certificate and destination information (IP address and TCP
     port).
   - When connecting to the remote machine, strong certificate checks
     must be employed.

#. Due to the asynchronous nature of the whole process, the destination
   cluster checks whether all disks have been transferred every time
   after transferring a single disk; if so, it destroys the encryption
   key
#. After sending all disks, the source cluster destroys its key
#. Destination cluster runs OS definition's rename script to adjust
   instance settings if needed (e.g. IP address)
#. Destination cluster starts the instance if requested at the beginning
   by the third party
#. Source cluster removes the instance if requested

Instance move in pseudo code
++++++++++++++++++++++++++++

.. highlight:: python

The following pseudo code describes a script moving instances between
clusters and what happens on both clusters.

#. Script is started, gets the instance name and destination cluster::

    (instance_name, dest_cluster_name) = sys.argv[1:]

    # Get destination cluster object
    dest_cluster = db.FindCluster(dest_cluster_name)

    # Use database to find source cluster
    src_cluster = db.FindClusterByInstance(instance_name)

#. Script tells source cluster to stop instance::

    # Stop instance
    src_cluster.StopInstance(instance_name)

    # Get instance specification (memory, disk, etc.)
    inst_spec = src_cluster.GetInstanceInfo(instance_name)

    (src_key_name, src_cert) = src_cluster.CreateX509Certificate()

#. ``CreateX509Certificate`` on source cluster::

    key_file = mkstemp()
    cert_file = "%s.cert" % key_file
    RunCmd(["/usr/bin/openssl", "req", "-new",
             "-newkey", "rsa:1024", "-days", "1",
             "-nodes", "-x509", "-batch",
             "-keyout", key_file, "-out", cert_file])

    plain_cert = utils.ReadFile(cert_file)

    # HMAC sign using secret key, this adds a "X-Ganeti-Signature"
    # header to the beginning of the certificate
    signed_cert = utils.SignX509Certificate(plain_cert,
      utils.ReadFile(constants.X509_SIGNKEY_FILE))

    # The certificate now looks like the following:
    #
    #   X-Ganeti-Signature: $1234$28676f0516c6ab68062b[…]
    #   -----BEGIN CERTIFICATE-----
    #   MIICsDCCAhmgAwIBAgI[…]
    #   -----END CERTIFICATE-----

    # Return name of key file and signed certificate in PEM format
    return (os.path.basename(key_file), signed_cert)

#. Script creates instance on destination cluster and waits for move to
   finish::

    dest_cluster.CreateInstance(mode=constants.REMOTE_IMPORT,
                                spec=inst_spec,
                                source_cert=src_cert)

    # Wait until destination cluster gives us its certificate
    dest_cert = None
    disk_info = []
    while not (dest_cert and len(disk_info) < len(inst_spec.disks)):
      tmp = dest_cluster.WaitOutput()
      if tmp is Certificate:
        dest_cert = tmp
      elif tmp is DiskInfo:
        # DiskInfo contains destination address and port
        disk_info[tmp.index] = tmp

    # Tell source cluster to export disks
    for disk in disk_info:
      src_cluster.ExportDisk(instance_name, disk=disk,
                             key_name=src_key_name,
                             dest_cert=dest_cert)

    print ("Instance %s sucessfully moved to %s" %
           (instance_name, dest_cluster.name))

#. ``CreateInstance`` on destination cluster::

    # …

    if mode == constants.REMOTE_IMPORT:
      # Make sure certificate was not modified since it was generated by
      # source cluster (which must use the same secret)
      if (not utils.VerifySignedX509Cert(source_cert,
            utils.ReadFile(constants.X509_SIGNKEY_FILE))):
        raise Error("Certificate not signed with this cluster's secret")

      if utils.CheckExpiredX509Cert(source_cert):
        raise Error("X509 certificate is expired")

      source_cert_file = utils.WriteTempFile(source_cert)

      # See above for X509 certificate generation and signing
      (key_name, signed_cert) = CreateSignedX509Certificate()

      SendToClient("x509-cert", signed_cert)

      for disk in instance.disks:
        # Start socat
        RunCmd(("socat"
                " OPENSSL-LISTEN:%s,…,key=%s,cert=%s,cafile=%s,verify=1"
                " stdout > /dev/disk…") %
               port, GetRsaKeyPath(key_name, private=True),
               GetRsaKeyPath(key_name, private=False), src_cert_file)
        SendToClient("send-disk-to", disk, ip_address, port)

      DestroyX509Cert(key_name)

      RunRenameScript(instance_name)

#. ``ExportDisk`` on source cluster::

    # Make sure certificate was not modified since it was generated by
    # destination cluster (which must use the same secret)
    if (not utils.VerifySignedX509Cert(cert_pem,
          utils.ReadFile(constants.X509_SIGNKEY_FILE))):
      raise Error("Certificate not signed with this cluster's secret")

    if utils.CheckExpiredX509Cert(cert_pem):
      raise Error("X509 certificate is expired")

    dest_cert_file = utils.WriteTempFile(cert_pem)

    # Start socat
    RunCmd(("socat stdin"
            " OPENSSL:%s:%s,…,key=%s,cert=%s,cafile=%s,verify=1"
            " < /dev/disk…") %
           disk.host, disk.port,
           GetRsaKeyPath(key_name, private=True),
           GetRsaKeyPath(key_name, private=False), dest_cert_file)

    if instance.all_disks_done:
      DestroyX509Cert(key_name)

.. highlight:: text

Miscellaneous notes
+++++++++++++++++++

- A very similar system could also be used for instance exports within
  the same cluster. Currently OpenSSH is being used, but could be
  replaced by socat and SSL/TLS.
- During the design of intra-cluster instance moves we also discussed
  encrypting instance exports using GnuPG.
- While most instances should have exactly the same configuration as
  on the source cluster, setting them up with a different disk layout
  might be helpful in some use-cases.
- A cleanup operation, similar to the one available for failed instance
  migrations, should be provided.
- ``ganeti-watcher`` should remove instances pending a move from another
  cluster after a certain amount of time. This takes care of failures
  somewhere in the process.
- RSA keys can be generated using the existing
  ``bootstrap.GenerateSelfSignedSslCert`` function, though it might be
  useful to not write both parts into a single file, requiring small
  changes to the function. The public part always starts with
  ``-----BEGIN CERTIFICATE-----`` and ends with ``-----END
  CERTIFICATE-----``.
- The source and destination cluster might be different when it comes
  to available hypervisors, kernels, etc. The destination cluster should
  refuse to accept an instance move if it can't fulfill an instance's
  requirements.


Privilege separation
--------------------

Current state and shortcomings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All Ganeti daemons are run under the user root. This is not ideal from a
security perspective as for possible exploitation of any daemon the user
has full access to the system.

In order to overcome this situation we'll allow Ganeti to run its daemon
under different users and a dedicated group. This also will allow some
side effects, like letting the user run some ``gnt-*`` commands if one
is in the same group.

Implementation
~~~~~~~~~~~~~~

For Ganeti 2.2 the implementation will be focused on a the RAPI daemon
only. This involves changes to ``daemons.py`` so it's possible to drop
privileges on daemonize the process. Though, this will be a short term
solution which will be replaced by a privilege drop already on daemon
startup in Ganeti 2.3.

It also needs changes in the master daemon to create the socket with new
permissions/owners to allow RAPI access. There will be no other
permission/owner changes in the file structure as the RAPI daemon is
started with root permission. In that time it will read all needed files
and then drop privileges before contacting the master daemon.


Feature changes
===============

KVM Security
------------

Current state and shortcomings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Currently all kvm processes run as root. Taking ownership of the
hypervisor process, from inside a virtual machine, would mean a full
compromise of the whole Ganeti cluster, knowledge of all Ganeti
authentication secrets, full access to all running instances, and the
option of subverting other basic services on the cluster (eg: ssh).

Proposed changes
~~~~~~~~~~~~~~~~

We would like to decrease the surface of attack available if an
hypervisor is compromised. We can do so adding different features to
Ganeti, which will allow restricting the broken hypervisor
possibilities, in the absence of a local privilege escalation attack, to
subvert the node.

Dropping privileges in kvm to a single user (easy)
++++++++++++++++++++++++++++++++++++++++++++++++++

By passing the ``-runas`` option to kvm, we can make it drop privileges.
The user can be chosen by an hypervisor parameter, so that each instance
can have its own user, but by default they will all run under the same
one. It should be very easy to implement, and can easily be backported
to 2.1.X.

This mode protects the Ganeti cluster from a subverted hypervisor, but
doesn't protect the instances between each other, unless care is taken
to specify a different user for each. This would prevent the worst
attacks, including:

- logging in to other nodes
- administering the Ganeti cluster
- subverting other services

But the following would remain an option:

- terminate other VMs (but not start them again, as that requires root
  privileges to set up networking) (unless different users are used)
- trace other VMs, and probably subvert them and access their data
  (unless different users are used)
- send network traffic from the node
- read unprotected data on the node filesystem

Running kvm in a chroot (slightly harder)
+++++++++++++++++++++++++++++++++++++++++

By passing the ``-chroot`` option to kvm, we can restrict the kvm
process in its own (possibly empty) root directory. We need to set this
area up so that the instance disks and control sockets are accessible,
so it would require slightly more work at the Ganeti level.

Breaking out in a chroot would mean:

- a lot less options to find a local privilege escalation vector
- the impossibility to write local data, if the chroot is set up
  correctly
- the impossibility to read filesystem data on the host

It would still be possible though to:

- terminate other VMs
- trace other VMs, and possibly subvert them (if a tracer can be
  installed in the chroot)
- send network traffic from the node


Running kvm with a pool of users (slightly harder)
++++++++++++++++++++++++++++++++++++++++++++++++++

If rather than passing a single user as an hypervisor parameter, we have
a pool of useable ones, we can dynamically choose a free one to use and
thus guarantee that each machine will be separate from the others,
without putting the burden of this on the cluster administrator.

This would mean interfering between machines would be impossible, and
can still be combined with the chroot benefits.

Running iptables rules to limit network interaction (easy)
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

These don't need to be handled by Ganeti, but we can ship examples. If
the users used to run VMs would be blocked from sending some or all
network traffic, it would become impossible for a broken into hypervisor
to send arbitrary data on the node network, which is especially useful
when the instance and the node network are separated (using ganeti-nbma
or a separate set of network interfaces), or when a separate replication
network is maintained. We need to experiment to see how much restriction
we can properly apply, without limiting the instance legitimate traffic.


Running kvm inside a container (even harder)
++++++++++++++++++++++++++++++++++++++++++++

Recent linux kernels support different process namespaces through
control groups. PIDs, users, filesystems and even network interfaces can
be separated. If we can set up ganeti to run kvm in a separate container
we could insulate all the host process from being even visible if the
hypervisor gets broken into. Most probably separating the network
namespace would require one extra hop in the host, through a veth
interface, thus reducing performance, so we may want to avoid that, and
just rely on iptables.

Implementation plan
~~~~~~~~~~~~~~~~~~~

We will first implement dropping privileges for kvm processes as a
single user, and most probably backport it to 2.1. Then we'll ship
example iptables rules to show how the user can be limited in its
network activities.  After that we'll implement chroot restriction for
kvm processes, and extend the user limitation to use a user pool.

Finally we'll look into namespaces and containers, although that might
slip after the 2.2 release.

New OS states
-------------

Separate from the OS external changes, described below, we'll add some
internal changes to the OS.

Current state and shortcomings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

There are two issues related to the handling of the OSes.

First, it's impossible to disable an OS for new instances, since that
will also break reinstallations and renames of existing instances. To
phase out an OS definition, without actually having to modify the OS
scripts, it would be ideal to be able to restrict new installations but
keep the rest of the functionality available.

Second, ``gnt-instance reinstall --select-os`` shows all the OSes
available on the clusters. Some OSes might exist only for debugging and
diagnose, and not for end-user availability. For this, it would be
useful to "hide" a set of OSes, but keep it otherwise functional.

Proposed changes
~~~~~~~~~~~~~~~~

Two new cluster-level attributes will be added, holding the list of OSes
hidden from the user and respectively the list of OSes which are
blacklisted from new installations.

These lists will be modifiable via ``gnt-os modify`` (implemented via
``OpClusterSetParams``), such that even not-yet-existing OSes can be
preseeded into a given state.

For the hidden OSes, they are fully functional except that they are not
returned in the default OS list (as computed via ``OpOsDiagnose``),
unless the hidden state is requested.

For the blacklisted OSes, they are also not shown (unless the
blacklisted state is requested), and they are also prevented from
installation via ``OpInstanceCreate`` (in create mode).

Both these attributes are per-OS, not per-variant. Thus they apply to
all of an OS' variants, and it's impossible to blacklist or hide just
one variant. Further improvements might allow a given OS variant to be
blacklisted, as opposed to whole OSes.

External interface changes
==========================


OS API
------

The OS variants implementation in Ganeti 2.1 didn't prove to be useful
enough to alleviate the need to hack around the Ganeti API in order to
provide flexible OS parameters.

As such, for Ganeti 2.2 we will provide support for arbitrary OS
parameters. However, since OSes are not registered in Ganeti, but
instead discovered at runtime, the interface is not entirely
straightforward.

Furthermore, to support the system administrator in keeping OSes
properly in sync across the nodes of a cluster, Ganeti will also verify
(if existing) the consistence of a new ``os_version`` file.

These changes to the OS API will bump the API version to 20.


OS version
~~~~~~~~~~

A new ``os_version`` file will be supported by Ganeti. This file is not
required, but if existing, its contents will be checked for consistency
across nodes. The file should hold only one line of text (any extra data
will be discarded), and its contents will be shown in the OS information
and diagnose commands.

It is recommended that OS authors increase the contents of this file for
any changes; at a minimum, modifications that change the behaviour of
import/export scripts must increase the version, since they break
intra-cluster migration.

Parameters
~~~~~~~~~~

The interface between Ganeti and the OS scripts will be based on
environment variables, and as such the parameters and their values will
need to be valid in this context.

Names
+++++

The parameter names will be declared in a new file, ``parameters.list``,
together with a one-line documentation (whitespace-separated). Example::

  $ cat parameters.list
  ns1    Specifies the first name server to add to /etc/resolv.conf
  extra_packages  Specifies additional packages to install
  rootfs_size     Specifies the root filesystem size (the rest will be left unallocated)
  track  Specifies the distribution track, one of 'stable', 'testing' or 'unstable'

As seen above, the documentation can be separate via multiple
spaces/tabs from the names.

The parameter names as read from the file will be used for the command
line interface in lowercased form; as such, there shouldn't be any two
parameters which differ in case only.

Values
++++++

The values of the parameters are, from Ganeti's point of view,
completely freeform. If a given parameter has, from the OS' point of
view, a fixed set of valid values, these should be documented as such
and verified by the OS, but Ganeti will not handle such parameters
specially.

An empty value must be handled identically as a missing parameter. In
other words, the validation script should only test for non-empty
values, and not for declared versus undeclared parameters.

Furthermore, each parameter should have an (internal to the OS) default
value, that will be used if not passed from Ganeti. More precisely, it
should be possible for any parameter to specify a value that will have
the same effect as not passing the parameter, and no in no case should
the absence of a parameter be treated as an exceptional case (outside
the value space).


Environment variables
^^^^^^^^^^^^^^^^^^^^^

The parameters will be exposed in the environment upper-case and
prefixed with the string ``OSP_``. For example, a parameter declared in
the 'parameters' file as ``ns1`` will appear in the environment as the
variable ``OSP_NS1``.

Validation
++++++++++

For the purpose of parameter name/value validation, the OS scripts
*must* provide an additional script, named ``verify``. This script will
be called with the argument ``parameters``, and all the parameters will
be passed in via environment variables, as described above.

The script should signify result/failure based on its exit code, and
show explanatory messages either on its standard output or standard
error. These messages will be passed on to the master, and stored as in
the OpCode result/error message.

The parameters must be constructed to be independent of the instance
specifications. In general, the validation script will only be called
with the parameter variables set, but not with the normal per-instance
variables, in order for Ganeti to be able to validate default parameters
too, when they change. Validation will only be performed on one cluster
node, and it will be up to the ganeti administrator to keep the OS
scripts in sync between all nodes.

Instance operations
+++++++++++++++++++

The parameters will be passed, as described above, to all the other
instance operations (creation, import, export). Ideally, these scripts
will not abort with parameter validation errors, if the ``verify``
script has verified them correctly.

Note: when changing an instance's OS type, any OS parameters defined at
instance level will be kept as-is. If the parameters differ between the
new and the old OS, the user should manually remove/update them as
needed.

Declaration and modification
++++++++++++++++++++++++++++

Since the OSes are not registered in Ganeti, we will only make a 'weak'
link between the parameters as declared in Ganeti and the actual OSes
existing on the cluster.

It will be possible to declare parameters either globally, per cluster
(where they are indexed per OS/variant), or individually, per
instance. The declaration of parameters will not be tied to current
existing OSes. When specifying a parameter, if the OS exists, it will be
validated; if not, then it will simply be stored as-is.

A special note is that it will not be possible to 'unset' at instance
level a parameter that is declared globally. Instead, at instance level
the parameter should be given an explicit value, or the default value as
explained above.

CLI interface
+++++++++++++

The modification of global (default) parameters will be done via the
``gnt-os`` command, and the per-instance parameters via the
``gnt-instance`` command. Both these commands will take an addition
``--os-parameters`` or ``-O`` flag that specifies the parameters in the
familiar comma-separated, key=value format. For removing a parameter, a
``-key`` syntax will be used, e.g.::

  # initial modification
  $ gnt-instance modify -O use_dchp=true instance1
  # later revert (to the cluster default, or the OS default if not
  # defined at cluster level)
  $ gnt-instance modify -O -use_dhcp instance1

Internal storage
++++++++++++++++

Internally, the OS parameters will be stored in a new ``osparams``
attribute. The global parameters will be stored on the cluster object,
and the value of this attribute will be a dictionary indexed by OS name
(this also accepts an OS+variant name, which will override a simple OS
name, see below), and for values the key/name dictionary. For the
instances, the value will be directly the key/name dictionary.

Overriding rules
++++++++++++++++

Any instance-specific parameters will override any variant-specific
parameters, which in turn will override any global parameters. The
global parameters, in turn, override the built-in defaults (of the OS
scripts).


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
