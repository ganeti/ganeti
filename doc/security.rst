Security in Ganeti
==================

Documents Ganeti version 2.16

Ganeti was developed to run on internal, trusted systems. As such, the
security model is all-or-nothing.

Up to version 2.3 all Ganeti code ran as root. Since version 2.4 it is
possible to run all daemons except the node daemon and the monitoring daemon
as non-root users by specifying user names and groups at build time.
The node daemon continues to require root privileges to create logical volumes,
DRBD devices, start instances, etc. Cluster commands can be run as root or by
users in a group specified at build time. The monitoring daemon requires root
privileges in order to be able to access and present information that are only
avilable to root (such as the output of the ``xm`` command of Xen).

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
- The Ganeti node daemon will accept RPC requests from any host that is
  master candidate within the cluster, and the operations it will
  do as a result of these requests are:

  - running commands under the ``/etc/ganeti/hooks`` directory
  - creating DRBD disks between it and the IP it has been told
  - overwrite a defined list of files on the host

As you can see, as soon as a node is joined, it becomes equal to all
other nodes in the cluster wrt to SSH and equal to all non-master
candidate nodes wrt to RPC, and the security of the cluster is
determined by the weakest node.

Note that only the SSH key will allow other machines to run any command
on this node; the RPC method will run only:

- well defined commands to create, remove, activate logical volumes,
  drbd devices, start/stop instances, etc;
- run well-defined SSH commands on other nodes in the cluster
- scripts under the ``/etc/ganeti/hooks`` directory
- scripts under the ``/etc/ganeti/restricted-commands`` directory, if
  this feature has been enabled at build time (see below)

It is therefore important to make sure that the contents of the
``/etc/ganeti/hooks`` and ``/etc/ganeti/restricted-commands``
directories are supervised and only trusted sources can populate them.

Restricted commands
~~~~~~~~~~~~~~~~~~~

The restricted commands feature is new in Ganeti 2.7. It enables the
administrator to run any commands in the
``/etc/ganeti/restricted-commands`` directory, if the feature has been
enabled at build time, subject to the following restrictions:

- No parameters may be passed
- No absolute or relative path may be passed, only a filename
- The ``/etc/ganeti/restricted-commands`` directory must
  be owned by root:root and have mode 0755 or stricter
- Executables must be regular files or symlinks, and must be executable
  by root:root

Note that it's not possible to list the contents of the directory, and
there is an intentional delay when trying to execute a non-existing
command (to slow-down dictionary attacks).

Since for Ganeti itself this functionality is not needed, and is only
provided as a way to help administrate or recover nodes, it is a local
site decision whether to enable or not the restricted commands feature.

By default, this feature is disabled.


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
SSL/TLS encryption. The server must have must have the cluster-wide
shared SSL/TLS certificate. When acting as a client, the nodes use an
individual SSL/TLS certificate. On incoming requests, the server checks
whether the client's certificate is that of a master candidate by
verifying its finterprint to a list of known master candidate
certificates. We decided not to use a CA (yet) to simplify the key
handling.

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

Luxi daemon
-----------

The ``luxid`` daemon (automatically enabled if ``confd`` is enabled at
build time) serves local (UNIX socket) queries about the run-time
configuration. Answering these means talking to other cluster nodes,
exactly as ``masterd`` does. See the notes for ``masterd`` regarding
permission-based protection.

Conf daemon
-----------

In Ganeti 2.8, the ``confd`` daemon (if enabled at build time), serves
network-originated queries about parts of the static cluster
configuration.

If Ganeti is not configured (at build time) to use separate users,
``confd`` has access to all Ganeti related files (including internal RPC
SSL certificates). This makes it a bit more sensitive to bugs (a remote
attacker could get direct access to the intra-cluster RPC), so to harden
security it's recommended to:

- disable confd at build time if it (and ``luxid``) is not needed in
  your setup.
- configure Ganeti (at build time) to use separate users, so that the
  confd daemon doesn't also have access to the server SSL/TLS
  certificates.
- add firewall rules to protect the ``confd`` port or bind it to a
  trusted address. Make sure that all nodes can access the daemon, as
  the monitoring daemon requires it.

Monitoring daemon
-----------------

The monitoring daemon provides information about the status and the
performance of the cluster over HTTP.
It is currently unencrypted and non-authenticated, therefore it is strongly
advised to set proper firewalling rules to prevent unwanted access.

The monitoring daemon runs as root, because it needs to be able to access
privileged information (such as the state of the instances as provided by
the Xen hypervisor). Nevertheless, the security implications are mitigated
by the fact that the agent only provides reporting functionalities,
without the ability to actually modify the state of the cluster.

Remote API
----------

Starting with Ganeti 2.0, Remote API traffic is encrypted using SSL/TLS
by default. It supports Basic authentication as per :rfc:`2617`. Users
can be granted different capabilities. Details can be found in the
:ref:`RAPI documentation <rapi-users>`.

Paths for certificate, private key and CA files required for SSL/TLS
will be set at source configure time. Symlinks or command line
parameters may be used to use different files.

The RAPI binds to all interfaces by default, and allows read-only
requests without the need for authentication. In the case that one of
the interfaces RAPI binds to is publicly exposed, this will allow
anyone in the world to read the state of the cluster, divulging
potentially useful data such as the names of instances, their IP
addresses, etc. Since the RAPI daemon resides on the master node as
well, DoS attacks can result in Ganeti outages or issues with instances
located on the master node.

We recommend that you reduce the attack surface by either placing RAPI
in an environment where you can control access to it, or should you
need to expose it publicly, use various RAPI daemon options to lock
functionality down to only what you need. RAPI daemon options are best
added to ``/etc/default/ganeti``, the ``RAPI_ARGS`` variable. Some
examples of situations where you might want to expose the RAPI are
cross-cluster instance moves, which can be done only via the RAPI.

If you do not use RAPI at all, we recommend that you lock it down by
binding it to the loopback interface. This can be done by passing the
``-b 127.0.0.1`` parameter to the RAPI daemon. Preventing the RAPI
from starting or making it unreachable on the master node is not
recommended, as the watcher performs health checks and will attempt to
restart the daemon repeatedly.

If you intend to use the RAPI and to expose it to the public, make sure
to use the ``--require-authentication`` flag, disabling anonymous HTTP
requests.

Ganeti currently cannot protect users adequately from DoS attacks based
on client-side HTTPS parameter renegotiation due to the Python OpenSSL
library lacking necessary features. To protect yourself from these, the
use of a HTTPS proxy handling this correctly is needed (e.g. nginx).
Useful options for setting RAPI up for cooperation with the proxy are:

- ``-p PORT`` for allowing the default RAPI port to be used by the
  proxy
- ``--no-ssl`` to disable SSL as it will be handled by the proxy anyway

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
