Security in Ganeti
~~~~~~~~~~~~~~~~~~

Ganeti was developed to run on internal, trusted systems. As such, the
security model is all-or-nothing.

All the Ganeti code runs as root, because all the operations that Ganeti
is doing require privileges: creating logical volumes, drbd devices,
starting instances, etc. Running as root does not mean setuid, but that
you need to be root to run the cluster commands.

Host issues
-----------

For a host on which the Ganeti software has been installed, but not joined to a
cluster, there are no changes to the system.

For a host that has been joined to the cluster, there are very important
changes:
  - The host will have its SSH host key replaced with the one of the
    cluster (which is the one the initial node had at the cluster
    creation)
  - A new public key will be added to root's authorized_keys file, granting
    root access to all nodes of the cluster. The private part of the key
    is also distributed to all nodes. Old files are renamed.
  - Communication between nodes is encrypted using SSL/TLS. A common
    key and certificate combo is shared between all nodes of the cluster.
    At this time, no CA is used.
  - The Ganeti node daemon will accept RPC requests from any host within the
    cluster with the correct certificate, and the operations it will do as a
    result of these requests are:
      - running commands under the /etc/ganeti/hooks directory
      - creating DRBD disks between it and the IP it has been told
      - overwrite a defined list of files on the host

As you can see, as soon as a node is joined, it becomes equal to all
other nodes in the cluster, and the security of the cluster is
determined by the weakest node.

Note that only the SSH key will allow other machines to run random
commands on this node; the RPC method will run only:
  - well defined commands to create, remove, activate logical volumes,
    drbd devices, start/stop instances, etc;
  - run SSH commands on other nodes in the cluster, again well-defined
  - scripts under the /etc/ganeti/hooks directory

It is therefore important to make sure that the contents of the
/etc/ganeti/hooks directory is supervised and only trusted sources can
populate it.

Cluster issues
--------------

As told above, there are multiple ways of communication between cluster
nodes:
  - SSH-based, for high-volume traffic like image dumps or for low-level
    command, e.g. restarting the Ganeti node daemon
  - RPC communication between master and nodes
  - DRBD real-time disk replication traffic

The SSH traffic is protected (after the initial login to a new node) by
the cluster-wide shared SSH key.

RPC communication between the master and nodes is protected using SSL/TLS
encryption. Both the client and the server must have the cluster-widely
shared SSL/TLS certificate and verify it when establishing the connection
by comparing fingerprints. We decided not to use a CA to simplify the
key handling.

The DRBD traffic is not protected by encryption. DRBD does not support
traffic encryption. It's therefore recommended to implement host-level
firewalling or to use a separate range of IP addresses for the DRBD
traffic (this is supported in Ganeti) which is not routed outside the
cluster. DRBD connections are protected from connecting to random other
machines by using a shared secret exchanged via RPC requests when
starting the device.

Remote API
----------

Starting with Ganeti 2.0, Remote API traffic is encrypted using SSL/TLS by
default. It supports Basic authentication as per RFC2617.

Paths for certificate, private key and CA files required for SSL/TLS will
be set at source configure time. Symlinks or command line parameters may
be used to use different files.
