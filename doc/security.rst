Security in Ganeti
==================

Documents Ganeti version 2.6

Ganeti was developed to run on internal, trusted systems. As such, the
security model is all-or-nothing.

Up to version 2.3 all Ganeti code ran as root. Since version 2.4 it is
possible to run all daemons except the node daemon as non-root users by
specifying user names and groups at build time. The node daemon
continues to require root privileges to create logical volumes, DRBD
devices, start instances, etc. Cluster commands can be run as root or by
users in a group specified at build time.

Host issues
-----------

For a host on which the Ganeti software has been installed, but not
joined to a cluster, there are no changes to the system.

For a host that has been joined to the cluster, there are very important
changes:

- The host will have its SSH host key replaced with the one of the
  cluster (which is the one the initial node had at the cluster
  creation)
- A new public key will be added to root's ``authorized_keys`` file,
  granting root access to all nodes of the cluster. The private part of
  the key is also distributed to all nodes. Old files are renamed.
- Communication between nodes is encrypted using SSL/TLS. A common key
  and certificate combo is shared between all nodes of the cluster.  At
  this time, no CA is used.
- The Ganeti node daemon will accept RPC requests from any host within
  the cluster with the correct certificate, and the operations it will
  do as a result of these requests are:

  - running commands under the ``/etc/ganeti/hooks`` directory
  - creating DRBD disks between it and the IP it has been told
  - overwrite a defined list of files on the host

As you can see, as soon as a node is joined, it becomes equal to all
other nodes in the cluster, and the security of the cluster is
determined by the weakest node.

Note that only the SSH key will allow other machines to run any command
on this node; the RPC method will run only:

- well defined commands to create, remove, activate logical volumes,
  drbd devices, start/stop instances, etc;
- run well-defined SSH commands on other nodes in the cluster
- scripts under the ``/etc/ganeti/hooks`` directory

It is therefore important to make sure that the contents of the
``/etc/ganeti/hooks`` directory is supervised and only trusted sources
can populate it.

Cluster issues
--------------

As mentioned above, there are multiple ways of communication between
cluster nodes:

- SSH-based, for high-volume traffic like image dumps or for low-level
  command, e.g. restarting the Ganeti node daemon
- RPC communication between master and nodes
- DRBD real-time disk replication traffic

The SSH traffic is protected (after the initial login to a new node) by
the cluster-wide shared SSH key.

RPC communication between the master and nodes is protected using
SSL/TLS encryption. Both the client and the server must have the
cluster-wide shared SSL/TLS certificate and verify it when establishing
the connection by comparing fingerprints. We decided not to use a CA to
simplify the key handling.

The DRBD traffic is not protected by encryption, as DRBD does not
support this. It's therefore recommended to implement host-level
firewalling or to use a separate range of IP addresses for the DRBD
traffic (this is supported in Ganeti through the use of a secondary
interface) which is not routed outside the cluster. DRBD connections are
protected from erroneous connections to other machines (as may happen
due to software issues), and from accepting connections from other
machines, by using a shared secret, exchanged via RPC requests from the
master to the nodes when configuring the device.

Master daemon
-------------

The command-line tools to master daemon communication is done via a
UNIX socket, whose permissions are reset to ``0660`` after listening but
before serving requests. This permission-based protection is documented
and works on Linux, but is not-portable; however, Ganeti doesn't work on
non-Linux system at the moment.

Remote API
----------

Starting with Ganeti 2.0, Remote API traffic is encrypted using SSL/TLS
by default. It supports Basic authentication as per :rfc:`2617`. Users
can be granted different capabilities. Details can be found in the
:ref:`RAPI documentation <rapi-users>`.

Paths for certificate, private key and CA files required for SSL/TLS
will be set at source configure time. Symlinks or command line
parameters may be used to use different files.

Inter-cluster instance moves
----------------------------

To move instances between clusters, different clusters must be able to
communicate with each other over a secure channel. Up to and including
Ganeti 2.1, clusters were self-contained entities and had no knowledge
of other clusters. With Ganeti 2.2, clusters can exchange data if tokens
(an encryption certificate) was exchanged by a trusted third party
before.

KVM Security
------------

When running KVM instances under Ganeti three security models ara
available: "none", "user" and "pool".

Under security model "none" instances run by default as root. This means
that, if an instance gets jail broken, it will be able to own the host
node, and thus the ganeti cluster. This is the default model, and the
only one available before Ganeti 2.1.2.

Under security model "user" an instance is run as the user specified by
the hypervisor parameter "security_domain". This makes it easy to run
all instances as non privileged users, and allows one to manually
allocate specific users to specific instances or sets of instances. If
the specified user doesn't have permissions a jail broken instance will
need some local privilege escalation before being able to take over the
node and the cluster. It's possible though for a jail broken instance to
affect other ones running under the same user.

Under security model "pool" a global cluster-level uid pool is used to
start each instance on the same node under a different user. The uids in
the cluster pool can be set with ``gnt-cluster init`` and ``gnt-cluster
modify``, and must correspond to existing users on all nodes. Ganeti
will then allocate one to each instance, as needed. This way a jail
broken instance won't be able to affect any other. Since the users are
handed out by ganeti in a per-node randomized way, in this mode there is
no way to make sure a particular instance is always run as a certain
user. Use mode "user" for that.

In addition to these precautions, if you want to avoid instances sending
traffic on your node network, you can use an iptables rule such as::

  iptables -A OUTPUT -m owner --uid-owner <uid>[-<uid>] -j LOG \
    --log-prefix "ganeti uid pool user network traffic"
  iptables -A OUTPUT -m owner --uid-owner <uid>[-<uid>] -j DROP

This won't affect regular instance traffic (that comes out of the tapX
allocated to the instance, and can be filtered or subject to appropriate
policy routes) but will stop any user generated traffic that might come
from a jailbroken instance.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
