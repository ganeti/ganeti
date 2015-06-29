=============================
Improvements of Node Security
=============================

This document describes an enhancement of Ganeti's security by restricting
the distribution of security-sensitive data to the master and master
candidates only.

Note: In this document, we will use the term 'normal node' for a node that
is neither master nor master-candidate.

.. contents:: :depth: 4

Objective
=========

Up till 2.10, Ganeti distributes security-relevant keys to all nodes,
including nodes that are neither master nor master-candidates. Those
keys are the private and public SSH keys for node communication and the
SSL certficate and private key for RPC communication. Objective of this
design is to limit the set of nodes that can establish ssh and RPC
connections to the master and master candidates.

As pointed out in
`issue 377 <https://code.google.com/p/ganeti/issues/detail?id=377>`_, this
is a security risk. Since all nodes have these keys, compromising
any of those nodes would possibly give an attacker access to all other
machines in the cluster. Reducing the set of nodes that are able to
make ssh and RPC connections to the master and master candidates would
significantly reduce the risk simply because fewer machines would be a
valuable target for attackers.

Note: For bigger installations of Ganeti, it is advisable to run master
candidate nodes as non-vm-capable nodes. This would reduce the attack
surface for the hypervisor exploitation.


Detailed design
===============


Current state and shortcomings
------------------------------

Currently (as of 2.10), all nodes hold the following information:

- the ssh host keys (public and private)
- the ssh root keys (public and private)
- node daemon certificate (the SSL client certificate and its
  corresponding private key)

Concerning ssh, this setup contains the following security issue. Since
all nodes of a cluster can ssh as root into any other cluster node, one
compromised node can harm all other nodes of a cluster.

Regarding the SSL encryption of the RPC communication with the node
daemon, we currently have the following setup. There is only one
certificate which is used as both, client and server certificate. Besides
the SSL client verification, we check if the used client certificate is
the same as the certificate stored on the server.

This means that any node running a node daemon can also act as an RPC
client and use it to issue RPC calls to other cluster nodes. This in
turn means that any compromised node could be used to make RPC calls to
any node (including itself) to gain full control over VMs. This could
be used by an attacker to for example bring down the VMs or exploit bugs
in the virtualization stacks to gain access to the host machines as well.


Proposal concerning SSH host key distribution
---------------------------------------------

We propose the following design regarding the SSH host key handling. The
root keys are untouched by this design.

Each node gets its own ssh private/public key pair, but only the public
keys of the master candidates get added to the ``authorized_keys`` file
of all nodes. This has the advantages, that:

- Only master candidates can ssh into other nodes, thus compromised
  nodes cannot compromise the cluster further.
- One can remove a compromised master candidate from a cluster
  (including removing it's public key from all nodes' ``authorized_keys``
  file) without having to regenerate and distribute new ssh keys for all
  master candidates. (Even though it is be good practice to do that anyway,
  since the compromising of the other master candidates might have taken
  place already.)
- If a (uncompromised) master candidate is offlined to be sent for
  repair due to a hardware failure before Ganeti can remove any keys
  from it (for example when the network adapter of the machine is broken),
  we don't have to worry about the keys being on a machine that is
  physically accessible.

To ensure security while transferring public key information and
updating the ``authorized_keys``, there are several other changes
necessary:

- Any distribution of keys (in this case only public keys) is done via
  SSH and not via RPC. An attacker who has RPC control should not be
  able to get SSH access where he did not have SSH access before
  already.
- The only RPC calls that are made in this context are from the master
  daemon to the node daemon on its own host and noded ensures as much
  as possible that the change to be made does not harm the cluster's
  security boundary.
- The nodes that are potential master candidates keep a list of public
  keys of potential master candidates of the cluster in a separate
  file called ``ganeti_pub_keys`` to keep track of which keys could
  possibly be added ``authorized_keys`` files of the nodes. We come
  to what "potential" means in this case in the next section. The key
  list is only transferred via SSH or written directly by noded. It
  is not stored in the cluster config, because the config is
  distributed via RPC.

The following sections describe in detail which Ganeti commands are
affected by the proposed changes.


RAPI
~~~~

The design goal to limit SSH powers to master candidates conflicts with
the current powers a user of the RAPI interface would have. The
``master_capable`` flag of nodes can be modified via RAPI.
That means, an attacker that has access to the RAPI interface, can make
all non-master-capable nodes master-capable, and then increase the master
candidate pool size till all machines are master candidates (or at least
a particular machine that he is aming for). This means that with RAPI
access and a compromised normal node, one can make this node a master
candidate and then still have the power to compromise the whole cluster.

To mitigate this issue, we propose the following changes:

- Add a flag ``master_capability_rapi_modifiable`` to the cluster
  configuration which indicates whether or not it should be possible
  to modify the ``master_capable`` flag of nodes via RAPI. The flag is
  set to ``False`` by default and can itself only be changed on the
  commandline. In this design doc, we refer to the flag as the
  "rapi flag" from here on.
- Only if the ``master_capabability_rapi_modifiable`` switch is set to
  ``True``, it is possible to modify the master-capability flag of
  nodes.

With this setup, there are the following definitions of "potential
master candidates" depending on the rapi flag:

- If the rapi flag is set to ``True``, all cluster nodes are potential
  master candidates, because as described above, all of them can
  eventually be made master candidates via RAPI and thus security-wise,
  we haven't won anything above the current SSH handling.
- If the rapi flag is set to ``False``, only the master capable nodes
  are considered potential master candidates, as it is not possible to
  make them master candidates via RAPI at all.

Note that when the rapi flag is changed, the state of the
``ganeti_pub_keys`` file on all nodes  has to be updated accordingly.
This should be done in the client script ``gnt_cluster`` before the
RPC call to update the configuration is made, because this way, if
someone would try to perform that RPC call on master to trick it into
thinking that the flag is enabled, this would not help as the content of
the ``ganeti_pub_keys`` file is a crucial part in the design of the
distribution of the SSH keys.

Note: One could think of always allowing to disable the master-capability
via RAPI and just restrict the enabling of it, thus making it possible
to RAPI-"freeze" the nodes' master-capability state once it disabled.
However, we think these are rather confusing semantics of the involved
flags and thus we go with proposed design.

Note that this change will break RAPI compatibility, at least if the
rapi flag is not explicitely set to ``True``. We made this choice to
have the more secure option as default, because otherwise it is
unlikely to be widely used.


Cluster initialization
~~~~~~~~~~~~~~~~~~~~~~

On cluster initialization, the following steps are taken in
bootstrap.py:

- A public/private key pair is generated (as before), but only used
  by the first (and thus master) node. In particular, the private key
  never leaves the node.
- A mapping of node UUIDs to public SSH keys is created and stored
  as text file in ``/var/lib/ganeti/ganeti_pub_keys`` only accessible
  by root (permissions 0600). The master node's uuid and its public
  key is added as first entry. The format of the file is one
  line per node, each line composed as ``node_uuid ssh_key``.
- The node's public key is added to it's own ``authorized_keys`` file.


(Re-)Adding nodes to a cluster
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

According to :doc:`design-node-add`, Ganeti transfers the ssh keys to
every node that gets added to the cluster.

Adding a new node will require the following steps.

In gnt_node.py:

- On the new node, a new public/private SSH key pair is generated.
- The public key of the new node is fetched (via SSH) to the master
  node and if it is a potential master candidate (see definition above),
  it is added to the ``ganeti_pub_keys`` list on the master node.
- The public keys of all current master candidates are added to the
  new node's ``authorized_keys`` file (also via SSH).

In LUNodeAdd in cmdlib/node.py:

- The LUNodeAdd determines whether or not the new node is a master
  candidate and in any case updates the cluster's configuration with the
  new nodes information. (This is not changed by the proposed design.)
- If the new node is a master candidate, we make an RPC call to the node
  daemon of the master node to add the new node's public key to all
  nodes' ``authorized_keys`` files. The implementation of this RPC call
  has to be extra careful as described in the next steps, because
  compromised RPC security should not compromise SSH security.

RPC call execution in noded (on master node):

- Check that the public key of the new node is in the
  ``ganeti_pub_keys`` file of the master node to make sure that no keys
  of nodes outside the Ganeti cluster and no keys that are not potential
  master candidates gain SSH access in the cluster.
- Via SSH, transfer the new node's public key to all nodes (including
  the new node) and add it to their ``authorized_keys`` file.
- The ``ganeti_pub_keys`` file is transferred via SSH to all
  potential master candidates nodes except the master node
  (including the new one).

In case of readding a node that used to be in the cluster before,
handling of the SSH keys would basically be the same, in particular also
a new SSH key pair is generated for the node, because we cannot be sure
that the old key pair has not been compromised while the node was
offlined. Note that for reasons of data hygiene, a node's
``ganeti_pub_keys`` file is cleared before the node is readded.
Also, Ganeti attempts to remove any Ganeti keys from the ``authorized_keys``
file before the node is readded. However, since Ganeti does not keep a list
of all keys ever used in the cluster, this applies only to keys which
are currently used in the cluster. Note that Ganeti won't touch any keys
that were added to the ``authorized_keys`` by other systems than Ganeti.


Pro- and demoting a node to/from master candidate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If the role of a node is changed from 'normal' to 'master_candidate',
the procedure is the same as for adding nodes from the step "In
LUNodeAdd ..." on.

If a node gets demoted to 'normal', the master daemon makes a similar
RPC call to the master node's node daemon as for adding a node.

In the RPC call, noded will perform the following steps:

- Check that the public key of the node to be demoted is indeed in the
  ``ganeti_pub_keys`` file to avoid deleting ssh keys of machines that
  don't belong to the cluster (and thus potentially lock out the
  administrator).
- Via SSH, remove the key from all node's ``authorized_keys`` files.

This affected the behavior of the following commands:

::
  gnt-node modify --master-candidate=yes
  gnt-node modify --master-candidate=no [--auto-promote]

If the node has been master candidate already before the command to promote
it was issued, Ganeti does not do anything.

Note that when you demote a node from master candidate to normal node, another
master-capable and normal node will be promoted to master candidate. For this
newly promoted node, the same changes apply as if it was explicitely promoted.

The same behavior should be ensured for the corresponding rapi command.


Offlining and onlining a node
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When offlining a node, it immediately loses its role as master or master
candidate as well. When it is onlined again, it will become master
candidate again if it was so before. The handling of the keys should be done
in the same way as when the node is explicitely promoted or demoted to or from
master candidate. See the previous section for details.

This affects the command:

::
  gnt-node modify --offline=yes
  gnt-node modify --offline=no [--auto-promote]

For offlining, the removal of the keys is particularly important, as the
detection of a compromised node might be the very reason for the offlining.
Of course we cannot guarantee that removal of the key is always successful,
because the node might not be reachable anymore. Even though it is a
best-effort operation, it is still an improvement over the status quo,
because currently Ganeti does not even try to remove any keys.

The same behavior should be ensured for the corresponding rapi command.


Cluster verify
~~~~~~~~~~~~~~

So far, ``gnt-cluster verify`` checks the SSH connectivity of all nodes to
all other nodes. We propose to replace this by the following checks:

- For all master candidates, we check if they can connect any other node
  in the cluster (other master candidates and normal nodes).
- We check if the ``ganeti_pub_keys`` file contains keys of nodes that
  are no longer in the cluster or that are not potential master
  candidates.
- For all normal nodes, we check if their key does not appear in other
  node's ``authorized_keys``. For now, we will only emit a warning
  rather than an error if this check fails, because Ganeti might be
  run in a setup where Ganeti is not the only system manipulating the
  SSH keys.


Upgrades
~~~~~~~~

When upgrading from a version that has the previous SSH setup to the one
proposed in this design, the upgrade procedure has to involve the
following steps in the post-upgrade hook:

- For all nodes, new SSH key pairs are generated.
- All nodes and their public keys are added to the ``ganeti_pub_keys``
  file and the file is copied to all nodes.
- All keys of master candidate nodes are added to the
  ``authorized_keys`` files of all other nodes.

Since this upgrade significantly changes the configuration of the
clusters' nodes, we will add a note to the UPGRADE notes to make the
administrator aware of this fact (in case he intends to enable access
from normal nodes to master candidates for other reasons than Ganeti
uses the machines).

Also, in any operation where Ganeti creates new SSH keys, the old keys
will be backed up and not simply overridden.


Downgrades
~~~~~~~~~~

These downgrading steps will be implemtented from 2.13 to 2.12:

- The master node's private/public key pair will be distributed to all
  nodes (via SSH) and the individual SSH keys will be backed up.
- The obsolete individual ssh keys will be removed from all nodes'
  ``authorized_keys`` file.


Renew-Crypto
~~~~~~~~~~~~

The ``gnt-cluster renew-crypto`` command will be extended by a new
option ``--new-ssh-keys``, which will renew all SSH keys on all nodes
and rebuild the ``authorized_keys`` files and the ``ganeti_pub_keys``
files according to the previous sections. This operation will be
performed considering the already stated security considerations, for
example minimizing RPC calls, distribution of keys via SSH only etc.


Compliance to --no-ssh-init and --no-node-setup
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

With this design, Ganeti will do more manipulations of SSH keys and
``authorized_keys`` files than before. If this is not feasible in
a Ganeti environment, the administrator has the option to prevent
Ganeti from performing any manipulations on the SSH setup of the nodes.
The options for doing so, are ``--no-ssh-init`` for ``gnt-cluster
init``, and ``--no-node-setup`` for ``gnt-node add``. Note that
these options already existed before the implementation of this
design, we just confirm that they will be complied to with the
new design as well.


Proposal regarding node daemon certificates
-------------------------------------------

Regarding the node daemon certificates, we propose the following changes
in the design.

- Instead of using the same certificate for all nodes as both, server
  and client certificate, we generate a common server certificate (and
  the corresponding private key) for all nodes and a different client
  certificate (and the corresponding private key) for each node. The
  server certificate will be self-signed. The client certficate will
  be signed by the server certificate. The client certificates will
  use the node UUID as serial number to ensure uniqueness within the
  cluster. They will use the host's hostname as the certificate
  common name (CN).
- In addition, we store a mapping of
  (node UUID, client certificate digest) in the cluster's configuration
  and ssconf for hosts that are master or master candidate.
  The client certificate digest is a hash of the client certificate.
  We suggest a 'sha1' hash here. We will call this mapping 'candidate map'
  from here on.
- The node daemon will be modified in a way that on an incoming RPC
  request, it first performs a client verification (same as before) to
  ensure that the requesting host is indeed the holder of the
  corresponding private key. Additionally, it compares the digest of
  the certificate of the incoming request to the respective entry of
  the candidate map. If the digest does not match the entry of the host
  in the mapping or is not included in the mapping at all, the SSL
  connection is refused.

This design has the following advantages:

- A compromised normal node cannot issue RPC calls, because it will
  not be in the candidate map. (See the ``Drawbacks`` section regarding
  an indirect way of achieving this though.)
- A compromised master candidate would be able to issue RPC requests,
  but on detection of its compromised state, it can be removed from the
  cluster (and thus from the candidate map) without the need for
  redistribution of any certificates, because the other master candidates
  can continue using their own certificates. However, it is best
  practice to issue a complete key renewal even in this case, unless one
  can ensure no actions compromising other nodes have not already been
  carried out.
- A compromised node would not be able to use the other (possibly master
  candidate) nodes' information from the candidate map to issue RPCs,
  because the config just stores the digests and not the certificate
  itself.
- A compromised node would be able to obtain another node's certificate
  by waiting for incoming RPCs from this other node. However, the node
  cannot use the certificate to issue RPC calls, because the SSL client
  verification would require the node to hold the corresponding private
  key as well.

Drawbacks of this design:

- Complexity of node and certificate management will be increased (see
  following sections for details).
- If the candidate map is not distributed fast enough to all nodes after
  an update of the configuration, it might be possible to issue RPC calls
  from a compromised master candidate node that has been removed
  from the Ganeti cluster already. However, this is still a better
  situation than before and an inherent problem when one wants to
  distinguish between master candidates and normal nodes.
- A compromised master candidate would still be able to issue RPC calls,
  if it uses ssh to retrieve another master candidate's client
  certificate and the corresponding private SSL key. This is an issue
  even with the first part of the improved handling of ssh keys in this
  design (limiting ssh keys to master candidates), but it will be
  eliminated with the second part of the design (separate ssh keys for
  each master candidate).
- Even though this proposal is an improvement towards the previous
  situation in Ganeti, it still does not use the full power of SSL. For
  further improvements, see Section "Related and future work".
- Signing the client certificates with the server certificate will
  increase the complexity of the renew-crypto, as a renewal of the
  server certificates requires the renewal (and signing) of all client
  certificates as well.

Alternative proposals:

- The initial version of this document described a setup where the
  client certificates were also self-signed. This led to a serious
  problem (Issue 1094), which would only have been solvable by
  distributing all client certificates to all nodes and load them
  as trusted CAs. As this would have resulted in having to restart
  noded on all nodes every time a node is added, removed, demoted
  or promoted, this was not feasible and we switched to client
  certficates which are signed by the server certificate.
- Instead of generating a client certificate per node, one could think
  of just generating two different client certificates, one for normal
  nodes and one for master candidates. Noded could then just check if
  the requesting node has the master candidate certificate. Drawback of
  this proposal is that once one master candidate gets compromised, all
  master candidates would need to get a new certificate even if the
  compromised master candidate had not yet fetched the certificates
  from the other master candidates via ssh.
- In addition to our main proposal, one could think of including a
  piece of data (for example the node's host name or UUID) in the RPC
  call which is encrypted with the requesting node's private key. The
  node daemon could check if the datum can be decrypted using the node's
  certificate. However, this would ensure similar functionality as
  SSL's built-in client verification and add significant complexity
  to Ganeti's RPC protocol.

In the following sections, we describe how our design affects various
Ganeti operations.


Cluster initialization
~~~~~~~~~~~~~~~~~~~~~~

On cluster initialization, so far only the node daemon certificate was
created. With our design, two certificates (and corresponding keys)
need to be created, a server certificate to be distributed to all nodes
and a client certificate only to be used by this particular node. In the
following, we use the term node daemon certificate for the server
certficate only.

In the cluster configuration, the candidate map is created. It is
populated with the respective entry for the master node. It is also
written to ssconf.


(Re-)Adding nodes
~~~~~~~~~~~~~~~~~

When a node is added, the server certificate is copied to the node (as
before). Additionally, a new client certificate (and the corresponding
private key) is created on the new node to be used only by the new node
as client certifcate.

If the new node is a master candidate, the candidate map is extended by
the new node's data. As before, the updated configuration is distributed
to all nodes (as complete configuration on the master candidates and
ssconf on all nodes). Note that distribution of the configuration after
adding a node is already implemented, since all nodes hold the list of
nodes in the cluster in ssconf anyway.

If the configuration for whatever reason already holds an entry for this
node, it will be overriden.

When readding a node, the procedure is the same as for adding a node.


Promotion and demotion of master candidates
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When a normal node gets promoted to be master candidate, an entry to the
candidate map has to be added and the updated configuration has to be
distributed to all nodes. If there was already an entry for the node,
we override it.

On demotion of a master candidate, the node's entry in the candidate map
gets removed and the updated configuration gets redistibuted.

The same procedure applied to onlining and offlining master candidates.


Cluster verify
~~~~~~~~~~~~~~

Cluster verify will be extended by the following checks:

- Whether each entry in the candidate map indeed corresponds to a master
  candidate.
- Whether the master candidate's certificate digest match their entry
  in the candidate map.
- Whether no node tries to use the certificate of another node. In
  particular, it is important to check that no normal node tries to
  use the certificate of a master candidate.
- Whether there are still self-signed client certificates in use (from
  a pre 2.12.4 Ganeti version).


Crypto renewal
~~~~~~~~~~~~~~

Currently, when the cluster's cryptographic tokens are renewed using the
``gnt-cluster renew-crypto`` command the node daemon certificate is
renewed (among others). Option ``--new-cluster-certificate`` renews the
node daemon certificate only.

By adding an option ``--new-node-certificates`` we offer to renew the
client certificate. Whenever the client certificates are renewed, the
candidate map has to be updated and redistributed.

If for whatever reason, the candidate map becomes inconsistent, for example
due inconsistent updating after a demotion or offlining), the user can use
this option to renew the client certificates and update the candidate
certificate map.

Note that renewing the server certificate requires all client certificates
being renewed and signed by the new server certificate, because
otherwise their signature can not be verified by the server who only has
the new server certificate then.

As there was a different design in place in Ganeti 2.12.4 and previous
versions, we have to ensure that renew-crypto works on pre 2.12 versions and
2.12.1-4. Users that got hit by Issue 1094 will be encouraged to run
renew-crypto at least once after switching to 2.12.5. Those who did not
encounter this bug yet, will still get nagged friendly by gnt-cluster
verify.


Further considerations
----------------------

Watcher
~~~~~~~

The watcher is a script that is run on all nodes in regular intervals. The
changes proposed in this design will not affect the watcher's implementation,
because it behaves differently on the master than on non-master nodes.

Only on the master, it issues query calls which would require a client
certificate of a node in the candidate mapping. This is the case for the
master node. On non-master node, it's only external communication is done via
the ConfD protocol, which uses the hmac key, which is present on all nodes.
Besides that, the watcher does not make any ssh connections, and thus is
not affected by the changes in ssh key handling either.


Other Keys and Daemons
~~~~~~~~~~~~~~~~~~~~~~

Ganeti handles a couple of other keys/certificates that have not been mentioned
in this design so far. Also, other daemons than the ones mentioned so far
perform intra-cluster communication. Neither the keys nor the daemons will
be affected by this design for several reasons:

- The hmac key used by ConfD (see :doc:`design-2.1`): the hmac key is still
  distributed to all nodes, because it was designed to be used for
  communicating with ConfD, which should be possible from all nodes.
  For example, the monitoring daemon which runs on all nodes uses it to
  retrieve information from ConfD. However, since communication with ConfD
  is read-only, a compromised node holding the hmac key does not enable an
  attacker to change the cluster's state.

- The WConfD daemon writes the configuration to all master candidates
  via RPC. Since it only runs on the master node, it's ability to run
  RPC requests is maintained with this design.

- The rapi SSL key certificate and rapi user/password file 'rapi_users' is
  already only copied to the master candidates (see :doc:`design-2.1`,
  Section ``Redistribute Config``).

- The spice certificates are still distributed to all nodes, since it should
  be possible to use spice to access VMs on any cluster node.

- The cluster domain secret is used for inter-cluster instance moves.
  Since instances can be moved from any normal node of the source cluster to
  any normal node of the destination cluster, the presence of this
  secret on all nodes is necessary.


Related and Future Work
~~~~~~~~~~~~~~~~~~~~~~~

There a couple of suggestions on how to improve the SSL setup even more.
As a trade-off wrt to complexity and implementation effort, we did not
implement them yet (as of version 2.11) but describe them here for
future reference.

- The server certificate is currently self-signed and the client certificates
  are signed by the server certificate. It would increase the security if they
  were signed by a common CA. There is already a design doc for a Ganeti CA
  which was suggested in a different context (related to import/export).
  This would also be a benefit for the RPC calls. See design doc
  :doc:`design-impexp2` for more information. Implementing a CA is rather
  complex, because it would mean also to support renewing the CA certificate and
  providing and supporting infrastructure to revoke compromised certificates.
- An extension of the previous suggestion would be to even enable the
  system administrator to use an external CA. Especially in bigger
  setups, where already an SSL infrastructure exists, it would be useful
  if Ganeti can simply be integrated with it, rather than forcing the
  user to use the Ganeti CA.
- Ganeti RPC calls are currently done without checking if the hostname
  of the node complies with the common name of the certificate. This
  might be a desirable feature, but would increase the effort when a
  node is renamed.
- The typical use case for SSL is to have one certificate per node
  rather than one shared certificate (Ganeti's noded server certificate)
  and a client certificate. One could change the design in a way that
  only one certificate per node is used, but this would require a common
  CA so that the validity of the certificate can be established by every
  node in the cluster.
- With the proposed design, the serial numbers of the client
  certificates are set to the node UUIDs. This is technically also not
  complying to how SSL is supposed to be used, as the serial numbers
  should reflect the enumeration of certificates created by the CA. Once
  a CA is implemented, it might be reasonable to change this
  accordingly. The implementation of the proposed design also has the
  drawback of the serial number not changing even if the certificate is
  replaced by a new one (for example when calling ``gnt-cluster renew-
  crypt``), which also does not comply to way SSL was designed to be
  used.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
