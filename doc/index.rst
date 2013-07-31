.. Ganeti documentation master file,
   created by sphinx-quickstart

Welcome to Ganeti's documentation!
==================================

This page is the starting point for browsing the ganeti documentation. It
contains link to all the sections of the documentation, grouped by topic.

The list of changes between Ganeti versions is provided in the :doc:`news` file.

In order to help understanding the Ganeti terminology, a :doc:`glossary` is
provided.

Also see the :ref:`search`.

Installing Ganeti
+++++++++++++++++

In order to install Ganeti, follow the instructions contained in the
:doc:`install`.

If you are an experienced user, the content of the :doc:`install-quick` should
be enough.

Instructions for upgrading an existing installation to the latest version of
Ganeti are contained in the :doc:`upgrade`.

Using Ganeti
++++++++++++

Information about how to manage a Ganeti cluster after it has been installed
(including management of nodes, instances, info about the tools and the
monitoring agent) can be found in :doc:`admin`.

A more example-oriended guide is available in :doc:`walkthrough`.

The various tool that are part of Ganeti are described one by one in the
:doc:`manpages`.

A description of the security model underlying a Ganeti cluster can be found in
the :doc:`security` document.

Ganeti functionalities can be extended by hooking scripts automatically
activated when certain events happen. Information on this mechanism is provided
in the :doc:`hooks` document.

While using Ganeti, the allocation of instances can happen manually or
automatically, through some external tools making decisions about this. The API
for such tools is described in :doc:`iallocator`.

Most of the functionalities of Ganeti can be programmatically accessed through
an API, the :doc:`rapi`.

Compatibility with the standard OVF virtual machine interchange format is
provided by the :doc:`ovfconverter`.

Mainly for testing reasons, Ganeti also has :doc:`virtual-cluster`.

A few functionalities are explicitly targeted for big installations, where
multiple clusters are present. A tool for merging two existing clusters
is provided, and is described in :doc:`cluster-merge`. There is also a document
describing the procedure for :doc:`move-instance`.

Developing Ganeti
+++++++++++++++++

A few documents useful for who wants to modify Ganeti are available and listed
in this section.

A description of the locking strategy and, in particular, lock order
dependencies is presented in :doc:`locking`.

Build dependencies and other useful development-related information are provided
in the :doc:`devnotes`.

All the features implemented in Ganeti are described in a design document before
being actually implemented. Designs can be implemented in a released version, or
be still draft (and therefore either incomplete or not implemented).

Implemented designs
-------------------
.. toctree::
   :maxdepth: 1

   design-2.0.rst
   design-2.1.rst
   design-2.2.rst
   design-2.3.rst
   design-htools-2.3.rst
   design-2.4.rst
   design-2.5.rst
   design-2.6.rst
   design-2.7.rst
   design-2.8.rst

Draft designs
-------------
.. toctree::
   :maxdepth: 2

   design-draft.rst

.. toctree::
   :hidden:

   admin.rst
   cluster-merge.rst
   design-autorepair.rst
   design-bulk-create.rst
   design-chained-jobs.rst
   design-cpu-pinning.rst
   design-device-uuid-name.rst
   design-linuxha.rst
   design-lu-generated-jobs.rst
   design-multi-reloc.rst
   design-network.rst
   design-node-add.rst
   design-oob.rst
   design-opportunistic-locking.rst
   design-ovf-support.rst
   design-query2.rst
   design-reason-trail.rst
   design-restricted-commands.rst
   design-shared-storage.rst
   design-virtual-clusters.rst
   devnotes.rst
   glossary.rst
   hooks.rst
   iallocator.rst
   install.rst
   install-quick.rst
   locking.rst
   manpages.rst
   monitoring-query-format.rst
   move-instance.rst
   news.rst
   ovfconverter.rst
   rapi.rst
   security.rst
   upgrade.rst
   virtual-cluster.rst
   walkthrough

.. vim: set textwidth=72 :
