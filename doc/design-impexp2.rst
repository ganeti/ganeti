==================================
Design for import/export version 2
==================================

.. contents:: :depth: 4

Current state and shortcomings
------------------------------

Ganeti 2.2 introduced :doc:`inter-cluster instance moves <design-2.2>`
and replaced the import/export mechanism with the same technology. It's
since shown that the chosen implementation was too complicated and and
can be difficult to debug.

The old implementation is henceforth called "version 1". It used
``socat`` in combination with a rather complex tree of ``bash`` and
Python utilities to move instances between clusters and import/export
them inside the cluster. Due to protocol limitations, the master daemon
starts a daemon on the involved nodes and then keeps polling a status
file for updates. A non-trivial number of timeouts ensures that jobs
don't freeze.

In version 1, the destination node would start a daemon listening on a
random TCP port. Upon receiving the destination information, the source
node would temporarily stop the instance, create snapshots, and start
exporting the data by connecting to the destination. The random TCP port
is chosen by the operating system by binding the socket to port 0.
While this is a somewhat elegant solution, it causes problems in setups
with restricted connectivity (e.g. iptables).

Another issue encountered was with dual-stack IPv6 setups. ``socat`` can
only listen on one protocol, IPv4 or IPv6, at a time. The connecting
node can not simply resolve the DNS name, but it must be told the exact
IP address.

Instance OS definitions can provide custom import/export scripts. They
were working well in the early days when a filesystem was usually
created directly on the block device. Around Ganeti 2.0 there was a
transition to using partitions on the block devices. Import/export
scripts could no longer use simple ``dump`` and ``restore`` commands,
but usually ended up doing raw data dumps.


Proposed changes
----------------

Unlike in version 1, in version 2 the destination node will connect to
the source. The active side is swapped. This design assumes the
following design documents have been implemented:

- :doc:`design-x509-ca`
- :doc:`design-http-server`

The following design is mostly targetted at inter-cluster instance
moves. Intra-cluster import and export use the same technology, but do
so in a less complicated way (e.g. reusing the node daemon certificate
in version 1).

Support for instance OS import/export scripts, which have been in Ganeti
since the beginning, will be dropped with this design. Should the need
arise, they can be re-added later.


Software requirements
+++++++++++++++++++++

- HTTP client: cURL/pycURL (already used for inter-node RPC and RAPI
  client)
- Authentication: X509 certificates (server and client)


Transport
+++++++++

Instead of a home-grown, mostly raw protocol the widely used HTTP
protocol will be used. Ganeti already uses HTTP for its :doc:`Remote API
<rapi>` and inter-node communication. Encryption and authentication will
be implemented using SSL and X509 certificates.


SSL certificates
++++++++++++++++

The source machine will identify connecting clients by their SSL
certificate. Unknown certificates will be refused.

Version 1 created a new self-signed certificate per instance
import/export, allowing the certificate to be used as a Certificate
Authority (CA). This worked by means of starting a new ``socat``
instance per instance import/export.

Under the version 2 model, a continously running HTTP server will be
used. This disallows the use of self-signed certificates for
authentication as the CA needs to be the same for all issued
certificates.

See the :doc:`separate design document for more details on how the
certificate authority will be implemented <design-x509-ca>`.

Local imports/exports will, like version 1, use the node daemon's
certificate/key. Doing so allows the verification of local connections.
The client's certificate can be exported to the CGI/FastCGI handler
using lighttpd's ``ssl.verifyclient.exportcert`` setting. If a
cluster-local import/export is being done, the handler verifies if the
used certificate matches with the local node daemon key.


Source
++++++

The source can be the same physical machine as the destination, another
node in the same cluster, or a node in another cluster. A
physical-to-virtual migration mechanism could be implemented as an
alternative source.

In the case of a traditional import, the source is usually a file on the
source machine. For exports and remote imports, the source is an
instance's raw disk data. In all cases the transported data is opaque to
Ganeti.

All nodes of a cluster will run an instance of Lighttpd. The
configuration is automatically generated when starting Ganeti. The HTTP
server is configured to listen on IPv4 and IPv6 simultaneously.
Imports/exports will use a dedicated TCP port, similar to the Remote
API.

See the separate :ref:`HTTP server design document
<http-srv-shortcomings>` for why Ganeti's existing, built-in HTTP server
is not a good choice.

The source cluster is provided with a X509 Certificate Signing Request
(CSR) for a key private to the destination cluster.

After shutting down the instance, creating snapshots and restarting the
instance the master will sign the destination's X509 certificate using
the :doc:`X509 CA <design-x509-ca>` once per instance disk. Instead of
using another identifier, the certificate's serial number (:ref:`never
reused <x509-ca-serial>`) and fingerprint are used to identify incoming
requests. Once ready, the master will call an RPC method on the source
node and provide it with the input information (e.g. file paths or block
devices) and the certificate identities.

The RPC method will write the identities to a place accessible by the
HTTP request handler, generate unique transfer IDs and return them to
the master. The transfer ID could be a filename containing the
certificate's serial number, fingerprint and some disk information. The
file containing the per-transfer information is signed using the node
daemon key and the signature written to a separate file.

Once everything is in place, the master sends the certificates, the data
and notification URLs (which include the transfer IDs) and the public
part of the source's CA to the job submitter. Like in version 1,
everything will be signed using the cluster domain secret.

Upon receiving a request, the handler verifies the identity and
continues to stream the instance data. The serial number and fingerprint
contained in the transfer ID should be matched with the certificate
used. If a cluster-local import/export was requested, the remote's
certificate is verified with the local node daemon key. The signature of
the information file from which the handler takes the path of the block
device (and more) is verified using the local node daemon certificate.
There are two options for handling requests, :ref:`CGI
<lighttpd-cgi-opt>` and :ref:`FastCGI <lighttpd-fastcgi-opt>`.

To wait for all requests to finish, the master calls another RPC method.
The destination should notify the source once it's done with downloading
the data. Since this notification may never arrive (e.g. network
issues), an additional timeout needs to be used.

There is no good way to avoid polling as the HTTP requests will be
handled asynchronously in another process. Once, and if, implemented
:ref:`RPC feedback <rpc-feedback>` could be used to combine the two RPC
methods.

Upon completion of the transfer requests, the instance is removed if
requested.


.. _lighttpd-cgi-opt:

Option 1: CGI
~~~~~~~~~~~~~

While easier to implement, this option requires the HTTP server to
either run as "root" or a so-called SUID binary to elevate the started
process to run as "root".

The export data can be sent directly to the HTTP server without any
further processing.


.. _lighttpd-fastcgi-opt:

Option 2: FastCGI
~~~~~~~~~~~~~~~~~

Unlike plain CGI, FastCGI scripts are run separately from the webserver.
The webserver talks to them via a Unix socket. Webserver and scripts can
run as separate users. Unlike for CGI, there are almost no bootstrap
costs attached to each request.

The FastCGI protocol requires data to be sent in length-prefixed
packets, something which wouldn't be very efficient to do in Python for
large amounts of data (instance imports/exports can be hundreds of
gigabytes). For this reason the proposal is to use a wrapper program
written in C (e.g. `fcgiwrap
<http://nginx.localdomain.pl/wiki/FcgiWrap>`_) and to write the handler
like an old-style CGI program with standard input/output. If data should
be copied from a file, ``cat``, ``dd`` or ``socat`` can be used (see
note about :ref:`sendfile(2)/splice(2) with Python <python-sendfile>`).

The bootstrap cost associated with starting a Python interpreter for
a disk export is expected to be negligible.

The `spawn-fcgi <http://cgit.stbuehler.de/gitosis/spawn-fcgi/about/>`_
program will be used to start the CGI wrapper as "root".

FastCGI is, in the author's opinion, the better choice as it allows user
separation. As a first implementation step the export handler can be run
as a standard CGI program. User separation can be implemented as a
second step.


Destination
+++++++++++

The destination can be the same physical machine as the source, another
node in the same cluster, or a node in another cluster. While not
considered in this design document, instances could be exported from the
cluster by implementing an external client for exports.

For traditional exports the destination is usually a file on the
destination machine. For imports and remote exports, the destination is
an instance's disks. All transported data is opaque to Ganeti.

Before an import can be started, an RSA key and corresponding
Certificate Signing Request (CSR) must be generated using the new opcode
``OpInstanceImportPrepare``. The returned information is signed using
the cluster domain secret. The RSA key backing the CSR must not leave
the destination cluster. After being passed through a third party, the
source cluster will generate signed certificates from the CSR.

Once the request for creating the instance arrives at the master daemon,
it'll create the instance and call an RPC method on the instance's
primary node to download all data. The RPC method does not return until
the transfer is complete or failed (see :ref:`EXP_SIZE_FD <exp-size-fd>`
and :ref:`RPC feedback <rpc-feedback>`).

The node will use pycURL to connect to the source machine and identify
itself with the signed certificate received. pycURL will be configured
to write directly to a file descriptor pointing to either a regular file
or block device. The file descriptor needs to point to the correct
offset for resuming downloads.

Using cURL's multi interface, more than one transfer can be made at the
same time. While parallel transfers are used by the version 1
import/export, it can be decided at a later time whether to use them in
version 2 too. More investigation is necessary to determine whether
``CURLOPT_MAXCONNECTS`` is enough to limit the number of connections or
whether more logic is necessary.

If a transfer fails before it's finished (e.g. timeout or network
issues) it should be retried using an exponential backoff delay. The
opcode submitter can specify for how long the transfer should be
retried.

At the end of a transfer, succssful or not, the source cluster must be
notified. A the same time the RSA key needs to be destroyed.

Support for HTTP proxies can be implemented by setting
``CURLOPT_PROXY``. Proxies could be used for moving instances in/out of
restricted network environments or across protocol borders (e.g. IPv4
networks unable to talk to IPv6 networks).


The big picture for instance moves
----------------------------------

#. ``OpInstanceImportPrepare`` (destination cluster)

  Create RSA key and CSR (certificate signing request), return signed
  with cluster domain secret.

#. ``OpBackupPrepare`` (source cluster)

  Becomes a no-op in version 2, but see :ref:`backwards-compat`.

#. ``OpBackupExport`` (source cluster)

  - Receives destination cluster's CSR, verifies signature using
    cluster domain secret.
  - Creates certificates using CSR and :doc:`cluster CA
    <design-x509-ca>`, one for each disk
  - Stop instance, create snapshots, start instance
  - Prepare HTTP resources on node
  - Send certificates, URLs and CA certificate to job submitter using
    feedback mechanism
  - Wait for all transfers to finish or fail (with timeout)
  - Remove snapshots

#. ``OpInstanceCreate`` (destination cluster)

  - Receives certificates signed by destination cluster, verifies
    certificates and URLs using cluster domain secret

    Note that the parameters should be implemented in a generic way
    allowing future extensions, e.g. to download disk images from a
    public, remote server. The cluster domain secret allows Ganeti to
    check data received from a third party, but since this won't work
    with such extensions, other checks will have to be designed.

  - Create block devices
  - Download every disk from source, verified using remote's CA and
    authenticated using signed certificates
  - Destroy RSA key and certificates
  - Start instance

.. TODO: separate create from import?


.. _impexp2-http-resources:

HTTP resources on source
------------------------

The HTTP resources listed below will be made available by the source
machine. The transfer ID is generated while preparing the export and is
unique per disk and instance. No caching should be used and the
``Pragma`` (HTTP/1.0) and ``Cache-Control`` (HTTP/1.1) headers set
accordingly by the server.

``GET /transfers/[transfer_id]/contents``
  Dump disk contents. Important request headers:

  ``Accept`` (:rfc:`2616`, section 14.1)
    Specify preferred media types. Only one type is supported in the
    initial implementation:

    ``application/octet-stream``
      Request raw disk content.

    If support for more media types were to be implemented in the
    future, the "q" parameter used for "indicating a relative quality
    factor" needs to be used. In the meantime parameters need to be
    expected, but can be ignored.

    If support for OS scripts were to be re-added in the future, the
    MIME type ``application/x-ganeti-instance-export`` is hereby
    reserved for disk dumps using an export script.

    If the source can not satisfy the request the response status code
    will be 406 (Not Acceptable). Successful requests will specify the
    used media type using the ``Content-Type`` header. Unless only
    exactly one media type is requested, the client must handle the
    different response types.

  ``Accept-Encoding`` (:rfc:`2616`, section 14.3)
    Specify desired content coding. Supported are ``identity`` for
    uncompressed data, ``gzip`` for compressed data and ``*`` for any.
    The response will include a ``Content-Encoding`` header with the
    actual coding used. If the client specifies an unknown coding, the
    response status code will be 406 (Not Acceptable).

    If the client specifically needs compressed data (see
    :ref:`impexp2-compression`) but only gets ``identity``, it can
    either compress locally or abort the request.

  ``Range`` (:rfc:`2616`, section 14.35)
    Raw disk dumps can be resumed using this header (e.g. after a
    network issue).

    If this header was given in the request and the source supports
    resuming, the status code of the response will be 206 (Partial
    Content) and it'll include the ``Content-Range`` header as per
    :rfc:`2616`. If it does not support resuming or the request was not
    specifying a range, the status code will be 200 (OK).

    Only a single byte range is supported. cURL does not support
    ``multipart/byteranges`` responses by itself. Even if they could be
    somehow implemented, doing so would be of doubtful benefit for
    import/export.

    For raw data dumps handling ranges is pretty straightforward by just
    dumping the requested range.

    cURL will fail with the error code ``CURLE_RANGE_ERROR`` if a
    request included a range but the server can't handle it. The request
    must be retried without a range.

``POST /transfers/[transfer_id]/done``
  Use this resource to notify the source when transfer is finished (even
  if not successful). The status code will be 204 (No Content).


Code samples
------------

pycURL to file
++++++++++++++

.. highlight:: python

The following code sample shows how to write downloaded data directly to
a file without pumping it through Python::

  curl = pycurl.Curl()
  curl.setopt(pycurl.URL, "http://www.google.com/")
  curl.setopt(pycurl.WRITEDATA, open("googlecom.html", "w"))
  curl.perform()

This works equally well if the file descriptor is a pipe to another
process.


.. _backwards-compat:

Backwards compatibility
-----------------------

.. _backwards-compat-v1:

Version 1
+++++++++

The old inter-cluster import/export implementation described in the
:doc:`Ganeti 2.2 design document <design-2.2>` will be supported for at
least one minor (2.x) release. Intra-cluster imports/exports will use
the new version right away.


.. _exp-size-fd:

``EXP_SIZE_FD``
+++++++++++++++

Together with the improved import/export infrastructure Ganeti 2.2
allowed instance export scripts to report the expected data size. This
was then used to provide the user with an estimated remaining time.
Version 2 no longer supports OS import/export scripts and therefore
``EXP_SIZE_FD`` is no longer needed.


.. _impexp2-compression:

Compression
+++++++++++

Version 1 used explicit compression using ``gzip`` for transporting
data, but the dumped files didn't use any compression. Version 2 will
allow the destination to specify which encoding should be used. This way
the transported data is already compressed and can be directly used by
the client (see :ref:`impexp2-http-resources`). The cURL option
``CURLOPT_ENCODING`` can be used to set the ``Accept-Encoding`` header.
cURL will not decompress received data when
``CURLOPT_HTTP_CONTENT_DECODING`` is set to zero (if another HTTP client
library were used which doesn't support disabling transparent
compression, a custom content-coding type could be defined, e.g.
``x-ganeti-gzip``).


Notes
-----

The HTTP/1.1 protocol (:rfc:`2616`) defines trailing headers for chunked
transfers in section 3.6.1. This could be used to transfer a checksum at
the end of an import/export. cURL supports trailing headers since
version 7.14.1. Lighttpd doesn't seem to support them for FastCGI, but
they appear to be usable in combination with an NPH CGI (No Parsed
Headers).

.. _lighttp-sendfile:

Lighttpd allows FastCGI applications to send the special headers
``X-Sendfile`` and ``X-Sendfile2`` (the latter with a range). Using
these headers applications can send response headers and tell the
webserver to serve regular file stored on the file system as a response
body. The webserver will then take care of sending that file.
Unfortunately this mechanism is restricted to regular files and can not
be used for data from programs, neither direct nor via named pipes,
without writing to a file first. The latter is not an option as instance
data can be very large. Theoretically ``X-Sendfile`` could be used for
sending the input for a file-based instance import, but that'd require
the webserver to run as "root".

.. _python-sendfile:

Python does not include interfaces for the ``sendfile(2)`` or
``splice(2)`` system calls. The latter can be useful for faster copying
of data between file descriptors. There are some 3rd-party modules (e.g.
http://pypi.python.org/pypi/py-sendfile/) and discussions
(http://bugs.python.org/issue10882) for including support for
``sendfile(2)``, but the later is certainly not going to happen for the
Python versions supported by Ganeti. Calling the function using the
``ctypes`` module might be possible.


Performance considerations
--------------------------

The design described above was confirmed to be one of the better choices
in terms of download performance with bigger block sizes. All numbers
were gathered on the same physical machine with a single CPU and 1 GB of
RAM while downloading 2 GB of zeros read from ``/dev/zero``. ``wget``
(version 1.10.2) was used as the client, ``lighttpd`` (version 1.4.28)
as the server. The numbers in the first line are in megabytes per
second. The second line in each row is the CPU time spent in userland
respective system (measured for the CGI/FastCGI program using ``time
-v``).

::

  ----------------------------------------------------------------------
  Block size                      4 KB    64 KB   128 KB    1 MB    4 MB
  ======================================================================
  Plain CGI script reading          83      174      180     122     120
  from ``/dev/zero``
                               0.6/3.9  0.1/2.4  0.1/2.2 0.0/1.9 0.0/2.1
  ----------------------------------------------------------------------
  FastCGI with ``fcgiwrap``,        86      167      170     177     174
  ``dd`` reading from
  ``/dev/zero``                  1.1/5  0.5/2.9  0.5/2.7 0.7/3.1 0.7/2.8
  ----------------------------------------------------------------------
  FastCGI with ``fcgiwrap``,        68      146      150     170     170
  Python script copying from
  ``/dev/zero`` to stdout
                               1.3/5.1  0.8/3.7  0.7/3.3  0.9/2.9  0.8/3
  ----------------------------------------------------------------------
  FastCGI, Python script using      31       48       47       5       1
  ``flup`` library (version
  1.0.2) reading from
  ``/dev/zero``
                              23.5/9.8 14.3/8.5   16.1/8       -       -
  ----------------------------------------------------------------------


It should be mentioned that the ``flup`` library is not implemented in
the most efficient way, but even with some changes it doesn't get much
faster. It is fine for small amounts of data, but not for huge
transfers.


Other considered solutions
--------------------------

Another possible solution considered was to use ``socat`` like version 1
did. Due to the changing model, a large part of the code would've
required a rewrite anyway, while still not fixing all shortcomings. For
example, ``socat`` could still listen on only one protocol, IPv4 or
IPv6. Running two separate instances might have fixed that, but it'd get
more complicated. Using an existing HTTP server will provide us with a
number of other benefits as well, such as easier user separation between
server and backend.


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
