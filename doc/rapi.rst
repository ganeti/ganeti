Ganeti remote API
=================

Documents Ganeti version 2.0

.. contents::

Introduction
------------

Ganeti supports a remote API for enable external tools to easily
retrieve information about a cluster's state. The remote API daemon,
*ganeti-rapi*, is automatically started on the master node. By default
it runs on TCP port 5080, but this can be changed either in
``.../constants.py`` or via the command line parameter *-p*. SSL mode,
which is used by default, can also be disabled by passing command line
parameters.

Protocol
--------

The protocol used is JSON_ over HTTP designed after the REST_
principle.

.. _JSON: http://www.json.org/
.. _REST: http://en.wikipedia.org/wiki/Representational_State_Transfer

Usage examples
--------------

You can access the API using your favorite programming language as
long as it supports network connections.

Shell
+++++

Using wget::

  wget -q -O - https://CLUSTERNAME:5080/2/info

or curl::

  curl https://CLUSTERNAME:5080/2/info


Python
++++++

::

  import urllib2
  f = urllib2.urlopen('https://CLUSTERNAME:5080/info')
  print f.read()


JavaScript
++++++++++

.. warning:: While it's possible to use JavaScript, it poses several potential
  problems, including browser blocking request due to
  non-standard ports or different domain names. Fetching the data
  on the webserver is easier.

::

  var url = 'https://CLUSTERNAME:5080/info';
  var info;
  var xmlreq = new XMLHttpRequest();
  xmlreq.onreadystatechange = function () {
    if (xmlreq.readyState != 4) return;
    if (xmlreq.status == 200) {
      info = eval("(" + xmlreq.responseText + ")");
      alert(info);
    } else {
      alert('Error fetching cluster info');
    }
    xmlreq = null;
  };
  xmlreq.open('GET', url, true);
  xmlreq.send(null);

Resources
---------

.. include:: rapi-resources.gen
