=======================================
Design for a X509 Certificate Authority
=======================================

.. contents:: :depth: 4

Current state and shortcomings
------------------------------

Import/export in Ganeti have a need for many unique X509 certificates.
So far these were all self-signed, but with the :doc:`new design for
import/export <design-impexp2>` they need to be signed by a Certificate
Authority (CA).


Proposed changes
----------------

The plan is to implement a simple CA in Ganeti.

Interacting with an external CA is too difficult or impossible for
automated processes like exporting instances, so each Ganeti cluster
will have its own CA. The public key will be stored in
``…/lib/ganeti/ca/cert.pem``, the private key (only readable by the
master daemon) in ``…/lib/ganeti/ca/key.pem``.

Similar to the RAPI certificate, a new CA certificate can be installed
using the ``gnt-cluster renew-crypto`` command. Such a CA could be an
intermediate of a third-party CA. By default a self-signed CA is
generated and used.

.. _x509-ca-serial:

Each certificate signed by the CA is required to have a unique serial
number. The serial number is stored in the file
``…/lib/ganeti/ca/serial``, replicated to all master candidates and
never reset, even when a new CA is installed.

The threat model is expected to be the same as with self-signed
certificates. To reinforce this, all certificates signed by the CA must
be valid for less than one week (168 hours).

Implementing support for Certificate Revocation Lists (CRL) using
OpenSSL is non-trivial. Lighttpd doesn't support them at all and
`apparently never will in version 1.4.x
<http://redmine.lighttpd.net/issues/2278>`_. Some CRL-related parts have
only been added in the most recent version of pyOpenSSL (0.11). Instead
of a CRL, Ganeti will gain a new cluster configuration property defining
the minimum accepted serial number. In case of a lost or compromised
private key this property can be set to the most recently generated
serial number.

While possible to implement in the future, other X509 certificates used
by the cluster (e.g. RAPI or inter-node communication) will not be
automatically signed by the per-cluster CA.

The ``commonName`` attribute of signed certificates must be set to the
the cluster name or the name of a node in the cluster.


Software requirements
---------------------

- pyOpenSSL 0.10 or above (lower versions can't set the X509v3 extension
  ``subjectKeyIdentifier`` recommended for certificate authority
  certificates by :rfc:`3280`, section 4.2.1.2)


Code samples
------------

Generating X509 CA using pyOpenSSL
++++++++++++++++++++++++++++++++++

.. highlight:: python

The following code sample shows how to generate a CA certificate using
pyOpenSSL::

  key = OpenSSL.crypto.PKey()
  key.generate_key(OpenSSL.crypto.TYPE_RSA, 2048)

  ca = OpenSSL.crypto.X509()
  ca.set_version(3)
  ca.set_serial_number(1)
  ca.get_subject().CN = "ca.example.com"
  ca.gmtime_adj_notBefore(0)
  ca.gmtime_adj_notAfter(24 * 60 * 60)
  ca.set_issuer(ca.get_subject())
  ca.set_pubkey(key)
  ca.add_extensions([
    OpenSSL.crypto.X509Extension("basicConstraints", True,
                                 "CA:TRUE, pathlen:0"),
    OpenSSL.crypto.X509Extension("keyUsage", True,
                                 "keyCertSign, cRLSign"),
    OpenSSL.crypto.X509Extension("subjectKeyIdentifier", False, "hash",
                                 subject=ca),
    ])
  ca.sign(key, "sha1")


Signing X509 certificate using CA
+++++++++++++++++++++++++++++++++

.. highlight:: python

The following code sample shows how to sign an X509 certificate using a
CA::

  ca_cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                            "ca.pem")
  ca_key = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM,
                                          "ca.pem")

  key = OpenSSL.crypto.PKey()
  key.generate_key(OpenSSL.crypto.TYPE_RSA, 2048)

  cert = OpenSSL.crypto.X509()
  cert.get_subject().CN = "node1.example.com"
  cert.set_serial_number(1)
  cert.gmtime_adj_notBefore(0)
  cert.gmtime_adj_notAfter(24 * 60 * 60)
  cert.set_issuer(ca_cert.get_subject())
  cert.set_pubkey(key)
  cert.sign(ca_key, "sha1")


How to generate Certificate Signing Request
+++++++++++++++++++++++++++++++++++++++++++

.. highlight:: python

The following code sample shows how to generate an X509 Certificate
Request (CSR)::

  key = OpenSSL.crypto.PKey()
  key.generate_key(OpenSSL.crypto.TYPE_RSA, 2048)

  req = OpenSSL.crypto.X509Req()
  req.get_subject().CN = "node1.example.com"
  req.set_pubkey(key)
  req.sign(key, "sha1")

  # Write private key
  print OpenSSL.crypto.dump_privatekey(OpenSSL.crypto.FILETYPE_PEM, key)

  # Write request
  print OpenSSL.crypto.dump_certificate_request(OpenSSL.crypto.FILETYPE_PEM, req)


X509 certificate from Certificate Signing Request
+++++++++++++++++++++++++++++++++++++++++++++++++

.. highlight:: python

The following code sample shows how to create an X509 certificate from a
Certificate Signing Request and sign it with a CA::

  ca_cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                            "ca.pem")
  ca_key = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM,
                                          "ca.pem")
  req = OpenSSL.crypto.load_certificate_request(OpenSSL.crypto.FILETYPE_PEM,
                                                open("req.csr").read())

  cert = OpenSSL.crypto.X509()
  cert.set_subject(req.get_subject())
  cert.set_serial_number(1)
  cert.gmtime_adj_notBefore(0)
  cert.gmtime_adj_notAfter(24 * 60 * 60)
  cert.set_issuer(ca_cert.get_subject())
  cert.set_pubkey(req.get_pubkey())
  cert.sign(ca_key, "sha1")

  print OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, cert)


Verify whether X509 certificate matches private key
+++++++++++++++++++++++++++++++++++++++++++++++++++

.. highlight:: python

The code sample below shows how to check whether a certificate matches
with a certain private key. OpenSSL has a function for this,
``X509_check_private_key``, but pyOpenSSL provides no access to it.

::

  ctx = OpenSSL.SSL.Context(OpenSSL.SSL.TLSv1_METHOD)
  ctx.use_privatekey(key)
  ctx.use_certificate(cert)
  try:
    ctx.check_privatekey()
  except OpenSSL.SSL.Error:
    print "Incorrect key"
  else:
    print "Key matches certificate"


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
