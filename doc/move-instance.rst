=================================
Moving instances between clusters
=================================

Starting with Ganeti 2.2, instances can be moved between separate Ganeti
clusters using a new tool, ``move-instance``. The tool has a number of
features:

- Moving a single or multiple instances
- Moving instances in parallel (``--parallel`` option)
- Renaming instance (only when moving a single instance)
- SSL certificate verification for RAPI connections

The design of the inter-cluster instances moves is described in detail
in the :doc:`Ganeti 2.2 design document <design-2.2>`. The instance move
tool talks to the Ganeti clusters via RAPI and can run on any machine
which can connect to the cluster's RAPI. Despite their similar name, the
instance move tool should not be confused with the ``gnt-instance move``
command, which is used to move without changes (instead of export/import
plus rename) an instance within the cluster.


Configuring clusters for instance moves
---------------------------------------

To prevent third parties from accessing the instance data, all data
exchanged between the clusters is signed using a secret key, the
"cluster domain secret". It is recommended to assign the same domain
secret to all clusters of the same security domain, so that instances
can be easily moved between them. By checking the signatures, the
destination cluster can be sure the third party (e.g. this tool) didn't
modify the received crypto keys and connection information.

.. highlight:: shell-example

To create a new, random cluster domain secret, run the following command
on the master node::

  $ gnt-cluster renew-crypto --new-cluster-domain-secret


To read and set the cluster domain secret from the contents of a file,
run the following command on the master node::

  $ gnt-cluster renew-crypto --cluster-domain-secret=%/.../ganeti.cds%

More information about the ``renew-crypto`` command can be found in
:manpage:`gnt-cluster(8)`.


Moving instances
----------------

As soon as the clusters share a cluster domain secret, instances can be
moved. The tool usage is as follows::

  $ move-instance %[options]% %source-cluster% %destination-cluster% %instance-name...%

Multiple instances can be moved with one invocation of the instance move
tool, though a few options are only available when moving a single
instance.

The most important options are listed below. Unless specified otherwise,
destination-related options default to the source value (e.g. setting
``--src-rapi-port=1234`` will make ``--dest-rapi-port``'s default 1234).

``--src-rapi-port``/``--dest-rapi-port``
  RAPI server TCP port, defaults to 5080.
``--src-ca-file``/``--dest-ca-file``
  Path to file containing source cluster Certificate Authority (CA) in
  PEM format. For self-signed certificates, this is the certificate
  itself (see more details below in
  :ref:`instance-move-certificates`). For certificates signed by a third
  party CA, the complete chain must be in the file (see documentation
  for :manpage:`SSL_CTX_load_verify_locations(3)`).
``--src-username``/``--dest-username``
  RAPI username, must have write access to cluster.
``--src-password-file``/``--dest-password-file``
  Path to file containing RAPI password (make sure to restrict access to
  this file).
``--dest-instance-name``
  When moving a single instance: Change name of instance on destination
  cluster.
``--dest-primary-node``
  When moving a single instance: Primary node on destination cluster.
``--dest-secondary-node``
  When moving a single instance: Secondary node on destination cluster.
``--dest-disk-template``
  Disk template to use after the move. Can be used to change disk templates.
``--compress``
  Compression mode to use during the instance move. This mode has to be
  supported by both the source and the destination cluster.
``--iallocator``
  Iallocator for creating instance on destination cluster.
``--hypervisor-parameters``/``--backend-parameters``/``--os-parameters``/``--net``
  When moving a single instance: Override instances' parameters.
``--parallel``
  Number of instance moves to run in parallel.
``--verbose``/``--debug``
  Increase output verbosity.

The exit value of the tool is zero if and only if all instance moves
were successful.

.. _instance-move-certificates:

Certificates
------------

If using certificates signed by a CA, then you need to pass the same CA
certificate via both ``--src-ca-file`` and ``dest-ca-file``.

However, if you're using self-signed certificates, this has a few
(security) implications:

- the certificates of both the source and destinations clusters
  (``rapi.pem`` from the Ganeti configuration directory, usually
  ``/var/lib/ganeti/rapi.pem``) must be available to the tool
- by default, the certificates include the private key as well, so
  simply copying them to a third machine means that machine can now
  impersonate both the source and destination clusters RAPI endpoint

It is therefore recommended to copy only the certificate from the
``rapi.pem`` files, and pass these to ``--src-ca-file`` and
``--dest-ca-file`` appropriately.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
