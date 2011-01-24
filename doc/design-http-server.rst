=========================================
Design for replacing Ganeti's HTTP server
=========================================

.. contents:: :depth: 4

.. _http-srv-shortcomings:

Current state and shortcomings
------------------------------

The :doc:`new design for import/export <design-impexp2>` depends on an
HTTP server. Ganeti includes a home-grown HTTP server based on Python's
``BaseHTTPServer``. While it served us well so far, it only implements
the very basics of the HTTP protocol. It is, for example, not structured
well enough to support chunked transfers (:rfc:`2616`, section 3.6.1),
which would have some advantages. In addition, it has not been designed
for sending large responses.

In the case of the node daemon the HTTP server can not easily be
separated from the actual backend code and therefore must run as "root".
The RAPI daemon does request parsing in the same process as talking to
the master daemon via LUXI.


Proposed changes
----------------

The proposal is to start using a full-fledged HTTP server in Ganeti and
to run Ganeti's code as `FastCGI <http://www.fastcgi.com/>`_
applications. Reasons:

- Simplify Ganeti's code by delegating the details of HTTP and SSL to
  another piece of software
- Run HTTP frontend and handler backend as separate processes and users
  (esp. useful for node daemon, but also import/export and Remote API)
- Allows implementation of :ref:`rpc-feedback`


Software choice
+++++++++++++++

Theoretically any server able of speaking FastCGI to a backend process
could be used. However, to keep the number of steps required for setting
up a new cluster at roughly the same level, the implementation will be
geared for one specific HTTP server at the beginning. Support for other
HTTP servers can still be implemented.

After a rough selection of available HTTP servers `lighttpd
<http://www.lighttpd.net/>`_ and `nginx <http://www.nginx.org/>`_ were
the most likely candidates. Both are `widely used`_ and tested.

.. _widely used: http://news.netcraft.com/archives/2011/01/12/
  january-2011-web-server-survey-4.html

Nginx' `original documentation <http://sysoev.ru/nginx/docs/>`_ is in
Russian, translations are `available in a Wiki
<http://wiki.nginx.org/>`_. Nginx does not support old-style CGI
programs.

The author found `lighttpd's documentation
<http://redmine.lighttpd.net/wiki/lighttpd>`_ easier to understand and
was able to configure a test server quickly. This, together with the
support for more technologies, made deciding easier.

With its use as a public-facing web server on a large number of websites
(and possibly more behind proxies), lighttpd should be a safe choice.
Unlike other webservers, such as the Apache HTTP Server, lighttpd's
codebase is of manageable size.

Initially the HTTP server would only be used for import/export
transfers, but its use can be expanded to the Remote API and node
daemon (see :ref:`rpc-feedback`).

To reduce the attack surface, an option will be provided to configure
services (e.g. import/export) to only listen on certain network
interfaces.


.. _rpc-feedback:

RPC feedback
++++++++++++

HTTP/1.1 supports chunked transfers (:rfc:`2616`, section 3.6.1). They
could be used to provide feedback from node daemons to the master,
similar to the feedback from jobs. A good use would be to provide
feedback to the user during long-running operations, e.g. downloading an
instance's data from another cluster.

.. _requirement: http://www.python.org/dev/peps/pep-0333/
  #buffering-and-streaming

WSGI 1.0 (:pep:`333`) includes the following `requirement`_:

  WSGI servers, gateways, and middleware **must not** delay the
  transmission of any block; they **must** either fully transmit the
  block to the client, or guarantee that they will continue transmission
  even while the application is producing its next block

This behaviour was confirmed to work with lighttpd and the
:ref:`flup <http-software-req>` library. FastCGI by itself has no such
guarantee; webservers with buffering might require artificial padding to
force the message to be transmitted.

The node daemon can send JSON-encoded messages back to the master daemon
by separating them using a predefined character (see :ref:`LUXI
<luxi>`). The final message contains the method's result. pycURL passes
each received chunk to the callback set as ``CURLOPT_WRITEFUNCTION``.
Once a message is complete, the master daemon can pass it to a callback
function inside the job, which then decides on what to do (e.g. forward
it as job feedback to the user).

A more detailed design may have to be written before deciding whether to
implement RPC feedback.


.. _http-software-req:

Software requirements
+++++++++++++++++++++

- lighttpd 1.4.24 or above built with OpenSSL support (earlier versions
  `don't support SSL client certificates
  <http://redmine.lighttpd.net/issues/1288>`_)
- `flup <http://trac.saddi.com/flup>`_ for FastCGI


Lighttpd SSL configuration
++++++++++++++++++++++++++

.. highlight:: lighttpd

The following sample shows how to configure SSL with client certificates
in Lighttpd::

  $SERVER["socket"] == ":443" {
    ssl.engine = "enable"
    ssl.pemfile = "server.pem"
    ssl.ca-file = "ca.pem"
    ssl.use-sslv2  = "disable"
    ssl.cipher-list = "HIGH:-DES:-3DES:-EXPORT:-ADH"
    ssl.verifyclient.activate = "enable"
    ssl.verifyclient.enforce = "enable"
    ssl.verifyclient.exportcert = "enable"
    ssl.verifyclient.username = "SSL_CLIENT_S_DN_CN"
  }


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
