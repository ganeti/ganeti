========================
Cluster Keys Replacement
========================

Ganeti uses both SSL and SSH keys, and actively modifies the SSH keys
on the nodes.  As result, in order to replace these keys, a few extra
steps need to be followed.

For an example when this could be needed, see the thread at
`Regenerating SSL and SSH keys after the security bug in Debian's
OpenSSL
<http://groups.google.com/group/ganeti/browse_thread/thread/30cc95102dc2123e>`_.

Ganeti uses OpenSSL for encryption on the RPC layer and SSH for
executing commands. The SSL certificate is automatically generated
when the cluster is initialized and it's copied to added nodes
automatically together with the master's SSH host key.

Note that paths below may vary depending on your distribution. In
general, modifications should be done on the master node and then
distributed to all nodes of a cluster (possibly using a pendrive - but
don't forget to use "shred" to remove files securely afterwards).

Replacing SSL keys
==================

The cluster-wide SSL key is stored in ``/var/lib/ganeti/server.pem``.
Besides that, since Ganeti 2.11, each node has an individual node
SSL key, which is stored in ``/var/lib/ganeti/client.pem``. This
client certificate is signed by the cluster-wide SSL certficate.

To renew the individual node certificates, run this command::

  gnt-cluster renew-crypto --new-node-certificates

Run the following command to generate a new cluster-wide certificate::

  gnt-cluster renew-crypto --new-cluster-certificate

Note that this triggers both, the renewal of the cluster certificate
as well as the renewal of the individual node certificate. The reason
for this is that the node certificates are signed by the cluster
certificate and thus they need to be renewed and signed as soon as
the changes certificate changes. Therefore, the command above is
equivalent to::

  gnt-cluster renew-crypto --new-cluster-certificate --new-node-certificates

On older versions, which don't have this command, use this instead::

  chmod 0600 /var/lib/ganeti/server.pem &&
  openssl req -new -newkey rsa:1024 -days 1825 -nodes \
   -x509 -keyout /var/lib/ganeti/server.pem \
   -out /var/lib/ganeti/server.pem -batch &&
  chmod 0400 /var/lib/ganeti/server.pem &&
  /etc/init.d/ganeti restart

  gnt-cluster copyfile /var/lib/ganeti/server.pem

  gnt-cluster command /etc/init.d/ganeti restart

Note that older versions don't have individual node certificates and thus
one does not have to handle the creation and distribution of them.


Replacing SSH keys
==================

There are two sets of SSH keys in the cluster: the host keys (both DSA
and RSA, though Ganeti only uses the RSA one) and the root's DSA key
(Ganeti uses DSA for historically reasons, in the future RSA will be
used).

host keys
+++++++++

These are the files named ``/etc/ssh/ssh_host_*``. You need to
manually recreate them; it's possibly that the startup script of
OpenSSH will generate them if they don't exist, or that the package
system regenerates them.

Also make sure to copy the master's SSH host keys to all other nodes.

cluster public key file
+++++++++++++++++++++++

The new public rsa host key created in the previous step must be added
in two places:

#. known hosts file, ``/var/lib/ganeti/known_hosts``
#. cluster configuration file, ``/var/lib/ganeti/config.data``

Edit these two files and update them with newly generated SSH host key
(in the previous step, take it from the
``/etc/ssh/ssh_host_rsa_key.pub``).

For the ``config.data`` file, please look for an entry named
``rsahostkeypub`` and replace the value for it with the contents of
the ``.pub`` file. For the ``known_hosts`` file, you need to replace
the old key with the new one on each line (for each host).

root's key
++++++++++

These are the files named ``~root/.ssh/id_dsa*``.

Run this command to rebuild them::

  ssh-keygen -t dsa -f ~root/.ssh/id_dsa -q -N ""

root's ``authorized_keys``
++++++++++++++++++++++++++

This is the file named ``~root/.ssh/authorized_keys``.

Edit file and update it with the newly generated root key, from the
``id_dsa.pub`` file generated in the previous step.

Finish
======

In the end, the files mentioned above should be identical for all
nodes in a cluster. Also do not forget to run ``gnt-cluster verify``.
